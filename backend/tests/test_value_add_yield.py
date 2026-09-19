"""Value-add yield on cost (engine audit fix): the basis carries the full
renovation budget, so the numerator must be NOI once the program is done —
untrended. It used to be in-place NOI, so a renovation that raises rents
LOWERED yield on cost."""

import json
from pathlib import Path

import pytest

from app.services.proforma import engine

_FIXTURES = Path(__file__).parent / "fixtures"


def _closed_form_deal(**overrides) -> dict:
    deal = json.loads((_FIXTURES / "analytic_acquisition.json").read_text())
    deal.pop("_comment", None)
    deal.update(
        grossPotentialRent=0,
        unitMix=[{"unitType": "1BR", "unitCount": 10, "avgSf": 700, "inPlaceRent": 1000, "marketRent": 1000}],
        vacancyPct=0.0,
        realEstateTaxes=0,
        rentGrowthMode="per_year",
        rentGrowthPct=0.03,  # must NOT leak into the untrended yield
        renovationProgram=[
            {"unitType": "1BR", "unitsToReno": 10, "costPerUnit": 5000, "premiumPerMonth": 100,
             "downtimeMonthsPerUnit": 1, "unitsPerMonth": 10}
        ],
    )
    deal.update(overrides)
    return deal


def test_yield_on_cost_uses_post_renovation_untrended_noi():
    outputs = engine.compute(_closed_form_deal())["outputs"]
    # 10 units x ($1,000 + $100 premium) x 12 = $132,000 on $1,000,000 + $50,000.
    assert outputs["yieldOnCost"] == pytest.approx(132_000 / 1_050_000, rel=1e-9)


def test_a_rent_raising_renovation_raises_yield_on_cost():
    without = engine.compute(_closed_form_deal(renovationProgram=[]))["outputs"]["yieldOnCost"]
    with_program = engine.compute(_closed_form_deal())["outputs"]["yieldOnCost"]
    assert without == pytest.approx(120_000 / 1_000_000, rel=1e-9)
    assert with_program > without
