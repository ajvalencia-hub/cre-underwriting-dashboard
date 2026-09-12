"""Deterministic parsing for the common two-column 'label: value' income
statement layout (a label cell followed by a single dollar figure) — distinct
from t12_parser.py's columnar 12-month/Total-column format. Brokers routinely
stack this alongside a rent roll in one sheet (e.g. "current in-place" and
"pro-forma" income/expense blocks sitting below the unit table); this parser
recovers those scalars from ANY grid, independent of the document's
classified type, since a rent-roll-classified spreadsheet can still carry
this content (extraction_service.py runs it opportunistically on every
grid).

Section-aware: these statements often repeat the same labels once for
"current/in-place" figures and once for "pro-forma" figures. Pro-forma values
win for shared line items (they're the forward-looking basis underwriting
uses); in-place/pro-forma NOI are captured only via their own explicit,
EXACT-match labels so a "@ 100% occupancy w/ 3rd-party management" what-if
variant sitting next to the real headline NOI line can't be mistaken for it.
"""

import re

from app.services.extraction.excel_extractor import parse_numeric

_PRICE_ALIASES = ["asking price", "purchase price", "list price", "sale price"]

# Deliberately EXACT-match only (see module docstring) — these labels are
# frequently followed by qualified "what-if" variants (different occupancy /
# management assumptions) that must NOT be mistaken for the headline figure.
_IN_PLACE_NOI_ALIASES = ["in place net operating income", "in place noi", "current noi"]
_STABILIZED_NOI_ALIASES = [
    "pro forma net operating income", "pro forma noi", "stabilized noi", "proforma noi",
]

_INCOME_ALIASES: dict[str, list[str]] = {
    "grossPotentialRent": [
        "gross annual income", "gross potential rent", "gross scheduled income",
    ],
    "otherIncome": ["other income", "ancillary income", "misc income", "miscellaneous income"],
}
# managementFeePct is deliberately excluded — the schema field is a % of
# revenue, but a two-column statement only ever gives a $ amount here, and
# converting correctly needs an EGI basis this row-by-row parser doesn't have
# (t12_parser.py's columnar path does that conversion properly).
_EXPENSE_ALIASES: dict[str, list[str]] = {
    "realEstateTaxes": ["property taxes", "real estate tax", "re tax"],
    "insurance": ["insurance"],
    "utilities": ["electric", "water sewer", "water and sewer", "utilities", "gas"],
    "repairsMaintenance": ["maintenance", "repairs and maintenance", "repairs"],
    "generalAdmin": ["landscaping", "trash", "general and administrative", "admin"],
}

_PRO_FORMA_KEYWORDS = ("pro forma", "proforma", "pro-forma", "stabilized")
_IN_PLACE_KEYWORDS = ("in place", "in-place", "current in")

_SUBSTRING_ALIASES: list[tuple[str, list[str]]] = (
    [("purchasePrice", _PRICE_ALIASES)]
    + list(_INCOME_ALIASES.items())
    + list(_EXPENSE_ALIASES.items())
)

# Expense buckets that legitimately aggregate several distinct broker line
# items (utilities = electric + water/sewer + gas, etc.) — summed within a
# section rather than the last match silently replacing the others.
_SUMMABLE_EXPENSE_FIELDS = set(_EXPENSE_ALIASES.keys())

_MIN_LABEL_CHARS = 3


def _normalize(text: str) -> str:
    text = re.sub(r"[-_/():%]", " ", text.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text)).strip()


def _classify_substring(norm_label: str) -> str | None:
    for field_id, aliases in _SUBSTRING_ALIASES:
        for alias in aliases:
            na = _normalize(alias)
            if na in norm_label or norm_label in na:
                return field_id
    return None


def _classify_noi(norm_label: str) -> str | None:
    if norm_label in (_normalize(a) for a in _IN_PLACE_NOI_ALIASES):
        return "inPlaceNoi"
    if norm_label in (_normalize(a) for a in _STABILIZED_NOI_ALIASES):
        return "stabilizedNoi"
    return None


def _section_for(norm_label: str) -> str | None:
    if any(kw in norm_label for kw in _PRO_FORMA_KEYWORDS):
        return "pro_forma"
    if any(kw in norm_label for kw in _IN_PLACE_KEYWORDS):
        return "in_place"
    return None


def _label_value_pairs_in_row(row: list) -> list[tuple[str, float, int]]:
    """Scan every adjacent (text, number) cell pair in the row — not just
    column 0/1 — since these statements routinely pack a second label:value
    pair further along the same row (e.g. an "Asking Price:" aside next to
    an unrelated expense line)."""
    pairs = []
    for i in range(len(row) - 1):
        cell = row[i]
        if cell is None:
            continue
        text = str(cell).strip()
        if len(text) < _MIN_LABEL_CHARS or parse_numeric(cell) is not None:
            continue  # empty, too short, or itself numeric — not a label
        value = parse_numeric(row[i + 1])
        if value is not None:
            pairs.append((text, value, i + 1))
    return pairs


def parse_label_value_pairs(headers: list[str], data_rows: list[list], source_doc: str, sheet: str) -> dict:
    """Returns {"scalars": [{fieldId, value, sourceRef, rawText}], "matchedRows": int, "confidence": float}."""
    section: str | None = None
    hits: dict[str, dict] = {}
    matched_rows = 0

    for row_idx, row in enumerate(data_rows):
        pairs = _label_value_pairs_in_row(row)
        if not pairs:
            first_text = next((str(c).strip() for c in row if c is not None and str(c).strip()), None)
            if first_text:
                new_section = _section_for(_normalize(first_text))
                if new_section:
                    section = new_section
            continue

        row_matched = False
        for label_str, value, value_col in pairs:
            norm_label = _normalize(label_str)
            if not norm_label:
                continue

            noi_field = _classify_noi(norm_label)
            field_id = noi_field or _classify_substring(norm_label)
            if not field_id:
                continue

            row_matched = True
            source_ref = {"doc": source_doc, "sheet": sheet, "row": row_idx, "page": None, "cell": None}
            entry = {
                "fieldId": field_id,
                "value": round(value, 2),
                "sourceRef": source_ref,
                "rawText": label_str,
                "section": section,
            }

            existing = hits.get(field_id)
            if existing is None:
                hits[field_id] = entry
            elif noi_field:
                # Exact-match NOI labels are unambiguous — the latest one
                # found wins (guards against a repeated line).
                hits[field_id] = entry
            elif field_id in _SUMMABLE_EXPENSE_FIELDS:
                # Several distinct broker line items legitimately roll up
                # into one schema bucket (e.g. Electric + Water/Sewer both
                # -> utilities) — sum them, but only WITHIN the same
                # section; switching section resets the bucket rather than
                # blending in-place and pro-forma totals together.
                if section == "pro_forma" and existing.get("section") != "pro_forma":
                    hits[field_id] = entry
                elif section == existing.get("section"):
                    existing["value"] = round(existing["value"] + value, 2)
                    existing["rawText"] = f"{existing['rawText']}; {label_str}"
                    existing["sourceRef"] = source_ref
                # else: existing is pro-forma and this new hit is an
                # in-place duplicate — keep the pro-forma accumulation.
            elif section == "pro_forma" and existing.get("section") != "pro_forma":
                # Singular fields (price/GPR/other income): pro-forma wins
                # over an in-place duplicate, never summed (a "Total Gross
                # Annual Income" restatement already includes the base
                # line, so adding them would double-count).
                hits[field_id] = entry
            # else: keep whichever value was captured first / already
            # pro-forma-tagged.

        if row_matched:
            matched_rows += 1

    confidence = round(min(1.0, matched_rows / 6), 2) if matched_rows else 0.0
    return {"scalars": list(hits.values()), "matchedRows": matched_rows, "confidence": confidence}
