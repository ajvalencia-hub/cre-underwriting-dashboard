"""Chart renderers for the IC memo — matplotlib (Agg), PNG bytes in memory.

Every renderer returns bytes or None; None means "data absent or not
chartable" and the memo silently skips the figure. No financial math here:
each chart plots numbers the engine already produced.
"""

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

from app.config import MEMO_BRAND_COLOR

_BRAND = f"#{MEMO_BRAND_COLOR}"
_DPI = 150


def _to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def sensitivity_heatmap(sensitivity: dict | None) -> bytes | None:
    """Heatmap from a SAVED sensitivity run's raw points (2-driver runs only;
    the formatted header/rows strings label the axes)."""
    if not sensitivity:
        return None
    run = sensitivity.get("run") or {}
    drivers = run.get("drivers") or []
    points = run.get("points") or []
    metric_ids = run.get("outputFieldIds") or []
    if len(drivers) != 2 or not points or not metric_ids:
        return None
    metric = metric_ids[0]
    rows_values = drivers[0].get("values") or []
    cols_values = drivers[1].get("values") or []
    if not rows_values or not cols_values:
        return None

    lookup = {}
    for point in points:
        dv = point.get("driverValues") or {}
        key = (dv.get(drivers[0]["fieldId"]), dv.get(drivers[1]["fieldId"]))
        value = (point.get("outputs") or {}).get(metric)
        lookup[key] = value if isinstance(value, (int, float)) else None

    grid = [[lookup.get((r, c)) for c in cols_values] for r in rows_values]
    if all(v is None for row in grid for v in row):
        return None
    numeric = [[v if v is not None else float("nan") for v in row] for row in grid]

    header = sensitivity.get("header") or []
    row_labels = [r[0] for r in (sensitivity.get("rows") or [])]
    col_labels = header[1:] if len(header) > 1 else [str(c) for c in cols_values]

    fig, ax = plt.subplots(figsize=(6, 3.2))
    image = ax.imshow(numeric, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(cols_values)))
    ax.set_xticklabels(col_labels[: len(cols_values)], fontsize=7, rotation=30, ha="right")
    ax.set_yticks(range(len(rows_values)))
    ax.set_yticklabels(row_labels[: len(rows_values)], fontsize=7)
    ax.set_title(str(sensitivity.get("description") or "Sensitivity"), fontsize=9)
    fig.colorbar(image, ax=ax, shrink=0.8).ax.tick_params(labelsize=7)
    return _to_png(fig)


def annual_cashflow_bars(statement: dict | None) -> bytes | None:
    """Levered cash flow by fiscal year (plus the close period)."""
    if not statement or not statement.get("levered"):
        return None
    levered = statement["levered"]
    total = len(levered) - 1
    if total < 1:
        return None
    labels = ["Close"]
    values = [levered[0]]
    for start in range(1, total + 1, 12):
        year = (start - 1) // 12 + 1
        labels.append(f"Y{year}")
        values.append(sum(levered[start : min(start + 12, total + 1)]))

    fig, ax = plt.subplots(figsize=(6, 2.6))
    colors = [_BRAND if v >= 0 else "#b91c1c" for v in values]
    ax.bar(labels, values, color=colors)
    ax.axhline(0, color="#94a3b8", linewidth=0.8)
    ax.set_title("Levered cash flow by year", fontsize=9)
    ax.tick_params(labelsize=7)
    ax.yaxis.set_major_formatter(lambda v, _: f"${v / 1000:,.0f}k")
    return _to_png(fig)


def sources_uses_bars(sources_and_uses: dict | None) -> bytes | None:
    if not sources_and_uses:
        return None
    uses = [(label, amount) for label, amount in sources_and_uses.get("uses", []) if amount]
    sources = [(label, amount) for label, amount in sources_and_uses.get("sources", []) if amount]
    if not uses or not sources:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.6))
    for ax, (title, entries) in zip(axes, (("Uses", uses), ("Sources", sources))):
        labels = [e[0] for e in entries]
        amounts = [e[1] for e in entries]
        ax.barh(labels, amounts, color=_BRAND)
        ax.set_title(title, fontsize=9)
        ax.tick_params(labelsize=6.5)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(lambda v, _: f"${v / 1e6:,.1f}M")
    fig.tight_layout()
    return _to_png(fig)


def hold_sweep_line(sweep: dict | None) -> bytes | None:
    rows = (sweep or {}).get("rows") or []
    rows = [r for r in rows if r.get("leveredIrr") is not None]
    if len(rows) < 2:
        return None
    years = [r["holdYear"] for r in rows]
    levered = [r["leveredIrr"] for r in rows]
    multiples = [r.get("equityMultiple") for r in rows]

    fig, ax = plt.subplots(figsize=(6, 2.6))
    ax.plot(years, levered, marker="o", color=_BRAND, label="Levered IRR")
    ax.set_xlabel("Exit year", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    modeled = (sweep or {}).get("modeledHoldYears")
    if modeled in years:
        ax.axvline(modeled, color="#f59e0b", linestyle="--", linewidth=1, label="Modeled hold")
    if any(m is not None for m in multiples):
        ax2 = ax.twinx()
        ax2.plot(years, multiples, marker="s", markersize=3, color="#059669", linestyle="--", label="Equity multiple")
        ax2.tick_params(labelsize=7)
        ax2.yaxis.set_major_formatter(lambda v, _: f"{v:.2f}x")
    ax.set_title("Returns by exit year", fontsize=9)
    ax.legend(fontsize=7, loc="lower right")
    return _to_png(fig)
