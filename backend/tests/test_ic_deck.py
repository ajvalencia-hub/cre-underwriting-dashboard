"""J14: full 8-slide IC deck. Full-data deals produce all slides; sparse
deals produce a reduced deck with a reported skip list. Slide shapes are
checked structurally (title text present), never by pixel."""

import json
from io import BytesIO
from pathlib import Path

from pptx import Presentation

from app.services import deck_service
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"
REGRESSION = FIXTURES.parent / "regression" / "fixtures"


def _titles(pptx_bytes: bytes) -> list[str]:
    prs = Presentation(BytesIO(pptx_bytes))
    titles = []
    for slide in prs.slides:
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if shape.has_text_frame and shape.text_frame.text.strip()
        ]
        titles.append(texts[0] if texts else "")
    return titles


def test_full_data_deck_has_all_eight_slides():
    inputs = json.loads((REGRESSION / "value_add_multifamily.json").read_text())
    inputs["investmentThesis"] = "Mispriced value-add; rents 12% below market."
    result = engine.compute(inputs)

    # Saved sensitivity (2-driver) + Monte Carlo so those slides render.
    sensitivity = {
        "description": "Levered IRR sensitivity",
        "header": ["", "5.0%", "5.5%"],
        "rows": [["$17.0M"], ["$18.0M"]],
        "run": {
            "drivers": [
                {"fieldId": "purchasePrice", "values": [17_000_000, 18_000_000]},
                {"fieldId": "exitCapRatePct", "values": [0.05, 0.055]},
            ],
            "outputFieldIds": ["leveredIrr"],
            "points": [
                {"driverValues": {"purchasePrice": 17_000_000, "exitCapRatePct": 0.05}, "outputs": {"leveredIrr": 0.18}},
                {"driverValues": {"purchasePrice": 17_000_000, "exitCapRatePct": 0.055}, "outputs": {"leveredIrr": 0.16}},
                {"driverValues": {"purchasePrice": 18_000_000, "exitCapRatePct": 0.05}, "outputs": {"leveredIrr": 0.14}},
                {"driverValues": {"purchasePrice": 18_000_000, "exitCapRatePct": 0.055}, "outputs": {"leveredIrr": 0.12}},
            ],
        },
    }
    monte_carlo = {
        "successfulRuns": 500, "seed": 42,
        "leveredIrr": {"p5": 0.05, "p50": 0.13, "p95": 0.22, "mean": 0.13,
                       "p25": 0.10, "p75": 0.16, "min": 0.0, "max": 0.3},
        "probIrrNegative": 0.02, "probIrrBelowHurdle": 0.15, "hurdleIrr": 0.08,
        "drivers": [{"inputPath": "exitCapRatePct"}],
    }
    benchmarks = {"flags": [
        {"verdict": "warning", "explanation": "Exit cap 30bps below market."},
        {"verdict": "caution", "explanation": "Rent growth above submarket trend."},
    ]}
    demographics = {"acs": {"population": 250_000, "medianHouseholdIncome": 68_000,
                            "medianGrossRent": 1_700, "renterOccupiedPct": 0.55}}
    tornado = {"metric": "leveredIrr", "base": 0.13, "bars": [
        {"key": "rent", "label": "Rent", "low": 0.10, "high": 0.16, "impact": 0.03},
        {"key": "exitCap", "label": "Exit cap", "low": 0.09, "high": 0.17, "impact": 0.04},
    ]}

    content, skipped = deck_service.build_ic_deck(
        "Maple Gardens", inputs, result,
        sensitivity=sensitivity, monte_carlo=monte_carlo,
        benchmarks=benchmarks, demographics=demographics, tornado=tornado,
    )
    titles = _titles(content)
    assert len(titles) == 8, titles
    assert skipped == []
    assert titles[0] == "Maple Gardens"
    assert "Deal Summary" in titles[1]
    assert "Market Context" in titles[2]
    assert "Returns" in titles[3]
    assert "Sensitivity" in titles[4]
    assert "Debt" in titles[5]
    assert "Waterfall" in titles[6]
    assert "Risk" in titles[7]


def test_sparse_deal_produces_reduced_deck_with_skip_list():
    """All-equity deal (no debt, no waterfall promote), no saved runs, no
    market data -> market/sensitivity/debt slides skip; the risk slide still
    renders from the tornado fallback."""
    inputs = {
        "dealName": "Tiny All-Equity", "dealType": "acquisition",
        "propertyType": "multifamily", "purchasePrice": 1_000_000,
        "grossPotentialRent": 100_000, "vacancyPct": 0.05,
        "realEstateTaxes": 10_000, "holdPeriodYears": 5,
        "exitCapRatePct": 0.06, "ltvOrLtc": 0, "loanAmount": 0,
    }
    result = engine.compute(inputs)
    tornado = {"metric": "leveredIrr", "base": 0.1, "bars": [
        {"key": "rent", "label": "Rent", "low": 0.08, "high": 0.12, "impact": 0.02},
    ]}
    content, skipped = deck_service.build_ic_deck(
        "Tiny All-Equity", inputs, result, tornado=tornado,
    )
    titles = _titles(content)
    assert "market" in skipped
    assert "sensitivity" in skipped
    assert "debt" in skipped  # all-equity -> no debt block
    # Title, summary, returns, risk always present.
    assert titles[0] == "Tiny All-Equity"
    assert any("Risk" in t for t in titles)
    assert len(titles) == 8 - len(skipped)


def test_risk_slide_prefers_monte_carlo_over_tornado():
    inputs = {
        "dealName": "MC Deal", "dealType": "acquisition",
        "propertyType": "multifamily", "purchasePrice": 1_000_000,
        "grossPotentialRent": 100_000, "vacancyPct": 0.05,
        "realEstateTaxes": 10_000, "holdPeriodYears": 5, "exitCapRatePct": 0.06,
        "ltvOrLtc": 0.6, "loanAmount": 600_000, "interestRate": 0.06, "ioMonths": 60,
    }
    result = engine.compute(inputs)
    monte_carlo = {
        "successfulRuns": 100, "seed": 7,
        "leveredIrr": {"p5": 0.04, "p50": 0.11, "p95": 0.19, "mean": 0.11,
                       "p25": 0.08, "p75": 0.14, "min": 0, "max": 0.25},
        "probIrrNegative": 0.03, "probIrrBelowHurdle": 0.2, "hurdleIrr": 0.08,
        "drivers": [],
    }
    content, _ = deck_service.build_ic_deck(
        "MC Deal", inputs, result, monte_carlo=monte_carlo,
    )
    prs = Presentation(BytesIO(content))
    all_text = "\n".join(
        shape.text_frame.text
        for slide in prs.slides for shape in slide.shapes
        if shape.has_text_frame
    )
    assert "Monte Carlo trials" in all_text
    assert "seed 7" in all_text
