"""One-page deck export (H12) via python-pptx.

Same STRICT RULE as the memo and the HTML share: zero financial math here.
Every number is a formatted pass-through from a fresh engine compute; the
charts are the memo's own matplotlib PNGs (annual levered cash flow,
sources & uses) fed the engine's vectors.
"""

from datetime import date
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from app.config import FIRM_NAME, MEMO_BRAND_COLOR
from app.services import memo_charts
from app.services.memo_service import _OUTPUT_META, format_value

# Metric tiles across the top, in order (shown when present).
_TILE_IDS = [
    "leveredIrr",
    "equityMultiple",
    "cashOnCashYear1",
    "goingInCapRate",
    "minDscr",
    "npv",
]

_ASSUMPTION_ROWS = [
    ("dealType", "Deal type", "text"),
    ("purchasePrice", "Purchase price", "currency"),
    ("landCost", "Land cost", "currency"),
    ("hardCosts", "Hard costs", "currency"),
    ("grossPotentialRent", "Gross potential rent", "currency"),
    ("vacancyPct", "Vacancy", "percent"),
    ("rentGrowthPct", "Rent growth", "percent"),
    ("holdPeriodYears", "Hold (yrs)", "number"),
    ("exitCapRatePct", "Exit cap", "percent"),
    ("ltvOrLtc", "LTV / LTC", "percent"),
    ("interestRate", "Interest rate", "percent"),
]

_SLIDE_W = Inches(13.333)  # 16:9
_SLIDE_H = Inches(7.5)
_MARGIN = Inches(0.45)

_DISCLAIMER = (
    "Prepared for internal discussion only. Projections are estimates based on "
    "the stated assumptions; actual results will differ. Not an offer to sell "
    "or a solicitation of an offer to buy any security."
)


def _brand() -> RGBColor:
    return RGBColor.from_string(MEMO_BRAND_COLOR)


def _text(slide, left, top, width, height, text, size, *, bold=False,
          color=None, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = text
    font = run.font
    font.size = Pt(size)
    font.bold = bold
    if color is not None:
        font.color.rgb = color
    return box


def _new_presentation() -> Presentation:
    prs = Presentation()
    prs.slide_width = _SLIDE_W
    prs.slide_height = _SLIDE_H
    return prs


def build_deck(deal_name: str, inputs: dict, result: dict) -> bytes:
    """One 16:9 slide: title bar, metric tiles, assumptions column, and the
    memo's cash-flow + sources & uses charts."""
    prs = _new_presentation()
    _render_deal_slide(prs, deal_name, inputs, result)
    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


BATCH_DECK_CAP = 20


def build_batch_deck(entries: list[dict], skipped: list[str]) -> bytes:
    """I13: a screening deck — one branded title slide (count, date, skip
    list) plus one H12-style slide per computable deal, in the caller's
    order (the client sends ids in the pipeline's current sort)."""
    prs = _new_presentation()

    title = prs.slides.add_slide(prs.slide_layouts[6])
    _text(title, _MARGIN, Inches(2.4), _SLIDE_W - 2 * _MARGIN, Inches(0.8),
          f"{FIRM_NAME} — Screening Deck", 34, bold=True, color=_brand(),
          align=PP_ALIGN.CENTER)
    _text(title, _MARGIN, Inches(3.3), _SLIDE_W - 2 * _MARGIN, Inches(0.4),
          f"{len(entries)} deal(s) · {date.today().isoformat()}",
          14, color=RGBColor.from_string("64748B"), align=PP_ALIGN.CENTER)
    if skipped:
        _text(title, _MARGIN, Inches(3.9), _SLIDE_W - 2 * _MARGIN, Inches(0.6),
              "Skipped (no computable outputs): " + ", ".join(skipped),
              10, color=RGBColor.from_string("B45309"), align=PP_ALIGN.CENTER)
    _text(title, _MARGIN, _SLIDE_H - Inches(0.5), _SLIDE_W - 2 * _MARGIN,
          Inches(0.35), _DISCLAIMER, 7, color=RGBColor.from_string("94A3B8"),
          align=PP_ALIGN.CENTER)

    for entry in entries:
        _render_deal_slide(prs, entry["name"], entry["inputs"], entry["result"])

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    return slide


def _slide_title(slide, title: str) -> None:
    _text(slide, _MARGIN, Inches(0.3), _SLIDE_W - 2 * _MARGIN, Inches(0.6),
          title, 24, bold=True, color=_brand())


def _footer(slide) -> None:
    _text(slide, _MARGIN, _SLIDE_H - Inches(0.45), _SLIDE_W - 2 * _MARGIN,
          Inches(0.35), _DISCLAIMER, 7, color=RGBColor.from_string("94A3B8"))


# J14: the ordered slide keys of the full IC deck (title is implicit slide 1).
IC_DECK_SLIDES = [
    "title", "summary", "market", "returns", "sensitivity", "debt",
    "waterfall", "risk",
]


def build_ic_deck(
    deal_name: str,
    inputs: dict,
    result: dict,
    *,
    sensitivity: dict | None = None,
    monte_carlo: dict | None = None,
    benchmarks: dict | None = None,
    demographics: dict | None = None,
    tornado: dict | None = None,
) -> tuple[bytes, list[str]]:
    """J14: the full 8-slide IC deck. Returns (pptx bytes, skipped slide
    keys). Every slide is a pure pass-through of engine/analysis output;
    slides whose data is absent are skipped and reported, never faked."""
    prs = _new_presentation()
    outputs = result.get("outputs", {})
    skipped: list[str] = []

    # 1 — Title
    title = _blank(prs)
    _text(title, _MARGIN, Inches(2.5), _SLIDE_W - 2 * _MARGIN, Inches(1.0),
          deal_name, 40, bold=True, color=_brand(), align=PP_ALIGN.CENTER)
    subtitle = " · ".join(
        str(v) for v in (inputs.get("address"), inputs.get("market")) if v
    )
    _text(title, _MARGIN, Inches(3.6), _SLIDE_W - 2 * _MARGIN, Inches(0.5),
          f"{FIRM_NAME} · Investment Committee · {date.today().isoformat()}",
          14, color=RGBColor.from_string("64748B"), align=PP_ALIGN.CENTER)
    if subtitle:
        _text(title, _MARGIN, Inches(4.1), _SLIDE_W - 2 * _MARGIN, Inches(0.4),
              subtitle, 12, color=RGBColor.from_string("94A3B8"), align=PP_ALIGN.CENTER)
    _footer(title)

    # 2 — Deal summary + thesis
    summary = _blank(prs)
    _slide_title(summary, "Deal Summary")
    thesis = str(inputs.get("investmentThesis") or "").strip()
    if thesis:
        _text(summary, _MARGIN, Inches(1.1), _SLIDE_W - 2 * _MARGIN, Inches(1.4),
              thesis, 14, color=RGBColor.from_string("334155"))
    else:
        _text(summary, _MARGIN, Inches(1.1), _SLIDE_W - 2 * _MARGIN, Inches(0.5),
              "(No investment thesis entered.)", 12,
              color=RGBColor.from_string("94A3B8"))
    row_top = Inches(2.7)
    for field_id, label, value_type in _ASSUMPTION_ROWS:
        value = inputs.get(field_id)
        if value in (None, "", 0):
            continue
        _text(summary, _MARGIN, row_top, Inches(2.4), Inches(0.24), label, 11,
              color=RGBColor.from_string("64748B"))
        _text(summary, _MARGIN + Inches(2.4), row_top, Inches(1.8), Inches(0.24),
              format_value(value, value_type), 11, align=PP_ALIGN.RIGHT)
        row_top += Inches(0.3)
        if row_top > Inches(6.6):
            break
    _footer(summary)

    # 3 — Market context (flags + demographics)
    flags = [f for f in ((benchmarks or {}).get("flags") or []) if f.get("verdict") != "ok"]
    demo_png = memo_charts.demographics_bars(demographics)
    if flags or demo_png:
        market = _blank(prs)
        _slide_title(market, "Market Context")
        row_top = Inches(1.15)
        for flag in flags[:8]:
            color = RGBColor.from_string("B45309" if flag.get("verdict") == "warning" else "64748B")
            _text(market, _MARGIN, row_top, Inches(6.4), Inches(0.4),
                  f"• {flag.get('explanation', '')}", 10, color=color)
            row_top += Inches(0.42)
        if demo_png:
            market.shapes.add_picture(BytesIO(demo_png), Inches(7.2), Inches(1.15),
                                      width=Inches(5.5))
        _footer(market)
    else:
        skipped.append("market")

    # 4 — Returns / metrics grid
    returns = _blank(prs)
    _slide_title(returns, "Returns & Metrics")
    grid_ids = [t for t in (_TILE_IDS + ["cashOnCashStabilized", "developmentSpreadBps",
                                         "yieldOnCost", "debtYield"]) if t in outputs]
    seen: set[str] = set()
    grid_ids = [t for t in grid_ids if not (t in seen or seen.add(t))]
    cols = 3
    tile_w = Emu(int((_SLIDE_W - 2 * _MARGIN) / cols))
    tile_h = Inches(1.0)
    for i, tid in enumerate(grid_ids[:9]):
        meta = _OUTPUT_META.get(tid, {})
        left = _MARGIN + (i % cols) * tile_w
        top = Inches(1.3) + (i // cols) * tile_h
        _text(returns, left, top, tile_w, Inches(0.25),
              str(meta.get("label", tid)).upper(), 9,
              color=RGBColor.from_string("94A3B8"))
        _text(returns, left, top + Inches(0.24), tile_w, Inches(0.5),
              format_value(outputs[tid], meta.get("type", "number")), 22, bold=True)
    cashflow_png = memo_charts.annual_cashflow_bars(result.get("statement"))
    if cashflow_png:
        returns.shapes.add_picture(BytesIO(cashflow_png), _MARGIN, Inches(4.6),
                                   width=Inches(7.5))
    _footer(returns)

    # 5 — Sensitivity heatmap
    heatmap_png = memo_charts.sensitivity_heatmap(sensitivity)
    if heatmap_png:
        sens = _blank(prs)
        _slide_title(sens, "Sensitivity")
        sens.shapes.add_picture(BytesIO(heatmap_png), _MARGIN, Inches(1.3),
                                width=Inches(9.0))
        _footer(sens)
    else:
        skipped.append("sensitivity")

    # 6 — Debt summary (combined leverage + strike-DSCR)
    debt_block = result.get("debt")
    if debt_block:
        debt = _blank(prs)
        _slide_title(debt, "Debt & Capital Structure")
        rows: list[tuple[str, str]] = []
        for tid, label in (
            ("ltv", "Senior LTV"), ("ltc", "Senior LTC"),
            ("combinedLtv", "Combined LTV (incl. junior)"),
            ("combinedLtc", "Combined LTC (incl. junior)"),
            ("minDscr", "Min DSCR"), ("debtYield", "Debt yield"),
            ("loanConstant", "Loan constant"),
            ("stressedDscr", "Stressed DSCR (+200bps, NOI −10%)"),
            ("dscrAtCapStrike", "DSCR at cap strike"),
        ):
            if tid in outputs:
                rows.append((label, format_value(outputs[tid], _OUTPUT_META.get(tid, {}).get("type", "number"))))
        rows.insert(0, ("Governing constraint", str(debt_block.get("governingConstraint", "—"))))
        rows.insert(1, ("Sized loan", format_value(debt_block.get("loanAmount", 0), "currency")))
        row_top = Inches(1.3)
        for label, value in rows:
            _text(debt, _MARGIN, row_top, Inches(4.0), Inches(0.26), label, 11,
                  color=RGBColor.from_string("64748B"))
            _text(debt, _MARGIN + Inches(4.0), row_top, Inches(2.0), Inches(0.26),
                  value, 11, bold=True, align=PP_ALIGN.RIGHT)
            row_top += Inches(0.34)
        rate = debt_block.get("rate")
        if rate:
            _text(debt, _MARGIN, row_top + Inches(0.1), Inches(8.0), Inches(0.4),
                  f"Floating: {rate.get('index', 'index')} + "
                  f"{round(rate.get('spreadBps', 0))}bps"
                  + (f", cap strike {rate['cap']['strikePct'] * 100:.2f}%"
                     if rate.get("cap") else ""),
                  10, color=RGBColor.from_string("334155"))
        _footer(debt)
    else:
        skipped.append("debt")

    # 7 — Waterfall + GP/LP split
    gp_economics = result.get("gpEconomics")
    has_split = "lpIrr" in outputs or "gpIrr" in outputs
    if has_split or gp_economics:
        wf = _blank(prs)
        _slide_title(wf, "Waterfall & Promote")
        rows = []
        for tid, label in (
            ("lpIrr", "LP IRR"), ("gpIrr", "GP IRR"),
            ("lpEquityMultiple", "LP equity multiple"),
        ):
            if tid in outputs:
                rows.append((label, format_value(outputs[tid], _OUTPUT_META.get(tid, {}).get("type", "number"))))
        if gp_economics:
            for key, label, vtype in (
                ("acquisitionFee", "GP acquisition fee", "currency"),
                ("developerFee", "GP developer fee", "currency"),
                ("assetMgmtFees", "GP asset-mgmt fees", "currency"),
                ("promote", "GP promote", "currency"),
                ("totalCompensation", "GP total compensation", "currency"),
            ):
                if gp_economics.get(key):
                    rows.append((label, format_value(gp_economics[key], vtype)))
        row_top = Inches(1.3)
        for label, value in rows:
            _text(wf, _MARGIN, row_top, Inches(4.0), Inches(0.26), label, 11,
                  color=RGBColor.from_string("64748B"))
            _text(wf, _MARGIN + Inches(4.0), row_top, Inches(2.0), Inches(0.26),
                  value, 11, bold=True, align=PP_ALIGN.RIGHT)
            row_top += Inches(0.34)
        _footer(wf)
    else:
        skipped.append("waterfall")

    # 8 — Risk (Monte Carlo if saved, else tornado top-5)
    risk = _blank(prs)
    _slide_title(risk, "Risk")
    if monte_carlo and monte_carlo.get("leveredIrr"):
        irr = monte_carlo["leveredIrr"]
        _text(risk, _MARGIN, Inches(1.2), _SLIDE_W - 2 * _MARGIN, Inches(0.4),
              f"{monte_carlo.get('successfulRuns', 0):,} Monte Carlo trials "
              f"(seed {monte_carlo.get('seed')})", 12,
              color=RGBColor.from_string("334155"))
        stats = [
            ("Levered IRR P5", format_value(irr.get("p5"), "percent")),
            ("Levered IRR P50", format_value(irr.get("p50"), "percent")),
            ("Levered IRR P95", format_value(irr.get("p95"), "percent")),
            ("P(IRR < 0)", format_value(monte_carlo.get("probIrrNegative"), "percent")),
            ("P(IRR < hurdle)", format_value(monte_carlo.get("probIrrBelowHurdle"), "percent")),
        ]
        row_top = Inches(1.8)
        for label, value in stats:
            _text(risk, _MARGIN, row_top, Inches(4.0), Inches(0.26), label, 11,
                  color=RGBColor.from_string("64748B"))
            _text(risk, _MARGIN + Inches(4.0), row_top, Inches(2.0), Inches(0.26),
                  value, 11, bold=True, align=PP_ALIGN.RIGHT)
            row_top += Inches(0.34)
    else:
        tornado_png = memo_charts.tornado_bars(tornado)
        if tornado_png:
            risk.shapes.add_picture(BytesIO(tornado_png), _MARGIN, Inches(1.3),
                                    width=Inches(9.0))
        else:
            _text(risk, _MARGIN, Inches(1.3), _SLIDE_W - 2 * _MARGIN, Inches(0.5),
                  "No saved Monte Carlo run and no tornado drivers moved the "
                  "metric — run the Risk or Sensitivity tools for this slide.",
                  11, color=RGBColor.from_string("94A3B8"))
    _footer(risk)

    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue(), skipped


def _render_deal_slide(prs: Presentation, deal_name: str, inputs: dict, result: dict) -> None:
    outputs = result.get("outputs", {})
    statement = result.get("statement")
    sources_and_uses = result.get("sourcesAndUses")

    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Title bar
    _text(slide, _MARGIN, Inches(0.25), _SLIDE_W - 2 * _MARGIN, Inches(0.5),
          deal_name, 26, bold=True, color=_brand())
    _text(slide, _MARGIN, Inches(0.72), _SLIDE_W - 2 * _MARGIN, Inches(0.3),
          f"{FIRM_NAME} · Investment summary · {date.today().isoformat()}",
          10, color=RGBColor.from_string("64748B"))

    # Metric tiles
    tiles = [(tid, _OUTPUT_META.get(tid, {})) for tid in _TILE_IDS if tid in outputs]
    if tiles:
        tile_w = Emu(int((_SLIDE_W - 2 * _MARGIN) / max(4, len(tiles))))
        top = Inches(1.15)
        for i, (tid, meta) in enumerate(tiles):
            left = _MARGIN + i * tile_w
            _text(slide, left, top, tile_w, Inches(0.25),
                  str(meta.get("label", tid)).upper(), 9,
                  color=RGBColor.from_string("94A3B8"))
            _text(slide, left, top + Inches(0.24), tile_w, Inches(0.4),
                  format_value(outputs[tid], meta.get("type", "number")),
                  20, bold=True)

    # Assumptions column (left)
    assumptions_top = Inches(2.15)
    _text(slide, _MARGIN, assumptions_top, Inches(3.6), Inches(0.25),
          "KEY ASSUMPTIONS", 10, bold=True, color=_brand())
    row_top = assumptions_top + Inches(0.35)
    for field_id, label, value_type in _ASSUMPTION_ROWS:
        value = inputs.get(field_id)
        if value in (None, "", 0):
            continue
        _text(slide, _MARGIN, row_top, Inches(2.0), Inches(0.22), label, 10,
              color=RGBColor.from_string("64748B"))
        _text(slide, _MARGIN + Inches(2.0), row_top, Inches(1.6), Inches(0.22),
              format_value(value, value_type), 10, align=PP_ALIGN.RIGHT)
        row_top += Inches(0.28)
        if row_top > Inches(6.5):
            break

    # Charts (right two-thirds)
    chart_left = Inches(4.5)
    chart_w = _SLIDE_W - chart_left - _MARGIN
    cashflow_png = memo_charts.annual_cashflow_bars(statement)
    if cashflow_png:
        slide.shapes.add_picture(BytesIO(cashflow_png), chart_left, Inches(2.15),
                                 width=chart_w)
    sources_png = memo_charts.sources_uses_bars(sources_and_uses)
    if sources_png:
        slide.shapes.add_picture(BytesIO(sources_png), chart_left, Inches(4.55),
                                 width=chart_w)

    # Footer
    _text(slide, _MARGIN, _SLIDE_H - Inches(0.45), _SLIDE_W - 2 * _MARGIN,
          Inches(0.35), _DISCLAIMER, 7, color=RGBColor.from_string("94A3B8"))
