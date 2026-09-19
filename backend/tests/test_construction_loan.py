"""Construction loan sizing (engine audit fix): LTC is measured on TOTAL
cost including capitalized interest and loan fees, and the origination fee
is charged on the loan commitment. Before the fix, a 60% LTC deal carried
~61.4% of total cost as debt and paid the fee on its first draw only."""

import json
from pathlib import Path

import pytest

from app.services.proforma import debt, engine

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dev_inputs():
    data = json.loads((_FIXTURES / "analytic_development.json").read_text())
    data.pop("_comment", None)
    return data


def test_ltc_holds_on_total_cost_including_financing(dev_inputs):
    result = engine.compute(dev_inputs)
    loan = result["constructionLoan"]
    uses = dict(result["sourcesAndUses"]["uses"])
    total_cost = sum(uses.values())
    assert loan["totalCost"] == pytest.approx(total_cost, rel=1e-12)
    assert loan["commitment"] / total_cost == pytest.approx(dev_inputs["ltvOrLtc"], abs=1e-9)
    assert loan["equity"] == pytest.approx(total_cost - loan["commitment"], rel=1e-12)


def test_origination_fee_is_charged_on_the_commitment(dev_inputs):
    result = engine.compute(dev_inputs)
    fee = dict(result["sourcesAndUses"]["uses"])["Loan fees"]
    assert fee == pytest.approx(dev_inputs["originationFeePct"] * result["constructionLoan"]["commitment"], rel=1e-9)


def test_construction_balance_ends_at_the_commitment(dev_inputs):
    financing, equity, commitment = debt.size_construction_loan(
        [2_000_000.0] + [1_000_000.0] * 16, 18_000_000.0, 0.6, 0.07, 0.01
    )
    assert financing.ending_balance == pytest.approx(commitment, rel=1e-9)
    total = 18_000_000.0 + financing.interest_capitalized + financing.fee_capitalized
    assert commitment == pytest.approx(0.6 * total, rel=1e-9)
    assert financing.fee_capitalized == pytest.approx(0.01 * commitment, rel=1e-9)


def test_zero_ltc_is_all_equity():
    financing, equity, commitment = debt.size_construction_loan([1.0, 2.0, 3.0], 6.0, 0.0, 0.07, 0.01)
    assert commitment == 0.0 and equity == 6.0
    assert financing.interest_capitalized == 0.0 and financing.fee_capitalized == 0.0
