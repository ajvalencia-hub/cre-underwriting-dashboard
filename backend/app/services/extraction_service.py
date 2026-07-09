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
    operating_statement_parser,
    pdf_extractor,
    rent_roll_parser,
    t12_parser,
)

_MIN_DETERMINISTIC_ROWS = 2
_MIN_OPSTMT_MATCHES = 3
# A hyphen between the digit and "bed" ("1-Bed", "2-Bed 2-Bath Loft") is at
# least as common as a plain space in real rent rolls — [\s-]* (not \s*)
# covers both, plus the no-separator case ("1BR").
_MULTIFAMILY_UNIT_TYPE_RE = re.compile(r"\d[\s-]*(bd|bed|br)\b", re.IGNORECASE)


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

        grid, table_warnings = _grid_from_pdf_tables(pdf_data["pages"])
        warnings.extend(f"{doc.filename}: {w}" for w in table_warnings)
        return grid, text, warnings

    return None, "", [f"{doc.filename}: unsupported file type for extraction"]


def _grid_from_pdf_tables(pages: list[dict]) -> tuple[dict | None, list[str]]:
    """Merge same-shape tables across pages into one grid. Rent rolls routinely
    span many PDF pages as one logical table (with or without repeated header
    rows); keeping only the single largest table silently truncated the roll
    to one page's units (FINDINGS.md C2). Tables whose column count differs
    from the main table's (summaries, disclaimers) are left out.
    """
    tables: list[tuple[int, list[list]]] = []  # (pageNumber, table) in document order
    for page in pages:
        for table in page["tables"]:
            if table and any(row for row in table):
                tables.append((page["pageNumber"], table))
    if not tables:
        return None, []

    # The main table shape = the column count whose tables carry the most rows.
    rows_by_width: dict[int, int] = {}
    for _, table in tables:
        width = max(len(row) for row in table)
        rows_by_width[width] = rows_by_width.get(width, 0) + len(table)
    main_width = max(rows_by_width, key=lambda w: rows_by_width[w])
    group = [(p, t) for p, t in tables if max(len(row) for row in t) == main_width]

    first_page, first_table = group[0]
    headers = [str(h).strip() if h is not None else "" for h in first_table[0]]
    norm_headers = [h.lower() for h in headers]

    rows: list[list] = list(first_table[1:])
    for _, table in group[1:]:
        first_row_norm = [str(c).strip().lower() if c is not None else "" for c in table[0]]
        # Continuation pages often repeat the header row — drop the repeat.
        rows.extend(table[1:] if first_row_norm == norm_headers else table)

    if not rows:
        return None, []

    last_page = group[-1][0]
    grid = {
        "headers": headers,
        "rows": rows,
        "sheet": f"page {first_page}" if len(group) == 1 else f"pages {first_page}-{last_page}",
    }
    warnings = []
    if len(group) > 1:
        warnings.append(
            f"merged {len(group)} tables (pages {first_page}-{last_page}) into one grid — "
            "verify no unrelated tables were combined."
        )
    return grid, warnings


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
            # Internal-only parse metadata for cross-validation (month
            # coverage) — "_" prefix keeps it off the review screen.
            doc_ref = {"doc": doc.filename, "sheet": grid["sheet"], "page": None, "cell": None, "row": None}
            scalars.append(
                {"fieldId": "_t12Months", "value": parsed["monthHeaders"],
                 "sourceRef": doc_ref, "confidence": parsed["confidence"]}
            )
            scalars.append(
                {"fieldId": "_t12PeriodType", "value": parsed["periodType"],
                 "sourceRef": doc_ref, "confidence": parsed["confidence"]}
            )

    if not line_items:
        warnings.append(f"{doc.filename}: period-column detection found too little — used the LLM instead.")
        llm = llm_extraction.extract_with_llm("t12_operating_statement", text, doc.filename, _allowed_fields())
        if llm["result"]:
            for li in llm["result"]["t12LineItems"]:
                category = li["mappedCategory"]
                if category in t12_parser.EXPENSE_CATEGORIES:
                    bucket = "expense"
                elif category in t12_parser.INCOME_CATEGORIES:
                    bucket = "income"
                else:
                    # No category means we don't know income vs expense — mark it
                    # unknown so aggregation surfaces it instead of silently
                    # dropping it (previously these were mislabeled "income").
                    bucket = "unknown"
                line_items.append(
                    {
                        "label": li["label"],
                        "amount": li["amount"],
                        "category": category,
                        "bucket": bucket,
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


_MULTIFAMILY_UNIT_ID_RE = re.compile(r"^\s*unit\s*#?\s*\d", re.IGNORECASE)
# "Studio" units carry no bed-count digit at all — that's correct, not a
# gap in _MULTIFAMILY_UNIT_TYPE_RE — but on a studio-heavy property (this
# regression's own fixture is 63% studios) excluding them from the
# match-ratio numerator can keep a 100% residential rent roll under the
# >0.5 threshold even once every non-studio label matches correctly.
_STUDIO_UNIT_TYPE_RE = re.compile(r"\bstudio\b", re.IGNORECASE)


def _looks_multifamily(rows: list[dict]) -> bool:
    typed = [r for r in rows if r.get("unitType")]
    if typed:
        matches = sum(
            1 for r in typed
            if _MULTIFAMILY_UNIT_TYPE_RE.search(str(r["unitType"]))
            or _STUDIO_UNIT_TYPE_RE.search(str(r["unitType"]))
        )
        if matches / len(typed) > 0.5:
            return True
    # No usable unitType column — a common shape for small/simple rent rolls
    # (bed/bath is implied by SF, never labeled). Fall back to structural
    # signals: apartment-style "Unit N" ids and/or a generic "Residential"
    # tenant placeholder (vs. a company/lessee name on a commercial roll).
    if not rows:
        return False
    residential_tenant = sum(1 for r in rows if str(r.get("tenant") or "").strip().lower() == "residential")
    unit_n_id = sum(1 for r in rows if r.get("unit") and _MULTIFAMILY_UNIT_ID_RE.match(str(r["unit"])))
    return residential_tenant / len(rows) > 0.5 or unit_n_id / len(rows) > 0.5


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
        doc_ref = {"doc": rows[0].get("sourceRef", {}).get("doc"), "sheet": None, "page": None, "cell": None, "row": None}  # noqa: E501

        if _looks_multifamily(rows):
            agg = rent_roll_parser.aggregate_multifamily(rows)
            fields["unitMix"] = _field_entry(agg["unitMix"], doc_ref, confidence, source)
            fields["_rentRollTotalUnits"] = _field_entry(agg["totalUnits"], doc_ref, confidence, source)
            if agg["occupancyPctByUnit"] is not None:
                fields["vacancyPct"] = _field_entry(round(1 - agg["occupancyPctByUnit"], 4), doc_ref, confidence, source)  # noqa: E501
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
            fields["_rentRollTotalUnits"] = _field_entry(agg["totalUnits"], doc_ref, confidence, source)
            if agg["occupancyPctBySf"] is not None:
                fields["retailVacancyPct"] = _field_entry(round(1 - agg["occupancyPctBySf"], 4), doc_ref, confidence, source)  # noqa: E501
                fields["_occupancyPct"] = _field_entry(agg["occupancyPctBySf"], doc_ref, confidence, source)
            fields["_rentRollGprAnnual"] = _field_entry(
                round(agg["grossPotentialRentMonthly"] * 12, 2), doc_ref, confidence, source
            )

    if merged["t12LineItems"]:
        items = merged["t12LineItems"]
        confidence = sum(li.get("confidence", 0.5) for li in items) / len(items) if items else 0.5
        source = items[0].get("source", "deterministic")
        doc_ref = {"doc": items[0].get("sourceRef", {}).get("doc"), "sheet": None, "page": None, "cell": None, "row": None}  # noqa: E501
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

        # Management fee $ -> % conversion basis. Industry convention is % of
        # EGI (collections), not GPR — GPR overstates the denominator and
        # understates the pct. Prefer the statement's own EGI line, then a
        # derived EGI, then GPR as a last resort; the note always names the
        # basis actually used.
        vacancy_abs = abs(vacancy_loss) if vacancy_loss else 0
        credit_abs = abs(agg["income"].get("creditLoss") or 0)
        other_inc = agg["income"].get("otherIncome") or 0
        stated_egi = agg["income"].get("effectiveGrossIncome")
        if stated_egi and stated_egi > 0:
            fee_basis, fee_basis_label = stated_egi, "the statement's EGI line"
        elif gpr and (vacancy_abs or credit_abs or other_inc) and gpr - vacancy_abs - credit_abs + other_inc > 0:
            fee_basis = gpr - vacancy_abs - credit_abs + other_inc
            fee_basis_label = "EGI derived as GPR less vacancy/credit loss plus other income"
        elif gpr:
            fee_basis, fee_basis_label = gpr, "GPR (EGI not derivable from this statement)"
        else:
            fee_basis, fee_basis_label = None, None

        sign_normalized = set(agg["signNormalizedExpenses"])
        sign_note = "Reported as a negative number in the source statement; sign normalized."
        for category, amount in agg["expenses"].items():
            if category == "other":
                continue
            notes = sign_note if category in sign_normalized else None
            if category == "managementFeePct" and fee_basis:
                # T-12 gives a dollar amount; the schema field is a % of revenue.
                conversion_note = f"Converted from $ amount using {fee_basis_label}."
                fields[category] = _field_entry(
                    round(amount / fee_basis, 4), doc_ref, confidence, source,
                    notes=f"{conversion_note} {notes}" if notes else conversion_note,
                )
            elif category == "managementFeePct":
                fields["_unmatchedManagementFeeAmount"] = _field_entry(amount, doc_ref, confidence, source)
            else:
                fields[category] = _field_entry(round(amount, 2), doc_ref, confidence, source, notes=notes)
        if sign_normalized:
            merged["warnings"].append(
                "Expense categories reported as negative numbers were sign-normalized to "
                f"positive amounts: {', '.join(sorted(sign_normalized))}. Verify these are "
                "expenses, not credits."
            )

        if agg["noi"] is not None:
            fields["_noi"] = _field_entry(agg["noi"], doc_ref, confidence, source)
        if agg["totalExpenses"] is not None:
            fields["_totalExpenses"] = _field_entry(agg["totalExpenses"], doc_ref, confidence, source)

        # Lines that matched no category are excluded from every field above —
        # that exclusion must be visible, not silent: list each one in the
        # review screen's unmatched section and summarize in a warning.
        if agg["unclassified"]:
            unclassified_total = sum(li["amount"] for li in agg["unclassified"])
            for li in agg["unclassified"]:
                merged["unmatchedExtractions"].append(
                    {
                        "suggestedLabel": f"T-12 line: {li['label']}",
                        "value": li["amount"],
                        "rawText": li["label"],
                        "sourceRef": li.get("sourceRef") or doc_ref,
                        "confidence": li.get("confidence", 0.5),
                    }
                )
            merged["warnings"].append(
                f"{len(agg['unclassified'])} T-12 line item(s) totaling ${unclassified_total:,.0f} "
                "didn't match any standard income/expense category and are NOT included in any "
                "extracted field — review them in the unmatched list below."
            )

    return fields


def run_extraction(documents: list[Document]) -> dict:
    merged: dict = {
        "scalarExtractions": [], "rentRollRows": [], "t12LineItems": [], "unmatchedExtractions": [], "warnings": [],
    }

    for doc in documents:
        grid, text, doc_warnings = _load_grid_and_text(doc)

        if doc.document_type == "rent_roll":
            result = _extract_rent_roll(doc, grid, text, doc_warnings)
        elif doc.document_type == "t12_operating_statement":
            result = _extract_t12(doc, grid, text, doc_warnings)
        else:
            result = _extract_narrative(doc, text, doc_warnings)

        # A spreadsheet can carry income-statement content even when it's
        # classified rent_roll (or vice versa) — brokers routinely stack a
        # rent roll and a simple "label: value" income statement in one
        # sheet. Opportunistically look for that shape on every grid,
        # independent of the doc's classified type, and merge in whatever it
        # finds (never overwriting a scalar the primary parser already
        # produced for this document).
        if grid and doc.document_type != "t12_operating_statement":
            opstmt = operating_statement_parser.parse_label_value_pairs(
                grid["headers"], grid["rows"], doc.filename, grid["sheet"]
            )
            if opstmt["matchedRows"] >= _MIN_OPSTMT_MATCHES:
                existing_ids = {s["fieldId"] for s in result["scalarExtractions"]}
                for s in opstmt["scalars"]:
                    if s["fieldId"] in existing_ids:
                        continue
                    result["scalarExtractions"].append(
                        {
                            "fieldId": s["fieldId"],
                            "value": s["value"],
                            "sourceRef": s["sourceRef"],
                            "confidence": opstmt["confidence"],
                            "source": "deterministic",
                            "rawText": s["rawText"],
                        }
                    )

        for key in ("scalarExtractions", "rentRollRows", "t12LineItems", "unmatchedExtractions"):
            merged[key].extend(result[key])
        merged["warnings"].extend(result["warnings"])

    # Multiple documents of the same type are summed/combined into single
    # fields below — a YTD plus a prior-year T-12 would double every category.
    # That can be intended (one statement per building) but must never be silent.
    for doc_type, label in (("t12_operating_statement", "T-12"), ("rent_roll", "rent roll")):
        names = [d.filename for d in documents if d.document_type == doc_type]
        if len(names) > 1:
            merged["warnings"].append(
                f"{len(names)} {label} documents were merged ({', '.join(names)}) — their "
                "line items are combined into single fields, so overlapping periods or "
                "duplicate rolls will double-count. Deselect duplicates if that's not intended."
            )

    fields = _aggregate_to_fields(merged)

    # Proposed unit-mix block (G5): the reviewable grouped table with
    # per-group provenance, for multifamily rent rolls. Same grouping
    # implementation as fields["unitMix"] (rent_roll_parser.propose_unit_mix).
    unit_mix_proposal = None
    commercial_lease_proposal = None
    if merged["rentRollRows"] and _looks_multifamily(merged["rentRollRows"]):
        unit_mix_proposal = rent_roll_parser.propose_unit_mix(merged["rentRollRows"])
        merged["warnings"].extend(unit_mix_proposal["warnings"])
    elif merged["rentRollRows"]:
        # Non-multifamily rolls propose lease-level rows (H1) through the
        # same human-review gate.
        commercial_lease_proposal = rent_roll_parser.propose_commercial_leases(
            merged["rentRollRows"]
        )
        merged["warnings"].extend(commercial_lease_proposal["warnings"])
        if not commercial_lease_proposal["rows"]:
            commercial_lease_proposal = None

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
        "unitMixProposal": unit_mix_proposal,
        "commercialLeaseProposal": commercial_lease_proposal,
    }
