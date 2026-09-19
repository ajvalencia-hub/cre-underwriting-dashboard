"""Roadmap #26: build-to-sell homes.

Hand fixture (all equity, no site period, no growth or fees):
10 homes at $500,000, 2 closings a month, $300,000 to build over 2 months,
$1,000,000 land, 5% selling costs. First closing month 2; closings months
2-6; vertical spend $150,000 per home-month:
  month   0      1      2      3      4      5      6
  costs  1.00M  0.30M  0.60M  0.60M  0.60M  0.60M  0.30M
  sales    -      -    0.95M  0.95M  0.95M  0.95M  0.95M
  flow  -1.00M -0.30M +0.35M +0.35M +0.35M +0.35M +0.65M
Profit $750,000 on $4,750,000 net revenue (15.79% margin); peak equity
$1,300,000; equity multiple 2,050,000 / 1,300,000 = 1.5769x.
"""

import pytest

from app.services.proforma import for_sale
from app.services.proforma.engine import InsufficientInputsError, compute

HOMES = {
    "dealType": "development",
    "propertyType": "single_family",
    "isForSale": True,
    "homeCount": 10,
    "salePricePerHome": 500_000,
    "absorptionPerMonth": 2,
    "buildCostPerHome": 300_000,
    "homeBuildMonths": 2,
    "landCost": 1_000_000,
    "constructionMonths": 0,
    "costOfSalePct": 0.05,
    "contingencyPct": 0,
    "developerFeePct": 0,
    "ltvOrLtc": 0,
    "lpSplitPct": 0.9,
    "gpSplitPct": 0.1,
    "preferredReturnPct": 0.08,
}


def test_hand_computed_all_equity_deal():
    result = compute(dict(HOMES))
    s, outputs = result["statement"], result["outputs"]
    assert s["costs"] == pytest.approx([1_000_000, 300_000, 600_000, 600_000, 600_000, 600_000, 300_000])
    assert s["forSale"]["closings"] == [0, 0, 2, 2, 2, 2, 2]
    assert s["levered"] == pytest.approx([-1_000_000, -300_000, 350_000, 350_000, 350_000, 350_000, 650_000])
    assert outputs["totalProfit"] == pytest.approx(750_000)
    assert outputs["grossMarginPct"] == pytest.approx(750_000 / 4_750_000)
    assert outputs["peakEquity"] == pytest.approx(1_300_000)
    assert outputs["equityMultiple"] == pytest.approx(2_050_000 / 1_300_000)
    assert outputs["selloutYears"] == pytest.approx(5 / 12)


def test_the_statement_reconciles_every_month():
    s = compute(dict(HOMES, ltvOrLtc=0.6, interestRate=0.08, originationFeePct=0.01, absorptionPerMonth=1))["statement"]
    for m in s["months"]:
        expected = (
            s["noi"][m] - s["debtService"][m] + s["debtDraws"][m] - s["costs"][m]
            - s["loanFees"][m] - s["leasingCapital"][m] + s["saleProceedsNet"][m]
        )
        assert s["levered"][m] == pytest.approx(expected, abs=1e-6)


def test_the_loan_stays_within_its_commitment_and_is_repaid():
    result = compute(dict(HOMES, ltvOrLtc=0.6, interestRate=0.08, originationFeePct=0.01, absorptionPerMonth=1))
    s, su = result["statement"], result["sourcesAndUses"]
    commitment = result["debt"]["loanAmount"]
    assert max(s["loanBalance"]) <= commitment + 0.01
    assert s["loanBalance"][-1] == pytest.approx(0)
    assert sum(a for _, a in su["sources"]) == pytest.approx(sum(a for _, a in su["uses"]))
    # LTC is on total cost including interest and the fee.
    assert result["outputs"]["ltc"] == pytest.approx(0.6)
    assert not any("exceed the loan commitment" in w for w in result["warnings"])


def test_leverage_lowers_peak_equity_once_equity_share_is_spent():
    # A big site budget up front: the 40% equity share runs out before
    # closings start, so the loan carries the rest.
    heavy = dict(HOMES, hardCosts=5_000_000, constructionMonths=6)
    unlevered = compute(heavy)["outputs"]["peakEquity"]
    levered = compute(dict(heavy, ltvOrLtc=0.6, interestRate=0.08))["outputs"]["peakEquity"]
    assert levered < unlevered


def test_home_prices_grow_annually_from_the_first_closing():
    s = compute(dict(HOMES, homeCount=30, absorptionPerMonth=1, homePriceGrowthPct=0.05))["statement"]["forSale"]
    first = s["closings"].index(1)
    assert s["grossSales"][first + 11] == pytest.approx(500_000)
    assert s["grossSales"][first + 12] == pytest.approx(525_000)


def test_without_a_sale_price_the_deal_is_not_for_sale():
    assert not for_sale.applies(dict(HOMES, salePricePerHome=None))
    assert not for_sale.applies(dict(HOMES, isForSale=False))
    assert not for_sale.applies(dict(HOMES, propertyType="multifamily"))


def test_missing_for_sale_inputs_are_named():
    with pytest.raises(InsufficientInputsError) as exc:
        compute(dict(HOMES, absorptionPerMonth=0, buildCostPerHome=0))
    assert exc.value.missing == ["absorptionPerMonth", "buildCostPerHome (or hardCosts for site work)"]


def test_single_family_rentals_compute_from_homes_and_rent():
    deal = {
        **{k: v for k, v in HOMES.items() if k != "salePricePerHome"},
        "isForSale": False, "rentPerHome": 2_500, "hardCosts": 3_000_000,
        "holdPeriodYears": 5, "exitCapRatePct": 0.055, "constructionMonths": 12,
    }
    result = compute(deal)
    assert result["gprSource"] == "homes"
    assert result["statement"]["gpr"][-1] == pytest.approx(10 * 2_500)


def test_hold_sweep_and_excel_export_decline_for_sale_deals():
    from app.services import excel_model_export
    from app.services.proforma import hold

    sweep = hold.hold_sweep(dict(HOMES))
    assert sweep["rows"] == [] and "no hold period" in sweep["warnings"][0]
    assert any("build-to-sell" in f for f in excel_model_export.unsupported_features(dict(HOMES)))
