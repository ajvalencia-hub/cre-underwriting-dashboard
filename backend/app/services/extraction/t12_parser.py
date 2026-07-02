"""Deterministic T-12 / operating-statement parsing: find the period columns
(monthly or a Total/Annual column), pull each line item's annual amount,
normalize the messy chart of accounts to the app's standard income/expense
categories, annualize T-3/T-6 statements, and flag likely one-time items —
without discarding anything (every raw line is preserved).
"""

import re

from app.services.extraction.excel_extractor import parse_numeric

_MONTHS = [
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
]
_TOTAL_COLUMN_NAMES = {"total", "annual", "annualtotal", "ytd", "totalannual", "sum"}

_EXPENSE_ALIASES: dict[str, list[str]] = {
    "realEstateTaxes": ["real estate tax", "property tax", "re tax", "taxes"],
    "insurance": ["insurance"],
    "utilities": ["utilities", "utility", "electric", "gas expense", "water sewer", "water and sewer"],
    "repairsMaintenance": ["repairs and maintenance", "repairs maintenance", "r m", "maintenance", "repairs"],
    "payroll": ["payroll", "salaries", "wages", "personnel"],
    "managementFeePct": ["management fee", "mgmt fee", "management"],
    "generalAdmin": ["general and administrative", "general administrative", "g a", "admin", "office expense"],
    "replacementReserves": ["replacement reserve", "reserves", "capex reserve", "reserve for replacement"],
}
_INCOME_ALIASES: dict[str, list[str]] = {
    "grossPotentialRent": ["gross potential rent", "gpr", "potential rent", "scheduled rent"],
    "vacancyLoss": ["vacancy loss", "vacancy", "vacancy credit loss"],
    "creditLoss": ["credit loss", "bad debt"],
    "otherIncome": ["other income", "misc income", "ancillary income", "miscellaneous income"],
    "effectiveGrossIncome": ["effective gross income", "egi", "total income"],
}
_NOI_LABELS = ["net operating income", "noi"]
_NON_RECURRING_KEYWORDS = [
    "one-time", "one time", "non-recurring", "nonrecurring", "special assessment",
    "extraordinary", "capital expenditure", "capex", "unusual item",
]

EXPENSE_CATEGORIES = set(_EXPENSE_ALIASES.keys())
INCOME_CATEGORIES = set(_INCOME_ALIASES.keys())


def _normalize(text: str) -> str:
    text = re.sub(r"[-_/]", " ", text.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text)).strip()


def _classify_label(norm_label: str) -> tuple[str | None, str]:
    """Returns (canonicalCategory, bucket) where bucket is 'income' | 'expense' | None."""
    for category, aliases in _INCOME_ALIASES.items():
        if any(_normalize(a) in norm_label or norm_label in _normalize(a) for a in aliases):
            return category, "income"
    for category, aliases in _EXPENSE_ALIASES.items():
        if any(_normalize(a) in norm_label or norm_label in _normalize(a) for a in aliases):
            return category, "expense"
    return None, "unknown"


def _find_period_columns(headers: list[str]) -> dict:
    norm_headers = [_normalize(h) for h in headers]
    month_cols = [i for i, h in enumerate(norm_headers) if any(h.startswith(m) for m in _MONTHS)]
    total_cols = [i for i, h in enumerate(norm_headers) if h.replace(" ", "") in _TOTAL_COLUMN_NAMES]
    return {"monthCols": month_cols, "totalCols": total_cols}


def parse_t12(headers: list[str], data_rows: list[list], source_doc: str, sheet: str) -> dict:
    periods = _find_period_columns(headers)
    month_cols = periods["monthCols"]
    total_col = periods["totalCols"][0] if periods["totalCols"] else None

    period_type = "unknown"
    annualize_factor = 1
    if total_col is not None and len(month_cols) >= 10:
        period_type = "T12"
    elif len(month_cols) >= 10:
        period_type = "T12"
    elif len(month_cols) in (5, 6, 7):
        period_type = "T6"
        annualize_factor = 2
    elif len(month_cols) in (2, 3, 4):
        period_type = "T3"
        annualize_factor = 4
    elif total_col is not None:
        period_type = "annual"

    annualized = annualize_factor != 1
    line_items = []

    label_col = 0  # first column is conventionally the line-item label

    for row_idx, row in enumerate(data_rows):
        label = row[label_col] if label_col < len(row) else None
        if label is None or str(label).strip() == "":
            continue
        label_str = str(label).strip()
        norm_label = _normalize(label_str)

        if total_col is not None and total_col < len(row):
            amount = parse_numeric(row[total_col])
        elif month_cols:
            monthly_values = [parse_numeric(row[c]) for c in month_cols if c < len(row)]
            monthly_values = [v for v in monthly_values if v is not None]
            amount = sum(monthly_values) * annualize_factor if monthly_values else None
        else:
            amount = None

        if amount is None:
            continue

        category, bucket = _classify_label(norm_label)
        is_noi_line = any(n in norm_label for n in _NOI_LABELS)
        is_non_recurring = any(kw in norm_label for kw in _NON_RECURRING_KEYWORDS)

        line_items.append(
            {
                "label": label_str,
                "amount": round(amount, 2),
                "category": category,
                "bucket": "noi" if is_noi_line else bucket,
                "isNonRecurring": is_non_recurring,
                "sourceRef": {"doc": source_doc, "sheet": sheet, "row": row_idx, "page": None, "cell": None},
            }
        )

    return {
        "periodType": period_type,
        "annualized": annualized,
        "annualizeFactor": annualize_factor,
        "lineItems": line_items,
        "confidence": round(min(1.0, (len(month_cols) + (1 if total_col is not None else 0)) / 12), 2),
    }


# Rows that are derivable subtotals, not data — kept in lineItems but excluded
# from the "unclassified" list so they don't get flagged as lost information.
_SUBTOTAL_RE = re.compile(r"^(sub ?)?total\b|^net ")


def aggregate_categories(line_items: list[dict]) -> dict:
    income: dict[str, float] = {}
    expenses: dict[str, float] = {}
    other_expense_total = 0.0
    non_recurring = []
    unclassified = []
    noi = None

    for item in line_items:
        if item["bucket"] == "noi":
            noi = item["amount"]
            continue
        if item["isNonRecurring"]:
            non_recurring.append({"label": item["label"], "amount": item["amount"]})
            continue
        if item["bucket"] == "income" and item["category"]:
            income[item["category"]] = income.get(item["category"], 0) + item["amount"]
        elif item["bucket"] == "expense" and item["category"]:
            expenses[item["category"]] = expenses.get(item["category"], 0) + item["amount"]
        elif item["bucket"] == "expense":
            other_expense_total += item["amount"]
        elif not _SUBTOTAL_RE.match(_normalize(item["label"])):
            # A real line that matched no category. It must NOT vanish: callers
            # surface these on the review screen (unmatched list + warning) so
            # the user knows these amounts are excluded from every field.
            unclassified.append(item)

    if other_expense_total:
        expenses["other"] = round(other_expense_total, 2)

    total_expenses = round(sum(expenses.values()), 2) if expenses else None

    return {
        "income": income,
        "expenses": expenses,
        "totalExpenses": total_expenses,
        "noi": noi,
        "nonRecurringFlags": non_recurring,
        "unclassified": unclassified,
    }
