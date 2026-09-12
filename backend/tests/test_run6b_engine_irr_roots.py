"""Run 6 wave 2 [FIN]: multiple-IRR diagnostics at the engine level. A deal
whose levered flows change sign twice (a negative exit: sale proceeds
below the debt payoff) has two IRRs; the engine reports the root nearest
the unlevered IRR, lists the other, and warns. Conventional deals are
untouched (no irrDiagnostics key, no warning)."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine, returns

FIXTURES = Path(__file__).parent / "fixtures"


def acquisition(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def _two_root_deal() -> dict:
    # Strong operating cash (2.5x rent) then an exit that does not cover the
    # senior payoff (40% exit cap) -> levered flows -, +..., -.
    return acquisition(grossPotentialRent=250_000, exitCapRatePct=0.4, ltvOrLtc=0.6)


def test_conventional_series_has_no_diagnostics():
    result = engine.compute(acquisition())
    assert "irrDiagnostics" not in result
    assert not any("IRRs in the" in w for w in result["warnings"])
    assert returns.sign_changes(result["statement"]["levered"]) == 1


def test_two_root_levered_series_reports_both_and_selects_the_economic_root():
    result = engine.compute(_two_root_deal())
    levered = result["statement"]["levered"]
    assert returns.sign_changes(levered) == 2
    diag = result["irrDiagnostics"]
    assert diag["irrMultipleRoots"] is True
    assert "unlevered" not in diag  # the asset flows are conventional
    lev = diag["levered"]
    assert lev["signChanges"] == 2
    assert len(lev["roots"]) == 2
    assert lev["roots"] == sorted(lev["roots"])
    # Both roots really are IRRs of the series.
    for root in lev["roots"]:
        monthly = (1 + root) ** (1 / 12) - 1
        assert returns._npv_periodic(monthly, levered) == pytest.approx(0, abs=1e-3)
    # Rule: the root nearest the unlevered IRR is reported; the other listed.
    unlev = result["outputs"]["unleveredIrr"]
    nearest = min(lev["roots"], key=lambda r: abs(r - unlev))
    assert lev["selected"] == pytest.approx(nearest)
    assert result["outputs"]["leveredIrr"] == pytest.approx(nearest)
    assert lev["otherRoots"] == [r for r in lev["roots"] if r != nearest]
    assert any(
        "2 IRRs in the -99%..300% band" in w and "nearest the unlevered IRR" in w
        for w in result["warnings"]
    )


def test_diagnostics_are_conditional_keys_only():
    """The block is absent from a conventional payload and its presence does
    not change any other key — a payload-level expansion, never a value
    change."""
    conventional = engine.compute(acquisition())
    two_root = engine.compute(_two_root_deal())
    assert set(two_root) - set(conventional) == {"irrDiagnostics"}
