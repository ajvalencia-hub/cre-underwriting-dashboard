"""Min DSCR is tested on loan years (engine audit fix). The minimum of
monthly DSCRs let a single rollover-downtime month set the headline — on
the commercial rollover case 1.31x monthly vs ~1.75x on the worst year."""

import json
from pathlib import Path

import pytest

from app.services.proforma import debt, engine

_FIXTURES = Path(__file__).parent / "regression" / "fixtures"


def test_loan_year_windows():
    assert debt.annual_dscr_windows(1, 60) == [(1, 12), (13, 24), (25, 36), (37, 48), (49, 60)]
    # Trailing partial year dropped when a full year exists.
    assert debt.annual_dscr_windows(31, 84) == [(31, 42), (43, 54), (55, 66), (67, 78)]
    # Less than a year of service: the one partial window.
    assert debt.annual_dscr_windows(55, 60) == [(55, 60)]
    assert debt.annual_dscr_windows(10, 5) == []


def test_min_dscr_is_the_worst_loan_year_not_the_worst_month():
    inputs = json.loads((_FIXTURES / "commercial_rollover.json").read_text())
    result = engine.compute(inputs)
    stmt, outputs = result["statement"], result["outputs"]
    service = [m for m in range(1, len(stmt["noi"])) if (stmt["debtService"][m] or 0) > 0]
    windows = debt.annual_dscr_windows(service[0], service[-1])
    expected = min(
        sum(stmt["noi"][m] for m in range(a, b + 1)) / sum(stmt["debtService"][m] for m in range(a, b + 1))
        for a, b in windows
    )
    assert outputs["minDscr"] == pytest.approx(expected, rel=1e-12)
    assert outputs["minMonthlyDscr"] < outputs["minDscr"]  # a downtime month is worse than its year
