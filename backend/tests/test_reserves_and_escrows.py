"""L6: replacement reserves (NEW per-unit/PSF line, with a convention
toggle) + a T&I escrow. Two layers: pure unit tests on
operations.replacement_reserves_schedule's hand-computable math, and
engine-level integration tests proving both conventions and the escrow's
pure cash-timing effect are correctly wired — including the regression
guard that the OLD flat replacementReserves field never changes behavior."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine, operations
from app.services.proforma.timeline import Timeline

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


# ----------------------------------------------------------------------
# operations.replacement_reserves_schedule
# ----------------------------------------------------------------------

def test_inactive_when_per_unit_amount_unset():
    timeline = Timeline(12, 0, 0, 1)
    result = operations.replacement_reserves_schedule({}, timeline)
    assert result["aboveNoiByMonth"] == [0.0] * 12
    assert result["belowNoiByMonth"] == [0.0] * 12
    assert result["warnings"] == []


def test_per_unit_basis_below_noi_hand_computed():
    timeline = Timeline(12, 0, 0, 1)
    inputs = {
        "replacementReservesPerUnit": 300,
        "reservesBasis": "per_unit",
        "reservesConvention": "below_noi",
        "unitMix": [{"unitType": "1BR", "unitCount": 40}, {"unitType": "2BR", "unitCount": 60}],
    }
    result = operations.replacement_reserves_schedule(inputs, timeline)
    # 100 units x $300/yr = $30,000/yr = $2,500/mo, flat (no growth set).
    assert result["belowNoiByMonth"] == pytest.approx([2500.0] * 12)
    assert result["aboveNoiByMonth"] == [0.0] * 12
    assert result["warnings"] == []


def test_psf_basis_above_noi_hand_computed():
    timeline = Timeline(12, 0, 0, 1)
    inputs = {
        "replacementReservesPerUnit": 0.25,
        "reservesBasis": "psf",
        "reservesConvention": "above_noi_underwritten",
        "rentableSf": 100_000,
    }
    result = operations.replacement_reserves_schedule(inputs, timeline)
    # 100,000 SF x $0.25/SF/yr = $25,000/yr = $2,083.33/mo.
    assert result["aboveNoiByMonth"] == pytest.approx([25_000 / 12] * 12)
    assert result["belowNoiByMonth"] == [0.0] * 12


def test_grows_with_expense_growth_rate():
    timeline = Timeline(24, 0, 0, 1)
    inputs = {
        "replacementReservesPerUnit": 300,
        "unitMix": [{"unitCount": 100}],
        "expenseGrowthMode": "per_year",
        "expenseGrowthPct": 0.10,
    }
    result = operations.replacement_reserves_schedule(inputs, timeline)
    assert result["belowNoiByMonth"][0] == pytest.approx(2500.0)
    assert result["belowNoiByMonth"][12] == pytest.approx(2500.0 * 1.10)  # year 2 step-up


def test_zero_units_basis_warns_and_no_effect():
    timeline = Timeline(12, 0, 0, 1)
    result = operations.replacement_reserves_schedule(
        {"replacementReservesPerUnit": 300, "reservesBasis": "per_unit"}, timeline
    )
    assert result["belowNoiByMonth"] == [0.0] * 12
    assert len(result["warnings"]) == 1
    assert "zero effect" in result["warnings"][0]


def test_both_fields_set_warns_but_both_apply():
    timeline = Timeline(12, 0, 0, 1)
    inputs = {
        "replacementReserves": 20_000,
        "replacementReservesPerUnit": 300,
        "unitMix": [{"unitCount": 100}],
    }
    result = operations.replacement_reserves_schedule(inputs, timeline)
    assert any(v > 0 for v in result["belowNoiByMonth"])
    assert any("both apply" in w.lower() for w in result["warnings"])


# ----------------------------------------------------------------------
# Engine integration
# ----------------------------------------------------------------------

def test_new_fields_absent_reproduce_baseline(analytic):
    result = engine.compute(analytic)
    assert "belowNoiReserves" not in result["statement"]
    assert "escrowCashFlow" not in result["statement"]
    assert "lenderUwDscrOnNoiLessReserves" not in result["outputs"]


def test_below_noi_leaves_primary_noi_and_dscr_untouched(analytic):
    without = engine.compute(analytic)
    with_reserves = engine.compute({
        **analytic,
        "replacementReservesPerUnit": 300,
        "reservesBasis": "per_unit",
        "reservesConvention": "below_noi",
        "unitMix": [{"unitCount": 100, "inPlaceRent": analytic["grossPotentialRent"] / 12 / 100}],
    })
    # unitMix would normally override flat GPR -> pin the same GPR via the
    # row's inPlaceRent so this is an apples-to-apples NOI/DSCR comparison.
    assert with_reserves["outputs"]["minDscr"] == pytest.approx(without["outputs"]["minDscr"])
    assert with_reserves["outputs"]["yieldOnCost"] == pytest.approx(without["outputs"]["yieldOnCost"])
    # But the below-NOI supplemental view IS more conservative.
    assert with_reserves["outputs"]["lenderUwDscrOnNoiLessReserves"] < with_reserves["outputs"]["minDscr"]
    # And levered cash flow (below NOI) is strictly worse.
    assert with_reserves["outputs"]["leveredIrr"] < without["outputs"]["leveredIrr"]


def test_above_noi_underwritten_reduces_noi_and_dscr(analytic):
    without = engine.compute(analytic)
    with_reserves = engine.compute({
        **analytic,
        "replacementReservesPerUnit": 300,
        "reservesBasis": "per_unit",
        "reservesConvention": "above_noi_underwritten",
        "unitMix": [{"unitCount": 100, "inPlaceRent": analytic["grossPotentialRent"] / 12 / 100}],
    })
    assert with_reserves["outputs"]["minDscr"] < without["outputs"]["minDscr"]
    assert "lenderUwDscrOnNoiLessReserves" not in with_reserves["outputs"]


def test_old_flat_field_ignores_new_convention_toggle(analytic):
    # The legacy flat replacementReserves field must behave identically
    # regardless of reservesConvention -- it never reads that toggle.
    below = engine.compute({**analytic, "replacementReserves": 5000, "reservesConvention": "below_noi"})
    above = engine.compute({**analytic, "replacementReserves": 5000, "reservesConvention": "above_noi_underwritten"})
    default = engine.compute({**analytic, "replacementReserves": 5000})
    assert below["outputs"]["minDscr"] == pytest.approx(above["outputs"]["minDscr"])
    assert below["outputs"]["minDscr"] == pytest.approx(default["outputs"]["minDscr"])
    assert "lenderUwDscrOnNoiLessReserves" not in below["outputs"]


def test_escrow_round_trips_as_timing_only(analytic):
    without = engine.compute(analytic)
    with_escrow = engine.compute({**analytic, "monthsOfTaxesAndInsurance": 6})
    # Total nominal profit is UNCHANGED (the escrow returns dollar-for-dollar
    # at exit) -- only the timing (and therefore IRR/NPV) differs.
    assert with_escrow["outputs"]["totalProfit"] == pytest.approx(without["outputs"]["totalProfit"])
    assert with_escrow["outputs"]["leveredIrr"] < without["outputs"]["leveredIrr"]
    assert with_escrow["statement"]["escrowCashFlow"][0] < 0
    assert with_escrow["statement"]["escrowCashFlow"][-1] > 0
    assert with_escrow["statement"]["escrowCashFlow"][0] == pytest.approx(
        -with_escrow["statement"]["escrowCashFlow"][-1]
    )
    # Hand-computed: (10,000 taxes + 0 insurance)/12 x 6mo = 5,000.
    assert with_escrow["statement"]["escrowCashFlow"][-1] == pytest.approx(5000.0)


def test_excel_export_refuses_below_noi_reserves_and_escrow(analytic):
    from app.services.excel_model_export import unsupported_features

    reserves_active = {
        **analytic, "replacementReservesPerUnit": 300, "reservesConvention": "below_noi",
    }
    assert any("replacement reserves" in f.lower() for f in unsupported_features(reserves_active))

    above_noi = {
        **analytic, "replacementReservesPerUnit": 300, "reservesConvention": "above_noi_underwritten",
    }
    # above_noi_underwritten is NOT a native-only behavior -- it's the same
    # opex treatment the exporter already handles for the flat field.
    assert not any("replacement reserves" in f.lower() for f in unsupported_features(above_noi))

    escrow_active = {**analytic, "monthsOfTaxesAndInsurance": 6}
    assert any("escrow" in f.lower() for f in unsupported_features(escrow_active))
    assert not any("escrow" in f.lower() for f in unsupported_features(analytic))
