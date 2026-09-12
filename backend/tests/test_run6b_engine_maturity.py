"""Run 6 wave 2 [FIN]: loan maturity inside the hold — loanMaturityBehavior
ignore (default, byte-identical to before loanTermYears was read) /
balloon (payoff from equity, unlevered thereafter) / refinance (new
constraint-sized loan on trailing-12 NOI at rate + refiRateSpreadPct with
refiCostsPct costs, fresh amortization, no IO).

Base = the analytic acquisition: $600,000 IO senior at 6% (service
3,000/mo), 60-month IO period. The maturity cases stretch the hold to 7
years with a 5-year term so the loan matures in month 60 of 84.
"""

import json
from pathlib import Path

import pytest

from app.services import excel_model_export
from app.services.proforma import engine

FIXTURES = Path(__file__).parent / "fixtures"


def acquisition(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


def development(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_development.json").read_text())
    deal.update(overrides)
    return deal


def _maturing(mode: str, **extra) -> dict:
    """7-year hold, 5-year term, 3% rent growth (so a refinance sizes up)."""
    return acquisition(
        holdPeriodYears=7, loanTermYears=5, loanMaturityBehavior=mode,
        rentGrowthMode="per_year", rentGrowthPct=0.03, **extra,
    )


def _levered_identity(statement: dict) -> None:
    n = len(statement["months"])
    zeros = [0.0] * n
    for m in range(n):
        expected = (
            statement["noi"][m]
            - statement["debtService"][m]
            + statement["debtDraws"][m]
            - statement["costs"][m]
            - statement["loanFees"][m]
            - statement["leasingCapital"][m]
            + statement["saleProceedsNet"][m]
            - statement.get("loanPayoff", zeros)[m]
        )
        assert statement["levered"][m] == pytest.approx(expected, abs=1e-6), f"levered tie @ {m}"


# ---------------------------------------------------------------- ignore


def test_ignore_is_byte_identical_to_absent_key():
    """The default reproduces today's payload exactly — loanTermYears stays
    unread under ignore even when term < hold."""
    base = acquisition(holdPeriodYears=7, loanTermYears=5,
                       rentGrowthMode="per_year", rentGrowthPct=0.03)
    explicit = {**base, "loanMaturityBehavior": "ignore"}
    assert engine.compute(explicit) == engine.compute(base)
    assert "loanPayoff" not in engine.compute(base)["statement"]
    assert "balloon" not in engine.compute(base)["debt"]
    assert "refinance" not in engine.compute(base)["debt"]


def test_term_at_or_beyond_hold_is_identical_across_modes():
    """term >= hold: the exit payoff already retires the loan — every mode
    is the same payload (no conditional keys, no warnings)."""
    for term in (5, 10):
        results = {
            mode: engine.compute(acquisition(loanTermYears=term, loanMaturityBehavior=mode))
            for mode in ("ignore", "balloon", "refinance")
        }
        assert results["balloon"] == results["ignore"]
        assert results["refinance"] == results["ignore"]


def test_unknown_mode_warns_and_ignores():
    result = engine.compute(_maturing("bogus"))
    assert any("Unknown loanMaturityBehavior" in w for w in result["warnings"])
    assert result["outputs"] == engine.compute(_maturing("ignore"))["outputs"]


# ---------------------------------------------------------------- balloon


def test_balloon_repays_at_maturity_and_runs_unlevered_after():
    ignore = engine.compute(_maturing("ignore"))
    balloon = engine.compute(_maturing("balloon"))
    stmt = balloon["statement"]

    # Month 60: the last scheduled payment (3,000 IO) AND the 600,000 payoff.
    assert stmt["debtService"][60] == pytest.approx(3_000)
    assert stmt["loanPayoff"][60] == pytest.approx(600_000)
    assert stmt["loanBalance"][60] == pytest.approx(0)
    assert stmt["levered"][60] == pytest.approx(stmt["noi"][60] - 3_000 - 600_000)
    # Months 61..84: no debt service, no balance, levered == unlevered.
    for m in range(61, 85):
        assert stmt["debtService"][m] == 0.0
        assert stmt["interest"][m] == 0.0
        assert stmt["loanBalance"][m] == 0.0
        assert stmt["levered"][m] == pytest.approx(stmt["unlevered"][m])
    assert sum(stmt["loanPayoff"]) == pytest.approx(600_000)
    # Exit: nothing to pay off — net proceeds = gross net of costs.
    assert balloon["outputs"]["netSaleProceeds"] == pytest.approx(
        stmt["saleProceedsGross"][84]
    )
    # Positive-leverage deal: retiring the debt early lowers the levered IRR.
    assert balloon["outputs"]["leveredIrr"] < ignore["outputs"]["leveredIrr"]
    assert balloon["outputs"]["unleveredIrr"] == pytest.approx(
        ignore["outputs"]["unleveredIrr"]
    )
    assert balloon["debt"]["balloon"] == {"month": 60, "balance": pytest.approx(600_000)}
    assert "refinance" not in balloon["debt"]
    assert any("balloon" in w and "month 60" in w for w in balloon["warnings"])
    _levered_identity(stmt)


def test_balloon_payoff_is_stripped_from_cash_on_cash():
    """The payoff is a capital event, not operating cash — avg CoC must not
    carry a -600,000 year (it would be deeply negative otherwise)."""
    balloon_run = engine.compute(_maturing("balloon"))
    ignore_run = engine.compute(_maturing("ignore"))
    balloon, ignore = balloon_run["outputs"], ignore_run["outputs"]
    assert balloon["avgCashOnCash"] > 0

    def equity_in(result: dict) -> float:
        return -sum(cf for cf in result["statement"]["levered"] if cf < 0)

    # The payoff IS a capital call — it joins total equity in (the same
    # contribution definition equityMultiple uses), so the ratio's
    # denominator grows; the year-1 NUMERATOR is untouched.
    assert equity_in(balloon_run) == pytest.approx(equity_in(ignore_run) + 600_000 - 4_607.98, abs=1)
    assert balloon["cashOnCashYear1"] * equity_in(balloon_run) == pytest.approx(
        ignore["cashOnCashYear1"] * equity_in(ignore_run)
    )
    # Year 5 (months 49-60) operating cash: the ignore case's months 49-60
    # are IO at 3,000 — the balloon strip leaves the same operating sum.
    year5_balloon = sum(balloon_run["statement"]["levered"][49:61]) + 600_000
    year5_ignore = sum(ignore_run["statement"]["levered"][49:61])
    assert year5_balloon == pytest.approx(year5_ignore)


def test_balloon_dscr_only_counts_months_with_debt():
    balloon = engine.compute(_maturing("balloon"))["outputs"]
    ignore = engine.compute(_maturing("ignore"))["outputs"]
    # The IO months 1..60 are shared; the ignore case adds amortizing months
    # 61..84 whose (growing NOI / larger payment) DSCR differs.
    assert balloon["minDscr"] == pytest.approx(min(
        engine.compute(_maturing("balloon"))["statement"]["noi"][m] / 3_000
        for m in range(1, 61)
    ))
    assert balloon["minDscr"] != ignore["minDscr"] or balloon["avgDscr"] != ignore["avgDscr"]


# -------------------------------------------------------------- refinance


def test_refinance_sizes_a_new_loan_on_trailing_noi_and_cashes_out():
    refi = engine.compute(_maturing("refinance", refiCostsPct=0.01))
    stmt = refi["statement"]
    block = refi["debt"]["refinance"]

    assert block["month"] == 60
    assert block["oldBalance"] == pytest.approx(600_000)
    # Trailing-12 NOI ending month 60, valued at the exit cap; LTV governs
    # (60% x value) because DSCR / debt yield allow more.
    trailing = sum(stmt["noi"][49:61])
    assert block["sizingNoi"] == pytest.approx(trailing)
    assert block["sizingNoiBasis"] == "trailing_12"
    assert block["value"] == pytest.approx(trailing / 0.08)
    assert block["candidates"]["ltv"] == pytest.approx(0.6 * trailing / 0.08)
    assert block["newLoan"] == pytest.approx(block["candidates"]["ltv"])
    assert block["governingConstraint"] == "LTV"
    assert block["newLoan"] > 600_000  # grown NOI -> larger loan
    assert block["cashOut"] == pytest.approx(block["newLoan"] - 600_000)
    assert block["cashOut"] > 0
    assert block["costs"] == pytest.approx(0.01 * block["newLoan"])
    assert block["netToEquity"] == pytest.approx(block["cashOut"] - block["costs"])
    assert block["ratePct"] == pytest.approx(0.06)  # rate + 0 spread

    # Statement: gross new loan in debtDraws, old balance in loanPayoff,
    # costs in loanFees, balance rolls to the new loan.
    assert stmt["debtDraws"][60] == pytest.approx(block["newLoan"])
    assert stmt["loanPayoff"][60] == pytest.approx(600_000)
    assert stmt["loanFees"][60] == pytest.approx(block["costs"])
    assert stmt["loanBalance"][60] == pytest.approx(block["newLoan"])
    assert stmt["levered"][60] == pytest.approx(
        stmt["noi"][60] - 3_000 + block["newLoan"] - 600_000 - block["costs"]
    )
    # A fresh 30-year amortizing schedule with NO IO from month 61.
    assert stmt["principal"][61] > 0
    assert stmt["interest"][61] == pytest.approx(block["newLoan"] * 0.06 / 12)
    assert stmt["loanBalance"][61] == pytest.approx(block["newLoan"] - stmt["principal"][61])
    assert stmt["loanBalance"][84] < block["newLoan"]
    assert stmt["loanBalance"][84] > 0
    # Exit payoff is the NEW loan's balance.
    assert refi["outputs"]["netSaleProceeds"] == pytest.approx(
        stmt["saleProceedsGross"][84] - stmt["loanBalance"][84]
    )
    assert "balloon" not in refi["debt"]
    _levered_identity(stmt)


def test_refinance_uses_rate_spread_and_flags_paydown():
    spread = engine.compute(_maturing("refinance", refiRateSpreadPct=0.01))
    assert spread["debt"]["refinance"]["ratePct"] == pytest.approx(0.07)
    assert spread["statement"]["interest"][61] == pytest.approx(
        spread["debt"]["refinance"]["newLoan"] * 0.07 / 12
    )
    # Tight DSCR at maturity sizes below the maturing balance -> paydown.
    paydown = engine.compute(_maturing("refinance", dscrConstraint=2.5))
    block = paydown["debt"]["refinance"]
    assert block["newLoan"] < 600_000
    assert block["cashOut"] < 0
    assert any("equity paydown" in w for w in paydown["warnings"])
    _levered_identity(paydown["statement"])


def test_refinance_cash_out_is_stripped_from_cash_on_cash():
    refi = engine.compute(_maturing("refinance"))["outputs"]
    ignore = engine.compute(_maturing("ignore"))["outputs"]
    # Year 5 would otherwise carry the ~85k cash-out; operating CoC stays in
    # the same neighborhood as the ignore case.
    assert abs(refi["avgCashOnCash"] - ignore["avgCashOnCash"]) < 0.02


def test_refinance_floating_mode_keeps_floating():
    floating = _maturing(
        "refinance", rateMode="floating", currentIndexPct=0.04, spreadBps=200,
        forwardCurve=[{"month": 61, "indexPct": 0.03}],
    )
    result = engine.compute(floating)
    block = result["debt"]["refinance"]
    # Priced at the in-force curve rate for month 61 (3% + 200bps).
    assert block["ratePct"] == pytest.approx(0.05)
    assert result["statement"]["interest"][61] == pytest.approx(block["newLoan"] * 0.05 / 12)
    _levered_identity(result["statement"])


# ------------------------------------------------------------ development


def test_development_perm_loan_term_runs_from_takeout():
    """Perm loan funds at the takeout (month 31 here); a 3-year term matures
    in month 31 + 36 - 1 = 66 of the 84-month hold."""
    base = engine.compute(development())
    assert base["statement"]["stabilizationMonth"] == 31
    balloon = engine.compute(development(loanTermYears=3, loanMaturityBehavior="balloon"))
    assert balloon["debt"]["balloon"]["month"] == 66
    assert balloon["statement"]["loanPayoff"][66] == pytest.approx(
        base["statement"]["loanBalance"][66]
    )
    assert all(balloon["statement"]["debtService"][m] == 0.0 for m in range(67, 85))
    assert balloon["outputs"]["leveredIrr"] < base["outputs"]["leveredIrr"]
    _levered_identity(balloon["statement"])

    refi = engine.compute(development(loanTermYears=3, loanMaturityBehavior="refinance"))
    assert refi["debt"]["refinance"]["month"] == 66
    assert refi["debt"]["refinance"]["oldBalance"] == pytest.approx(
        base["statement"]["loanBalance"][66]
    )
    _levered_identity(refi["statement"])
    # The perm rate (construction rate + spread) is the refinance rate too —
    # the spread is never applied twice.
    assert refi["debt"]["refinance"]["ratePct"] == pytest.approx(
        development()["interestRate"] + (development().get("refiRateSpreadPct") or 0)
    )

    # A term that outlives the hold from takeout is identical to ignore.
    assert engine.compute(development(loanTermYears=5, loanMaturityBehavior="balloon")) == base


def test_development_without_takeout_has_no_maturity():
    """Sold before stabilization: construction debt is repaid from sale
    proceeds — there is no perm loan to mature."""
    short = development(holdPeriodYears=2.5, loanTermYears=1, loanMaturityBehavior="balloon")
    result = engine.compute(short)
    assert "loanPayoff" not in result["statement"]
    assert "balloon" not in (result["debt"] or {})


# ------------------------------------------------------------ Excel export


def test_excel_export_refuses_both_non_ignore_modes_and_allows_ignore():
    for mode in ("balloon", "refinance"):
        blockers = excel_model_export.unsupported_features(_maturing(mode))
        assert any("loanMaturityBehavior=" + mode in b for b in blockers), blockers
        with pytest.raises(excel_model_export.UnsupportedModelFeatures):
            excel_model_export.build_model_workbook(_maturing(mode))
    assert not [
        b for b in excel_model_export.unsupported_features(_maturing("ignore"))
        if "maturity" in b
    ]
    data, _ = excel_model_export.build_model_workbook(_maturing("ignore"))
    assert data[:2] == b"PK"
