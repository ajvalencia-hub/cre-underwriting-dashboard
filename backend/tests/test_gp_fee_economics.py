"""L3: GP fee economics. acquisitionFeePct/developerFeePct already existed
(uses/YoC-basis, unchanged); new: assetMgmtFeePct, a partnership-level fee
below the property NOI line, and gpTotalComp aggregating all GP-side
economics."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def analytic() -> dict:
    return json.loads((FIXTURES / "analytic_acquisition.json").read_text())


@pytest.fixture
def analytic_dev() -> dict:
    return json.loads((FIXTURES / "analytic_development.json").read_text())


def test_am_fee_defaults_to_zero_effect(analytic):
    without = engine.compute(analytic)
    with_zero = engine.compute({**analytic, "assetMgmtFeePct": 0.0})
    assert without["outputs"]["lpIrr"] == pytest.approx(with_zero["outputs"]["lpIrr"], abs=1e-12)
    assert without["outputs"]["gpTotalComp"] == pytest.approx(with_zero["outputs"]["gpTotalComp"], abs=1e-12)


def test_am_fee_reduces_lp_irr_and_increases_gp_total_comp(analytic):
    without = engine.compute(analytic)
    with_fee = engine.compute({**analytic, "assetMgmtFeePct": 0.02, "assetMgmtFeeBasis": "egi"})
    assert with_fee["outputs"]["lpIrr"] < without["outputs"]["lpIrr"]
    assert with_fee["outputs"]["gpTotalComp"] > without["outputs"]["gpTotalComp"]


def test_am_fee_never_touches_dscr_or_noi():
    """The core structural guarantee: DSCR is bit-for-bit identical whether
    or not the AM fee is on, proving the upstream (NOI/debt)/downstream
    (levered/waterfall) separation actually holds — not just claimed."""
    inputs = json.loads((FIXTURES / "analytic_development.json").read_text())
    without = engine.compute(inputs)
    with_fee = engine.compute({**inputs, "assetMgmtFeePct": 0.03, "assetMgmtFeeBasis": "egi"})
    assert without["outputs"]["minDscr"] == with_fee["outputs"]["minDscr"]
    assert without["outputs"]["unleveredIrr"] == with_fee["outputs"]["unleveredIrr"]


def test_egi_basis_hand_computed(analytic):
    """analytic_acquisition.json is hand-derivable (see its own _comment):
    EGI = 90,000/yr flat, 5-year hold -> AM fee at 2% of EGI = $9,000 total,
    paid entirely to the GP (+9,000 in gpTotalComp) but ALSO shrinking the
    levered cash flow the no-promote pro-rata waterfall splits (this
    fixture has no waterfallTiers — LP/GP split strictly pro-rata at
    90/10), so the GP's OWN distributions fall by 10% of that same $9,000
    (-900). Net gpTotalComp delta = 9,000 - 900 = 8,100 — a real assertion
    on the fee math, not just "it changed."""
    result = engine.compute({**analytic, "assetMgmtFeePct": 0.02, "assetMgmtFeeBasis": "egi"})
    total_am_fee_net_of_gp_pro_rata_share = (
        result["outputs"]["gpTotalComp"] - engine.compute(analytic)["outputs"]["gpTotalComp"]
    )
    expected_fee = 90_000 * 5 * 0.02
    assert total_am_fee_net_of_gp_pro_rata_share == pytest.approx(
        expected_fee * (1 - analytic["gpSplitPct"]), rel=0.01
    )


def test_committed_equity_basis_is_flat_not_egi_linked(analytic):
    egi_based = engine.compute({**analytic, "assetMgmtFeePct": 0.01, "assetMgmtFeeBasis": "egi"})
    equity_based = engine.compute({**analytic, "assetMgmtFeePct": 0.01, "assetMgmtFeeBasis": "committed_equity"})
    # Different bases -> different LP IRR (unless coincidentally equal, which
    # this fixture's numbers rule out).
    assert egi_based["outputs"]["lpIrr"] != equity_based["outputs"]["lpIrr"]


def test_gp_total_comp_includes_existing_acquisition_and_developer_fees(analytic, analytic_dev):
    # Acquisition: acquisitionFeePct already 0 in the base fixture — set one.
    with_acq_fee = engine.compute({**analytic, "acquisitionFeePct": 0.02})
    without_acq_fee = engine.compute(analytic)
    assert with_acq_fee["outputs"]["gpTotalComp"] > without_acq_fee["outputs"]["gpTotalComp"]

    # Development: developerFeePct is already 0.04 in the base fixture —
    # zeroing it should lower gpTotalComp.
    without_dev_fee = engine.compute({**analytic_dev, "developerFeePct": 0.0})
    with_dev_fee = engine.compute(analytic_dev)
    assert with_dev_fee["outputs"]["gpTotalComp"] > without_dev_fee["outputs"]["gpTotalComp"]


def test_excel_export_refuses_active_am_fee(analytic):
    from app.services.excel_model_export import unsupported_features

    assert any("management fee" in f.lower() for f in unsupported_features({**analytic, "assetMgmtFeePct": 0.02}))
    assert not any("management fee" in f.lower() for f in unsupported_features(analytic))
