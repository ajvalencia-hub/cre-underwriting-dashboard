"""User construction draw schedule (roadmap #12): it shapes when the
non-land budget is spent; it used to be ignored (S-curve only)."""

import json
from pathlib import Path

import pytest

from app.services import excel_model_export
from app.services.proforma import engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dev():
    data = json.loads((_FIXTURES / "analytic_development.json").read_text())
    data.pop("_comment", None)
    return data  # 18-month build, land 2M, non-land budget 15,288,000


def _schedule(n_months, amounts):
    return [{"month": m, "drawAmount": a} for m, a in zip(range(1, n_months + 1), amounts)]


def test_costs_follow_the_drawn_shape_and_total_the_budget(dev):
    spend = 15_288_000
    # Everything in the last 6 months, evenly.
    draws = _schedule(18, [0] * 12 + [spend / 6] * 6)
    stmt = engine.compute(dict(dev, constructionDrawSchedule=draws))["statement"]
    assert stmt["costs"][0] == pytest.approx(2_000_000)  # land at close
    assert stmt["costs"][1:13] == pytest.approx([0.0] * 12)
    assert stmt["costs"][13:19] == pytest.approx([spend / 6] * 6)


def test_a_table_that_does_not_add_up_is_scaled_with_a_warning(dev):
    result = engine.compute(dict(dev, constructionDrawSchedule=_schedule(18, [1.0] * 18)))
    assert sum(result["statement"]["costs"][1:19]) == pytest.approx(15_288_000)
    assert any("draw schedule totals $18" in w for w in result["warnings"])


def test_late_spending_carries_less_interest_than_the_s_curve(dev):
    s_curve = engine.compute(dev)["constructionLoan"]
    late = engine.compute(dict(dev, constructionDrawSchedule=_schedule(18, [0] * 17 + [1])))["constructionLoan"]
    # Equity funds first; spending it all in the last month leaves almost no
    # time for loan interest to accrue.
    assert late["totalCost"] < s_curve["totalCost"]


def test_blank_schedule_keeps_the_s_curve(dev):
    assert engine.compute(dict(dev, constructionDrawSchedule=[]))["outputs"] == engine.compute(dev)["outputs"]


def test_excel_export_refuses_a_custom_schedule():
    from tests.parity.export_case import DEVELOPMENT_SCURVE_INPUTS

    deal = dict(DEVELOPMENT_SCURVE_INPUTS, constructionDrawSchedule=_schedule(12, [1] * 12))
    with pytest.raises(excel_model_export.UnsupportedModelFeatures):
        excel_model_export.build_model_workbook(deal)
