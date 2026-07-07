"""L4: an optional junior capital tranche (mezz debt or pref equity) ranking
between senior debt and common equity. Two layers of tests: pure unit tests
on mezzanine.py's hand-computable month-by-month math, and engine-level
integration tests proving the tranche is correctly threaded into the cash
flow, leverage outputs, and Excel refusal list."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine, mezzanine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def analytic_dev() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


# ----------------------------------------------------------------------
# mezzanine.size_junior_tranche
# ----------------------------------------------------------------------

def test_sizing_absent_when_kind_unset():
    assert mezzanine.size_junior_tranche({}, senior_loan_amount=600_000, basis=1_000_000) is None


def test_sizing_fixed_amount():
    sizing = mezzanine.size_junior_tranche(
        {"juniorTrancheKind": "mezz", "juniorTrancheAmount": 200_000, "juniorTrancheRatePct": 0.1},
        senior_loan_amount=600_000, basis=1_000_000,
    )
    assert sizing is not None
    assert sizing.amount == 200_000
    assert sizing.kind == "mezz"
    assert sizing.pay_mode == "current"  # default


def test_sizing_fill_to_total_ltc():
    sizing = mezzanine.size_junior_tranche(
        {
            "juniorTrancheKind": "pref_equity",
            "juniorTrancheSizing": "fill_to_total_ltc",
            "juniorTrancheTotalLtcPct": 0.9,
        },
        senior_loan_amount=600_000, basis=1_000_000,
    )
    assert sizing is not None
    assert sizing.amount == pytest.approx(300_000)  # 0.9*1,000,000 - 600,000


def test_sizing_fill_to_total_ltc_never_negative():
    # Senior already exceeds the target combined leverage -> zero junior, not negative.
    sizing = mezzanine.size_junior_tranche(
        {
            "juniorTrancheKind": "mezz",
            "juniorTrancheSizing": "fill_to_total_ltc",
            "juniorTrancheTotalLtcPct": 0.5,
        },
        senior_loan_amount=600_000, basis=1_000_000,
    )
    assert sizing is None  # amount resolves to 0 -> no tranche


def test_sizing_origination_fee():
    sizing = mezzanine.size_junior_tranche(
        {
            "juniorTrancheKind": "mezz",
            "juniorTrancheAmount": 200_000,
            "juniorTrancheOriginationFeePct": 0.02,
        },
        senior_loan_amount=600_000, basis=1_000_000,
    )
    assert sizing.origination_fee == pytest.approx(4_000)


# ----------------------------------------------------------------------
# mezzanine.run_junior_tranche
# ----------------------------------------------------------------------

def test_current_pay_full_coverage_no_pik():
    sizing = mezzanine.JuniorTrancheSizing(
        kind="mezz", amount=1200, rate_pct=0.12, pay_mode="current", origination_fee=0.0,
    )
    result = mezzanine.run_junior_tranche(sizing, noi=[100, 100], senior_debt_service=[0, 0])
    # 1% monthly interest on 1200 = 12/mo; residual (100) covers it fully both months.
    assert result["serviceByMonth"] == pytest.approx([12, 12])
    assert result["balanceByMonth"] == pytest.approx([1200, 1200])
    assert result["exitRepayment"] == pytest.approx(1200)
    assert result["warnings"] == []


def test_current_pay_shortfall_converts_to_pik():
    sizing = mezzanine.JuniorTrancheSizing(
        kind="mezz", amount=6000, rate_pct=0.24, pay_mode="current", origination_fee=0.0,
    )
    # 2% monthly interest on 6000 = 120/mo due; residual only 50/mo (noi - senior).
    # Month 1: paid 50, shortfall 70 -> balance 6070.
    # Month 2: interest 6070*0.02=121.4, paid 50, shortfall 71.4 -> balance 6141.4.
    result = mezzanine.run_junior_tranche(sizing, noi=[50, 50], senior_debt_service=[0, 0])
    assert result["serviceByMonth"] == pytest.approx([50, 50])
    assert result["balanceByMonth"] == pytest.approx([6070, 6141.4])
    assert result["exitRepayment"] == pytest.approx(6141.4)
    assert len(result["warnings"]) == 1
    assert "PIK" in result["warnings"][0]


def test_accrued_mode_compounds_monthly_zero_cash_service():
    sizing = mezzanine.JuniorTrancheSizing(
        kind="pref_equity", amount=1000, rate_pct=0.12, pay_mode="accrued", origination_fee=0.0,
    )
    # 1%/mo compounding: 1000 -> 1010 -> 1020.1.
    result = mezzanine.run_junior_tranche(sizing, noi=[9999, 9999], senior_debt_service=[0, 0])
    assert result["serviceByMonth"] == pytest.approx([0, 0])
    assert result["balanceByMonth"] == pytest.approx([1010, 1020.1])
    assert result["exitRepayment"] == pytest.approx(1020.1)
    assert result["warnings"] == []


# ----------------------------------------------------------------------
# Engine integration
# ----------------------------------------------------------------------

def test_tranche_absent_reproduces_baseline(analytic):
    result = engine.compute(analytic)
    # Matches the fixture's own hand-derived comments exactly.
    assert result["outputs"]["equityMultiple"] == pytest.approx(1.55, abs=1e-4)
    assert result["juniorTranche"] is None
    assert "combinedLtv" not in result["outputs"]
    assert "combinedLtc" not in result["outputs"]


def test_current_pay_mezz_threaded_through_engine(analytic):
    inputs = {
        **analytic,
        "juniorTrancheKind": "mezz",
        "juniorTrancheAmount": 200_000,
        "juniorTrancheRatePct": 0.10,
        "juniorTranchePayMode": "current",
    }
    result = engine.compute(inputs)
    # Senior-only residual (NOI - senior DS) is 6,666.67 - 3,000 = 3,666.67/mo,
    # comfortably above the 200,000*0.10/12=1,666.67/mo mezz service -> no PIK.
    # initial_equity = 1,000,000 - 600,000 - 200,000 = 200,000.
    # Monthly levered = 3,666.67 - 1,666.67 = 2,000/mo; exit = net_sale_proceeds
    # (400,000) - exitRepayment (200,000, fully interest-serviced, no amortization).
    # Equity multiple = (59*2,000 + 202,000) / 200,000 = 1.6.
    assert result["outputs"]["equityMultiple"] == pytest.approx(1.6, abs=1e-4)
    assert result["juniorTranche"]["kind"] == "mezz"
    assert result["juniorTranche"]["exitRepayment"] == pytest.approx(200_000, rel=1e-3)
    assert not any("PIK" in w for w in result["warnings"])


def test_combined_leverage_includes_mezz(analytic):
    inputs = {
        **analytic,
        "juniorTrancheKind": "mezz",
        "juniorTrancheAmount": 200_000,
        "juniorTrancheRatePct": 0.10,
    }
    result = engine.compute(inputs)
    # perm_loan 600,000 + mezz 200,000 = 800,000; value/cost basis both 1,000,000.
    assert result["outputs"]["combinedLtv"] == pytest.approx(0.8)
    assert result["outputs"]["combinedLtc"] == pytest.approx(0.8)


def test_combined_leverage_excludes_pref_equity(analytic):
    inputs = {
        **analytic,
        "juniorTrancheKind": "pref_equity",
        "juniorTrancheAmount": 200_000,
        "juniorTrancheRatePct": 0.10,
    }
    result = engine.compute(inputs)
    # Pref equity isn't debt for leverage purposes -> combined == senior-only ltv/ltc.
    assert result["outputs"]["combinedLtv"] == pytest.approx(result["outputs"]["ltv"])
    assert result["outputs"]["combinedLtc"] == pytest.approx(result["outputs"]["ltc"])


def test_exit_repayment_ordering_senior_then_junior_shortfall_warns(analytic):
    inputs = {
        **analytic,
        "juniorTrancheKind": "mezz",
        "juniorTrancheAmount": 100_000,
        "juniorTrancheRatePct": 1.00,  # deliberately extreme to force an exit shortfall
        "juniorTranchePayMode": "accrued",
    }
    result = engine.compute(inputs)
    # Accrued balance compounds far beyond the 400,000 residual sale proceeds
    # (net of the senior payoff, which is netted out first) -> negative exit
    # flow and an explicit warning, never a silent clamp.
    assert result["statement"]["levered"][-1] < 0
    assert any("exceeds residual sale proceeds" in w for w in result["warnings"])


def test_development_deal_ignores_junior_tranche_with_warning(analytic_dev):
    without = engine.compute(analytic_dev)
    with_tranche = engine.compute({
        **analytic_dev,
        "juniorTrancheKind": "mezz",
        "juniorTrancheAmount": 500_000,
        "juniorTrancheRatePct": 0.10,
    })
    assert with_tranche["outputs"]["leveredIrr"] == pytest.approx(without["outputs"]["leveredIrr"])
    assert with_tranche["juniorTranche"] is None
    assert any("acquisition-only" in w for w in with_tranche["warnings"])


def test_excel_export_refuses_active_junior_tranche(analytic):
    from app.services.excel_model_export import unsupported_features

    active = {**analytic, "juniorTrancheKind": "mezz", "juniorTrancheAmount": 200_000}
    assert any("junior tranche" in f.lower() for f in unsupported_features(active))
    assert not any("junior tranche" in f.lower() for f in unsupported_features(analytic))
