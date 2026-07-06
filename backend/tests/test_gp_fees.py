"""J3: GP fee economics.

Base fixture = the analytic acquisition ($1M price, NOI $80k/yr, loan
$600k IO at 6%, equity $400k). Hand numbers used below:
  acquisition fee 1%      -> $10,000 more basis and equity at close
  AM fee 0.5% of EGI      -> 0.005 x 7,500 = $37.50/mo levered drag
  AM fee 1% of committed  -> 0.01 x 400,000 / 12 = $333.33/mo
"""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def test_acquisition_fee_is_a_use_in_basis_and_yoc():
    base = engine.compute(analytic())
    with_fee = engine.compute(analytic(acquisitionFeePct=0.01))
    # Basis rises by the fee -> YoC falls; equity at close rises.
    assert with_fee["outputs"]["yieldOnCost"] == pytest.approx(80_000 / 1_010_000)
    uses = dict(with_fee["sourcesAndUses"]["uses"])
    assert uses["Acquisition fee"] == pytest.approx(10_000)
    assert with_fee["statement"]["levered"][0] == pytest.approx(
        base["statement"]["levered"][0] - 10_000
    )
    # ...and the fee streams to the GP.
    assert with_fee["gpEconomics"]["acquisitionFee"] == pytest.approx(10_000)
    assert with_fee["outputs"]["gpFeesTotal"] == pytest.approx(10_000)


def test_am_fee_is_below_noi_on_both_bases():
    base = engine.compute(analytic())
    egi_based = engine.compute(analytic(assetMgmtFeePct=0.005))
    # EGI = 7,500/mo flat -> fee 37.50/mo, levered only.
    stmt = egi_based["statement"]
    assert stmt["assetMgmtFee"][1] == pytest.approx(37.50)
    assert stmt["noi"][1] == pytest.approx(base["statement"]["noi"][1])  # NOI untouched
    assert stmt["levered"][1] == pytest.approx(base["statement"]["levered"][1] - 37.50)
    assert stmt["unlevered"][1] == pytest.approx(base["statement"]["unlevered"][1])

    equity_based = engine.compute(
        analytic(assetMgmtFeePct=0.01, assetMgmtFeeBasis="committed_equity")
    )
    assert equity_based["statement"]["assetMgmtFee"][1] == pytest.approx(400_000 * 0.01 / 12)


def test_dscr_and_lender_metrics_unchanged_by_am_fee():
    base = engine.compute(analytic())
    with_fee = engine.compute(analytic(assetMgmtFeePct=0.01))
    for metric in ("minDscr", "avgDscr", "debtYield", "loanConstant", "ltv"):
        assert with_fee["outputs"][metric] == pytest.approx(base["outputs"][metric]), metric
    # Unlevered IRR untouched; levered and LP IRRs net the drag.
    assert with_fee["outputs"]["unleveredIrr"] == pytest.approx(base["outputs"]["unleveredIrr"])
    assert with_fee["outputs"]["leveredIrr"] < base["outputs"]["leveredIrr"]
    assert with_fee["outputs"]["lpIrr"] < base["outputs"]["lpIrr"]


def test_lp_and_gp_deltas_with_all_three_fees():
    """AM fee 0.5% of EGI on the analytic deal: levered CF drops 37.50/mo.
    LP takes 90% of the drag through the pro-rata waterfall; the GP's fee
    income shows in gpEconomics, not in waterfall flows."""
    base = engine.compute(analytic())
    fees = engine.compute(analytic(acquisitionFeePct=0.01, assetMgmtFeePct=0.005))

    gp = fees["gpEconomics"]
    assert gp["acquisitionFee"] == pytest.approx(10_000)
    assert gp["assetMgmtFees"] == pytest.approx(37.50 * 60)
    assert gp["feesTotal"] == pytest.approx(10_000 + 2_250)
    assert gp["developerFee"] == 0
    # No promote tiers on this fixture: GP waterfall flows are pure pro-rata.
    assert gp["promote"] == pytest.approx(0)
    assert gp["totalCompensation"] == pytest.approx(gp["feesTotal"] + gp["gpDistributionsNet"])

    # LP IRR delta is a real drag vs baseline (fee-free).
    assert fees["outputs"]["lpIrr"] < base["outputs"]["lpIrr"]
    assert fees["outputs"]["gpTotalCompensation"] > 0


def test_developer_fee_streams_to_gp_on_development():
    """The developer fee reports inside gpEconomics — but never ACTIVATES
    the block alone (its pre-J3 engine default would otherwise put the
    block on every Run-4 development deal, breaking the baseline)."""
    dev = json.loads((FIXTURES / "analytic_development.json").read_text())
    alone = engine.compute(dev)  # developerFeePct 0.04 in the fixture
    assert alone["gpEconomics"] is None

    result = engine.compute({**dev, "assetMgmtFeePct": 0.005})
    gp = result["gpEconomics"]
    assert gp["developerFee"] > 0
    # The budget already capitalizes it — gpEconomics only REPORTS the stream.
    uses = dict(result["sourcesAndUses"]["uses"])
    assert uses["Developer fee"] == pytest.approx(gp["developerFee"])


def test_zero_fee_defaults_reproduce_run4():
    plain = engine.compute(analytic())
    explicit = engine.compute(
        analytic(assetMgmtFeePct=0, assetMgmtFeeBasis="egi", acquisitionFeePct=0)
    )
    assert plain["outputs"] == explicit["outputs"]
    assert plain["gpEconomics"] is None
    assert "assetMgmtFee" not in plain["statement"]
    assert "gpFeesTotal" not in plain["outputs"]
