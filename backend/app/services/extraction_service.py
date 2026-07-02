"""Orchestrates the full extraction pipeline across one or more documents:
raw extraction -> deterministic parse (rent roll / T-12) with LLM fallback
when it finds too little -> LLM extraction directly for OMs and "other"
documents -> aggregation into the app's existing input-schema fields ->
cross-validation. Nothing here is trusted automatically — the result is a
set of field-level proposals with provenance and confidence for the review
screen; only user-confirmed values ever reach the deal input form.
"""

import re
from pathlib import Path

from app.models import Document
from app.services import mapping_service
from app.services.extraction import (
    cross_validation,
    excel_extractor,
    llm_extraction,
    pdf_extractor,
    rent_roll_parser,
    t12_parser,
)

_MIN_DETERMINISTIC_ROWS = 2
_MULTIFAMILY_UNIT_TYPE_RE = re.compile(r"\d\s*(bd|bed|br)\b", re.IGNORECASE)


def _allowed_fields() -> list[dict]:
    return mapping_service.load_flat_fields(include_outputs=False)


def _load_grid_and_text(doc: Document) -> tuple[dict | None, str, list[str]]:
    path = Path(doc.stored_path)
    ext = doc.file_ext
    warnings: list[str] = []

    if ext in ("xlsx", "xls", "csv"):
        try:
            grid = excel_extractor.extract_grid(path, ext)
        except Exception as exc:  # noqa: BLE001
            return None, "", [f"{doc.filename}: could not parse spreadsheet ({exc})"]
        text_rows = [grid["headers"]] + grid["rows"][:150]
        text = "\n".join(", ".join(str(c) for c in row) for row in text_rows)
        return grid, text, warnings

    if ext == "pdf":
        pdf_data = pdf_extractor.extract_pdf(path)
        if pdf_data["scanned"]:
            warnings.append(f"{doc.filename}: {pdf_data['ocrNote']}")
        text = pdf_extractor.full_text(pdf_data)

        best_table, best_page = None, None
        for page in pdf_data["pages"]:
            for table in page["tables"]:
                if table and len(table) > len(best_table or []):
                    best_table, best_page = table, page["pageNumber"]

        grid = None
        if best_table and len(best_table) >= 2:
            headers = [str(h) if h is not None else "" for h in best_table[0]]
            grid = {"headers": headers, "rows": best_table[1:], "sheet": f"page {best_page}"}
        return grid, text, warnings

    return None, "", [f"{doc.filename}: unsupported file type for extraction"]


def _extract_rent_roll(doc: Document, grid: dict | None, text: str, warnings: list[str]) -> dict:
    rent_rows: list[dict] = []
    scalars: list[dict] = []
    unmatched: list[dict] = []

    if grid:
        parsed = rent_roll_parser.parse_rows(grid["headers"], grid["rows"], doc.filename, grid["sheet"])
        if len(parsed["rows"]) >= _MIN_DETERMINISTIC_ROWS and parsed["confidence"] >= 0.5:
            for r in parsed["rows"]:
                rent_rows.append({**r, "confidence": parsed["confidence"], "source": "deterministic"})

    if not rent_rows:
        warnings.append(f"{doc.filename}: header matching found too little — used the LLM instead.")
        llm = llm_extraction.extract_with_llm("rent_roll", text, doc.filename, _allowed_fields())
        if llm["result"]:
            for r in llm["result"]["rentRollRows"]:
                rent_rows.append({**r, "source": "llm"})
            scalars.extend({**s, "source": "llm"} for s in llm["result"]["scalarExtractions"])
            unmatched.extend(llm["result"]["unmatchedExtractions"])
            warnings.extend(llm["result"]["warnings"])
        elif llm["note"]:
            warnings.append(f"{doc.filename}: {llm['note']}")

    return {
        "scalarExtractions": scalars,
        "rentRollRows": rent_rows,
        "t12LineItems": [],
        "unmatchedExtractions": unmatched,
        "warnings": warnings,
    }


def _extract_t12(doc: Document, grid: dict | None, text: str, warnings: list[str]) -> dict:
    line_items: list[dict] = []
    scalars: list[dict] = []
    unmatched: list[dict] = []

    if grid:
        parsed = t12_parser.parse_t12(grid["headers"], grid["rows"], doc.filename, grid["sheet"])
        if len(parsed["lineItems"]) >= _MIN_DETERMINISTIC_ROWS and parsed["confidence"] >= 0.4:
            if parsed["annualized"]:
                warnings.append(
                    f"{doc.filename}: detected as a {parsed['periodType']} statement — annualized "
                    f"(×{parsed['annualizeFactor']})."
                )
            for li in parsed["lineItems"]:
                line_items.append({**li, "source": "deterministic", "confidence": parsed["confidence"]})

    if not line_items:
        warnings.append(f"{doc.filename}: period-column detection found too little — used the LLM instead.")
        llm = llm_extraction.extract_with_llm("t12_operating_statement", text, doc.filename, _allowed_fields())
        if llm["result"]:
            for li in llm["result"]["t12LineItems"]:
                line_items.append(
                    {
                        "label": li["label"],
                        "amount": li["amount"],
                        "category": li["mappedCategory"],
                        "bucket": "expense" if li["mappedCategory"] in t12_parser.EXPENSE_CATEGORIES else "income",
                        "isNonRecurring": li["isNonRecurring"],
                        "sourceRef": li["sourceRef"],
                        "source": "llm",
                        "confidence": li["confidence"],
                    }
                )
            scalars.extend({**s, "source": "llm"} for s in llm["result"]["scalarExtractions"])
            unmatched.extend(llm["result"]["unmatchedExtractions"])
            warnings.extend(llm["result"]["warnings"])
        elif llm["note"]:
            warnings.append(f"{doc.filename}: {llm['note']}")

    return {
        "scalarExtractions": scalars,
        "rentRollRows": [],
        "t12LineItems": line_items,
        "unmatchedExtractions": unmatched,
        "warnings": warnings,
    }


def _extract_narrative(doc: Document, text: str, warnings: list[str]) -> dict:
    """Offering Memoranda and anything classified 'other' — narrative content
    deterministic parsing doesn't apply to, so this goes straight to the LLM.
    """
    llm = llm_extraction.extract_with_llm(doc.document_type, text, doc.filename, _allowed_fields())
    if llm["result"]:
        r = llm["result"]
        return {
            "scalarExtractions": [{**s, "source": "llm"} for s in r["scalarExtractions"]],
            "rentRollRows": [{**x, "source": "llm"} for x in r["rentRollRows"]],
            "t12LineItems": [{**x, "source": "llm"} for x in r["t12LineItems"]],
            "unmatchedExtractions": r["unmatchedExtractions"],
            "warnings": warnings + r["warnings"],
        }
    if llm["note"]:
        warnings.append(f"{doc.filename}: {llm['note']}")
    return {
        "scalarExtractions": [],
        "rentRollRows": [],
        "t12LineItems": [],
        "unmatchedExtractions": [],
        "warnings": warnings,
    }


def _looks_multifamily(rows: list[dict]) -> bool:
    typed = [r for r in rows if r.get("unitType")]
    if not typed:
        return False
    matches = sum(1 for r in typed if _MULTIFAMILY_UNIT_TYPE_RE.search(str(r["unitType"])))
    return matches / len(typed) > 0.5


def _field_entry(value, source_ref, confidence, source, raw_text=None, notes=None) -> dict:
    return {
        "value": value,
        "sourceRef": source_ref,
        "confidence": confidence,
        "source": source,
        "rawText": raw_text,
        "notes": notes,
    }


def _aggregate_to_fields(merged: dict) -> dict:
    """Turn merged scalarExtractions / rentRollRows / t12LineItems into a flat
    {fieldId: {value, sourceRef, confidence, source, ...}} dict shaped to
    match the deal input form. A few internal-only keys (prefixed "_") carry
    values cross_validation.py needs but that aren't real input-schema fields.
    """
    fields: dict[str, dict] = {}

    for s in merged["scalarExtractions"]:
        fields[s["fieldId"]] = _field_entry(
            s["value"], s["sourceRef"], s["confidence"], s.get("source", "llm"), s.get("rawText"), s.get("notes")
        )

    if merged["rentRollRows"]:
        rows = merged["rentRollRows"]
        confidence = sum(r.get("confidence", 0.5) for r in rows) / len(rows)
        source = rows[0].get("source", "deterministic")
        doc_ref = {"doc": rows[0].get("sourceRef", {}).get("doc"), "sheet": None, "page": None, "cell": None, "row": None}

        if _looks_multifamily(rows):
            agg = rent_roll_parser.aggregate_multifamily(rows)
            fields["unitMix"] = _field_entry(agg["unitMix"], doc_ref, confidence, source)
            if agg["occupancyPctByUnit"] is not None:
                fields["vacancyPct"] = _field_entry(round(1 - agg["occupancyPctByUnit"], 4), doc_ref, confidence, source)
                fields["_occupancyPct"] = _field_entry(agg["occupancyPctByUnit"], doc_ref, confidence, source)
            if agg["lossToLeasePct"] is not None:
                fields["lossToLeasePct"] = _field_entry(agg["lossToLeasePct"], doc_ref, confidence, source)
            fields["_rentRollGprAnnual"] = _field_entry(
                round(agg["grossPotentialRentMonthly"] * 12, 2), doc_ref, confidence, source
            )
            if "grossPotentialRent" not in fields:
                fields["grossPotentialRent"] = _field_entry(
                    round(agg["grossPotentialRentMonthly"] * 12, 2), doc_ref, confidence, source
                )
        else:
            agg = rent_roll_parser.aggregate_commercial(rows)
            fields["rentRoll"] = _field_entry(agg["rentRoll"], doc_ref, confidence, source)
            if agg["occupancyPctBySf"] is not None:
                fields["retailVacancyPct"] = _field_entry(round(1 - agg["occupancyPctBySf"], 4), doc_ref, confidence, source)
                fields["_occupancyPct"] = _field_entry(agg["occupancyPctBySf"], doc_ref, confidence, source)
            fields["_rentRollGprAnnual"] = _field_entry(
                round(agg["grossPotentialRentMonthly"] * 12, 2), doc_ref, confidence, source
            )

    if merged["t12LineItems"]:
        items = merged["t12LineItems"]
        confidence = sum(li.get("confidence", 0.5) for li in items) / len(items) if items else 0.5
        source = items[0].get("source", "deterministic")
        doc_ref = {"doc": items[0].get("sourceRef", {}).get("doc"), "sheet": None, "page": None, "cell": None, "row": None}
        agg = t12_parser.aggregate_categories(items)

        gpr = agg["income"].get("grossPotentialRent")
        vacancy_loss = agg["income"].get("vacancyLoss")
        if gpr:
            fields["grossPotentialRent"] = _field_entry(round(gpr, 2), doc_ref, confidence, source)
            if vacancy_loss:
                fields["vacancyPct"] = _field_entry(round(abs(vacancy_loss) / gpr, 4), doc_ref, confidence, source)
        if agg["income"].get("creditLoss"):
            fields["creditLoss"] = _field_entry(round(abs(agg["income"]["creditLoss"]), 2), doc_ref, confidence, source)
        if agg["income"].get("otherIncome"):
            fields["otherIncome"] = _field_entry(round(agg["income"]["otherIncome"], 2), doc_ref, confidence, source)

        for category, amount in agg["expenses"].items():
            if category == "other":
                continue
            if category == "managementFeePct" and gpr:
                # T-12 gives a dollar amount; the schema field is a % of revenue.
                fields[category] = _field_entry(round(amount / gpr, 4), doc_ref, confidence, source, notes="Converted from $ amount using GPR.")
            elif category == "managementFeePct":
                fields["_unmatchedManagementFeeAmount"] = _field_entry(amount, doc_ref, confidence, source)
            else:
                fields[category] = _field_entry(round(amount, 2), doc_ref, confidence, source)

        if agg["noi"] is not None:
            fields["_noi"] = _field_entry(agg["noi"], doc_ref, confidence, source)
        if agg["totalExpenses"] is not None:
            fields["_totalExpenses"] = _field_entry(agg["totalExpenses"], doc_ref, confidence, source)

    return fields


def run_extraction(documents: list[Document]) -> dict:
    merged = {"scalarExtractions": [], "rentRollRows": [], "t12LineItems": [], "unmatchedExtractions": [], "warnings": []}

    for doc in documents:
        grid, text, doc_warnings = _load_grid_and_text(doc)

        if doc.document_type == "rent_roll":
            result = _extract_rent_roll(doc, grid, text, doc_warnings)
        elif doc.document_type == "t12_operating_statement":
            result = _extract_t12(doc, grid, text, doc_warnings)
        else:
            result = _extract_narrative(doc, text, doc_warnings)

        for key in ("scalarExtractions", "rentRollRows", "t12LineItems", "unmatchedExtractions"):
            merged[key].extend(result[key])
        merged["warnings"].extend(result["warnings"])

    fields = _aggregate_to_fields(merged)

    # "asking price"-style scalars from an OM feed cross-validation even
    # though they're not the schema's canonical purchasePrice field name.
    if "_statedCapRate" not in fields and "goingInCapRate" in fields:
        fields["_statedCapRate"] = fields["goingInCapRate"]

    checks = cross_validation.run_checks(fields)

    # Internal-only fields (prefixed "_") are cross-validation inputs, not
    # real proposals — strip them before they'd ever reach the review screen.
    visible_fields = {k: v for k, v in fields.items() if not k.startswith("_")}

    return {
        "fields": visible_fields,
        "unmatchedExtractions": merged["unmatchedExtractions"],
        "crossValidation": checks,
        "warnings": merged["warnings"],
    }
