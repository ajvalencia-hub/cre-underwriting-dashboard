"""Read-only HTML deal share (H10).

One self-contained file: inline CSS, no scripts, no external requests —
safe to email or drop in a data room. STRICT RULE (same as the memo):
zero financial math here. Every number is a pass-through from a fresh
engine compute; the annual cash-flow rows are sums of the engine's monthly
statement vectors (presentation aggregation, not new formulas).
"""

import html
from datetime import date

from app.services.memo_service import _OUTPUT_META, format_value

# Curated key-metric ids, shown in this order when present in the outputs.
_KEY_METRIC_IDS = [
    "leveredIrr",
    "unleveredIrr",
    "equityMultiple",
    "cashOnCashYear1",
    "goingInCapRate",
    "yieldOnCost",
    "minDscr",
    "npv",
    "terminalValue",
    "totalProfit",
]

_ASSUMPTION_ROWS = [
    ("dealType", "Deal type", "text"),
    ("propertyType", "Property type", "text"),
    ("market", "Market", "text"),
    ("purchasePrice", "Purchase price", "currency"),
    ("landCost", "Land cost", "currency"),
    ("hardCosts", "Hard costs", "currency"),
    ("grossPotentialRent", "Gross potential rent", "currency"),
    ("vacancyPct", "Vacancy", "percent"),
    ("rentGrowthPct", "Rent growth", "percent"),
    ("expenseGrowthPct", "Expense growth", "percent"),
    ("holdPeriodYears", "Hold period (yrs)", "number"),
    ("exitCapRatePct", "Exit cap rate", "percent"),
    ("ltvOrLtc", "LTV / LTC", "percent"),
    ("interestRate", "Interest rate", "percent"),
]

# Statement series shown as annual rows, in order.
_ANNUAL_ROWS = [
    ("gpr", "Gross potential rent"),
    ("vacancyLoss", "Vacancy loss"),
    ("otherIncome", "Other income + recoveries"),
    ("egi", "Effective gross income"),
    ("opexTotal", "Operating expenses"),
    ("noi", "Net operating income"),
    ("debtService", "Debt service"),
    ("levered", "Levered cash flow"),
]

_CSS = """
body { font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
       color: #1e293b; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.4rem; margin-bottom: 0.2rem; }
h2 { font-size: 0.85rem; letter-spacing: 0.06em; color: #64748b; margin: 1.6rem 0 0.5rem; }
.meta { color: #94a3b8; font-size: 0.8rem; }
.badge { display: inline-block; background: #f1f5f9; color: #475569; border-radius: 4px;
         padding: 2px 8px; font-size: 0.75rem; margin-left: 8px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
           gap: 10px; }
.metric { border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; }
.metric .label { font-size: 0.7rem; color: #94a3b8; letter-spacing: 0.04em; }
.metric .value { font-size: 1.1rem; font-weight: 600; margin-top: 2px; }
table { border-collapse: collapse; width: 100%; font-size: 0.82rem; }
th, td { text-align: right; padding: 4px 8px; border-bottom: 1px solid #f1f5f9; }
th:first-child, td:first-child { text-align: left; }
thead th { color: #94a3b8; font-weight: 500; }
.warn { background: #fffbeb; border: 1px solid #fde68a; color: #92400e;
        border-radius: 6px; padding: 8px 12px; font-size: 0.8rem; margin: 4px 0; }
.disclaimer { margin-top: 2rem; color: #94a3b8; font-size: 0.72rem; }
.error { background: #fef2f2; border: 1px solid #fecaca; color: #991b1b;
         border-radius: 6px; padding: 12px; }
"""

_DISCLAIMER = (
    "Read-only snapshot generated for discussion purposes. Projections are "
    "estimates based on the stated assumptions; actual results will differ. "
    "This document is not an offer to sell or a solicitation of an offer to "
    "buy any security."
)


def _esc(value) -> str:
    return html.escape(str(value))


def _annual_sums(series: list[float], months: int) -> list[float]:
    """Sum operating months (statement index 1..N) into calendar-of-hold
    years. Index 0 (close) is excluded — it's a capital event, not an
    operating period."""
    years = (months + 11) // 12
    sums = [0.0] * years
    for m in range(1, months + 1):
        sums[(m - 1) // 12] += series[m] if m < len(series) else 0.0
    return sums


def _page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def render_share_html(deal_name: str, status: str, inputs: dict, result: dict | None,
                      error: str | None = None) -> str:
    """result = engine.compute(...) output ({outputs, warnings, statement, ...})
    or None with `error` set."""
    head = (
        f"<h1>{_esc(deal_name)}<span class='badge'>{_esc(status)}</span></h1>"
        f"<div class='meta'>Read-only share &middot; generated {date.today().isoformat()} "
        "&middot; CRE Underwriting Dashboard</div>"
    )

    if result is None:
        body = head + f"<div class='error' style='margin-top:1rem'>{_esc(error or 'This deal could not be computed.')}</div>"  # noqa: E501
        return _page(deal_name, body)

    outputs = result.get("outputs", {})
    warnings = result.get("warnings", [])
    statement = result.get("statement") or {}

    metrics = ""
    for metric_id in _KEY_METRIC_IDS:
        if metric_id not in outputs:
            continue
        meta = _OUTPUT_META.get(metric_id, {})
        label = meta.get("label", metric_id)
        value = format_value(outputs[metric_id], meta.get("type", "number"))
        metrics += (
            f"<div class='metric'><div class='label'>{_esc(label)}</div>"
            f"<div class='value'>{_esc(value)}</div></div>"
        )
    metrics_html = f"<h2>KEY METRICS</h2><div class='metrics'>{metrics}</div>" if metrics else ""

    assumption_rows = ""
    for field_id, label, value_type in _ASSUMPTION_ROWS:
        value = inputs.get(field_id)
        if value in (None, "", 0):
            continue
        assumption_rows += (
            f"<tr><td>{_esc(label)}</td><td>{_esc(format_value(value, value_type))}</td></tr>"
        )
    assumptions_html = (
        f"<h2>KEY ASSUMPTIONS</h2><table>{assumption_rows}</table>" if assumption_rows else ""
    )

    annual_html = ""
    month_count = len(statement.get("months") or []) - 1  # index 0 = close
    if month_count > 0:
        years = (month_count + 11) // 12
        header = "<tr><th></th>" + "".join(f"<th>Year {y + 1}</th>" for y in range(years)) + "</tr>"
        rows = ""
        for key, label in _ANNUAL_ROWS:
            series = statement.get(key)
            if not series:
                continue
            sums = _annual_sums(series, month_count)
            if all(abs(v) < 0.005 for v in sums):
                continue
            cells = "".join(f"<td>{_esc(format_value(v, 'currency'))}</td>" for v in sums)
            rows += f"<tr><td>{_esc(label)}</td>{cells}</tr>"
        if rows:
            annual_html = f"<h2>ANNUAL CASH FLOW</h2><table>{header}{rows}</table>"

    warnings_html = ""
    if warnings:
        items = "".join(f"<div class='warn'>{_esc(w)}</div>" for w in warnings)
        warnings_html = f"<h2>MODEL NOTES</h2>{items}"

    body = (
        head
        + metrics_html
        + assumptions_html
        + annual_html
        + warnings_html
        + f"<div class='disclaimer'>{_esc(_DISCLAIMER)}</div>"
    )
    return _page(deal_name, body)
