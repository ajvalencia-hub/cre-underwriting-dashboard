"""analysisStartDate (engine audit fix): lease dates map onto the deal's own
calendar. With the calendar fixed at 2026-01-01, a deal closing later saw
its expiries, rollover downtime, free rent and base years land in the
wrong operating month — the drift grows every month after Jan 2026."""

import calendar
import json
from datetime import date
from pathlib import Path

import pytest

from app.services.proforma import engine
from app.services.proforma.timeline import ANALYSIS_EPOCH, analysis_epoch

_FIXTURES = Path(__file__).parent / "regression" / "fixtures"
# Whole years: base years and recoveries group months by CALENDAR year, so
# only a whole-year move leaves every grouping (and so every number) equal.
SHIFT_MONTHS = 24


def _shift(iso: str, months: int) -> str:
    d = date.fromisoformat(iso)
    year, month0 = divmod(d.year * 12 + d.month - 1 + months, 12)
    last_day = calendar.monthrange(year, month0 + 1)[1]
    return date(year, month0 + 1, min(d.day, last_day)).isoformat()


@pytest.fixture
def rollover():
    return json.loads((_FIXTURES / "commercial_rollover.json").read_text())


def _shifted(deal: dict) -> dict:
    moved = json.loads(json.dumps(deal))
    for lease in moved["commercialLeases"]:
        for key in ("startDate", "endDate"):
            if lease.get(key):
                lease[key] = _shift(lease[key], SHIFT_MONTHS)
    return moved


def _close(a: dict, b: dict) -> list[str]:
    return [
        k for k in a
        if isinstance(a[k], (int, float)) and isinstance(b.get(k), (int, float))
        and b[k] != pytest.approx(a[k], rel=1e-9, abs=1e-9)
    ]


def test_moving_the_deal_and_its_leases_together_changes_nothing(rollover):
    base = engine.compute(rollover)["outputs"]
    moved = _shifted(rollover)
    moved["analysisStartDate"] = _shift(ANALYSIS_EPOCH.isoformat(), SHIFT_MONTHS)  # 2028-01-01
    assert _close(base, engine.compute(moved)["outputs"]) == []


def test_without_a_start_date_a_later_deal_is_mis_timed(rollover):
    # The bug this fixes: same deal closing 14 months later, calendar still 2026.
    base = engine.compute(rollover)["outputs"]
    assert _close(base, engine.compute(_shifted(rollover))["outputs"]) != []


def test_bad_date_warns_and_uses_the_default(rollover):
    result = engine.compute(dict(rollover, analysisStartDate="next spring"))
    assert result["warnings"][0].startswith("Analysis start date 'next spring' isn't a date")
    assert result["outputs"] == engine.compute(rollover)["outputs"]


def test_calendar_is_restored_after_compute(rollover):
    engine.compute(dict(rollover, analysisStartDate="2030-06-01"))
    assert analysis_epoch() == ANALYSIS_EPOCH
