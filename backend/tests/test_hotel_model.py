"""Roadmap #25: hotel operations (USALI summary), hand-computed.

100 keys x $200 ADR x 365 x 75% = $5,475,000 rooms revenue; + $1,000,000
F&B + $200,000 other = $6,675,000 total revenue (flat growth).
  Departmental 30% of revenue     2,002,500
  Undistributed 25% of revenue    1,668,750
  GOP                             3,003,750
  Management fee 3% of revenue      200,250
  Franchise fee 5% of rooms         273,750
  FF&E reserve 4% of revenue        267,000
  Taxes + insurance                 400,000
  NOI                             1,862,750
At a $40M price: going-in cap 4.6569%; exit at 8% on forward NOI =
$23,284,375. A $10M interest-only loan at 6% costs $600,000 a year, so
break-even occupancy = (fixed + debt service) / ((revenue - revenue-linked
costs) / occupancy) = 1,000,000 / (2,262,750 / 0.75) = 33.145%.
"""

import pytest

from app.services import excel_model_export
from app.services.proforma.engine import InsufficientInputsError, compute

HOTEL = {
    "dealType": "acquisition",
    "propertyType": "hotel",
    "purchasePrice": 40_000_000,
    "keys": 100,
    "adr": 200,
    "occupancyPct": 0.75,
    "fnbRevenue": 1_000_000,
    "otherRevenue": 200_000,
    "departmentalExpenseRatioPct": 0.30,
    "undistributedExpenseRatioPct": 0.25,
    "managementFeeHotelPct": 0.03,
    "franchiseFeePct": 0.05,
    "ffeReservePct": 0.04,
    "realEstateTaxes": 300_000,
    "insurance": 100_000,
    "rentGrowthMode": "flat",
    "expenseGrowthMode": "flat",
    "holdPeriodYears": 5,
    "exitCapRatePct": 0.08,
    "costOfSalePct": 0,
    "ltvOrLtc": 0.5,
    "loanAmount": 10_000_000,
    "interestRate": 0.06,
    "ioMonths": 60,
    "amortYears": 30,
    "loanTermYears": 10,
    "originationFeePct": 0,
}


def _year1(vec: list[float]) -> float:
    return sum(vec[1:13])


def test_hand_computed_noi_and_value():
    result = compute(dict(HOTEL))
    statement, outputs = result["statement"], result["outputs"]
    assert _year1(statement["hotel"]["roomsRevenue"]) == pytest.approx(5_475_000)
    assert _year1(statement["egi"]) == pytest.approx(6_675_000)
    assert _year1(statement["hotel"]["gop"]) == pytest.approx(3_003_750)
    assert _year1(statement["managementFee"]) == pytest.approx(200_250)
    assert _year1(statement["fixedOpexByCategory"]["franchiseFee"]) == pytest.approx(273_750)
    assert _year1(statement["fixedOpexByCategory"]["ffeReserve"]) == pytest.approx(267_000)
    assert _year1(statement["noi"]) == pytest.approx(1_862_750)
    assert outputs["goingInCapRate"] == pytest.approx(1_862_750 / 40_000_000)
    assert outputs["terminalValue"] == pytest.approx(1_862_750 / 0.08)
    assert outputs["breakEvenOccupancy"] == pytest.approx(1_000_000 / (2_262_750 / 0.75))


def test_statement_identities_hold():
    s = compute(dict(HOTEL))["statement"]
    for m in range(1, len(s["months"])):
        assert s["egi"][m] == pytest.approx(s["gpr"][m] - s["vacancyLoss"][m] - s["creditLoss"][m] + s["otherIncome"][m])
        assert s["noi"][m] == pytest.approx(s["egi"][m] - s["opexTotal"][m])


def test_revenue_grows_at_the_rent_growth_rate():
    s = compute(dict(HOTEL, rentGrowthMode="per_year", rentGrowthPct=0.03))["statement"]
    assert sum(s["egi"][13:25]) == pytest.approx(6_675_000 * 1.03)


def test_a_development_hotel_ramps_occupancy_during_lease_up():
    deal = dict(
        HOTEL, dealType="development", purchasePrice=None,
        landCost=5_000_000, hardCosts=30_000_000, constructionMonths=18, leaseUpMonths=12,
    )
    s = compute(deal)["statement"]
    first_open = s["constructionMonths"] + 1
    assert s["occupancy"][first_open] < 0.75
    assert s["occupancy"][s["stabilizationMonth"]] == pytest.approx(0.75)
    # F&B follows the ramp too.
    assert s["hotel"]["fnbRevenue"][first_open] < 1_000_000 / 12


def test_missing_hotel_inputs_are_named():
    with pytest.raises(InsufficientInputsError) as exc:
        compute(dict(HOTEL, adr=0, occupancyPct=None))
    assert exc.value.missing == ["adr", "occupancyPct"]


def test_non_hotel_deals_have_no_hotel_rows():
    deal = {k: v for k, v in HOTEL.items() if k not in ("keys", "adr")}
    deal.update(propertyType="multifamily", grossPotentialRent=1_000_000)
    assert "hotel" not in compute(deal)["statement"]


def test_the_excel_export_refuses_hotels():
    features = excel_model_export.unsupported_features(dict(HOTEL))
    assert any("hotel" in f for f in features)


def test_a_hotel_component_of_a_mixed_use_deal_warns_that_it_is_ignored():
    deal = dict(HOTEL, propertyType="mixed_use", mixedUseComponents=["retail", "hotel"], grossPotentialRent=1_000_000)
    assert any("hotel component" in w for w in compute(deal)["warnings"])
