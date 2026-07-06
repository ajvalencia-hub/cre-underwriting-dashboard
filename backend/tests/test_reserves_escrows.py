"""J6: per-unit/PSF replacement reserves (convention toggle) + tax &
insurance escrows.

Hand fixture: 10 units x $1,000/mo = 120,000 GPR, 0% vacancy/credit loss,
taxes 12,000 + insurance 6,000 (flat growth), no mgmt fee -> NOI
102,000/yr = 8,500/mo. Exit cap 10.2% -> terminal 1,000,000 (par).
Debt: explicit 600,000 IO at 6% -> service 3,000/mo.
Reserves: $300/unit/yr x 10 = 3,000/yr = 250/mo.

The convention changes ONLY where the 250/mo sits:
  below_noi:  NOI 8,500, DSCR 2.8333, UW DSCR (8,500-250)/3,000 = 2.75,
              exit on NOI (terminal 1,000,000)
  above_noi:  NOI 8,250, DSCR 2.75, exit on NOI-reserves (terminal 970,588)
Either way levered month 1 = 5,250 — the same dollars.
"""

import pytest

from app.services.proforma import engine, operations
from app.services.proforma.timeline import build_timeline


def deal(**overrides) -> dict:
    base = {
        "dealName": "Reserves Test",
        "dealType": "acquisition",
        "propertyType": "multifamily",
        "purchasePrice": 1_000_000,
        "closingCostsPct": 0,
        "unitMix": [
            {"unitType": "1BR", "unitCount": 10, "inPlaceRent": 1000, "marketRent": 1000}
        ],
        "vacancyPct": 0,
        "creditLossPct": 0,
        "otherIncome": 0,
        "realEstateTaxes": 12_000,
        "insurance": 6_000,
        "managementFeePct": 0,
        "rentGrowthMode": "flat",
        "expenseGrowthMode": "flat",
        "holdPeriodYears": 5,
        "exitCapRatePct": 0.102,
        "costOfSalePct": 0,
        "loanAmount": 600_000,
        "ltvOrLtc": 0.6,
        "interestRate": 0.06,
        "amortYears": 30,
        "ioMonths": 60,
        "originationFeePct": 0,
        "lpSplitPct": 0.9,
        "gpSplitPct": 0.1,
        "waterfallTiers": [],
    }
    base.update(overrides)
    return base


def test_below_noi_default_convention():
    result = engine.compute(deal(replacementReservesPerUnit=300))
    stmt = result["statement"]
    # NOI untouched; reserves are a capital row on BOTH vectors.
    assert stmt["noi"][1] == pytest.approx(8_500)
    assert stmt["replacementReserves"][1] == pytest.approx(250)
    assert stmt["unlevered"][1] == pytest.approx(8_500 - 250)
    assert stmt["levered"][1] == pytest.approx(8_500 - 3_000 - 250)
    # DSCR on NOI; the lender-UW view is the extra detail output.
    assert result["outputs"]["minDscr"] == pytest.approx(8_500 / 3_000)
    assert result["outputs"]["underwrittenDscr"] == pytest.approx(8_250 / 3_000)
    # Exit caps NOI, not NOI - reserves: gross 102,000 / 10.2% = 1,000,000.
    assert stmt["saleProceedsGross"][60] == pytest.approx(1_000_000)


def test_above_noi_underwritten_convention():
    result = engine.compute(
        deal(replacementReservesPerUnit=300, reservesConvention="above_noi_underwritten")
    )
    stmt = result["statement"]
    # Inside opex for ALL NOI-derived metrics.
    assert stmt["noi"][1] == pytest.approx(8_250)
    assert stmt["opexTotal"][1] == pytest.approx(1_750)
    assert stmt["fixedOpexByCategory"]["reservesUnderwritten"][1] == pytest.approx(250)
    assert result["outputs"]["minDscr"] == pytest.approx(8_250 / 3_000)
    assert "underwrittenDscr" not in result["outputs"]
    # Exit caps the reserve-burdened NOI: 99,000 / 10.2%.
    assert stmt["saleProceedsGross"][60] == pytest.approx(99_000 / 0.102)
    # Same dollars either way — only the line placement moves.
    below = engine.compute(deal(replacementReservesPerUnit=300))
    assert stmt["levered"][1] == pytest.approx(below["statement"]["levered"][1])


def test_reserves_grow_on_the_expense_clock():
    result = engine.compute(
        deal(replacementReservesPerUnit=300, expenseGrowthMode="growing",
             expenseGrowthPct=0.03)
    )
    stmt = result["statement"]
    assert stmt["replacementReserves"][12] == pytest.approx(250)
    assert stmt["replacementReserves"][13] == pytest.approx(250 * 1.03)


def test_psf_reserves_and_missing_basis_warning():
    timeline, _ = build_timeline("acquisition", 5)
    vec, annual, warnings = operations.reserves_vector(
        {"replacementReservesPsf": 0.5, "rentableSf": 10_000}, timeline
    )
    assert annual == pytest.approx(5_000)
    assert vec[0] == pytest.approx(5_000 / 12)
    assert warnings == []
    # Per-unit reserves with no unit mix: inert, with a warning.
    vec, annual, warnings = operations.reserves_vector(
        {"replacementReservesPerUnit": 300}, timeline
    )
    assert vec is None and annual == 0.0
    assert any("no unit mix" in w for w in warnings)


def test_escrow_is_pure_cash_timing():
    plain = engine.compute(deal())
    escrowed = engine.compute(deal(monthsOfTaxesAndInsurance=6))
    stmt = escrowed["statement"]
    # 6 months of (12,000 + 6,000)/12 = 1,500/mo -> 9,000 at close, back at exit.
    assert stmt["levered"][0] == pytest.approx(-409_000)
    assert stmt["levered"][60] == pytest.approx(plain["statement"]["levered"][60] + 9_000)
    assert stmt["escrowFlows"][0] == pytest.approx(-9_000)
    assert stmt["escrowFlows"][60] == pytest.approx(9_000)
    # Unlevered never sees it (a lender requirement, not a property cost).
    assert stmt["unlevered"][0] == pytest.approx(plain["statement"]["unlevered"][0])
    # Round trip nets to zero -> total levered dollars unchanged, IRR lower.
    assert sum(stmt["levered"]) == pytest.approx(sum(plain["statement"]["levered"]))
    assert escrowed["outputs"]["leveredIrr"] < plain["outputs"]["leveredIrr"]
    uses = dict(escrowed["sourcesAndUses"]["uses"])
    assert uses["Tax & insurance escrows"] == pytest.approx(9_000)


def test_defaults_reproduce_run4():
    plain = engine.compute(deal())
    explicit = engine.compute(
        deal(replacementReservesPerUnit=0, replacementReservesPsf=0,
             reservesConvention="below_noi", monthsOfTaxesAndInsurance=0)
    )
    assert plain["outputs"] == explicit["outputs"]
    assert "replacementReserves" not in plain["statement"]
    assert "escrowFlows" not in plain["statement"]
    assert "underwrittenDscr" not in plain["outputs"]
    assert "reservesUnderwritten" not in plain["statement"]["fixedOpexByCategory"]
