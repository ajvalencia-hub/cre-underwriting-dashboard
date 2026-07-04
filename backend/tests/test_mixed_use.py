"""H2: mixed-use composition — component NOIs sum to blended per month,
single-component deals are untouched, and component-cap exit math.

Fixture: 10x 1BR at $2,000 (res GPR $240k/yr, 5% vacancy, credit 0) plus one
10,000sf NNN lease at $30psf ($300k/yr). Commercial recoverable share =
300k/(300k+240k) = 5/9 of the $54,000 recoverable taxes -> $2,500/mo
recoveries. Management fee 0, flat growth.

Hand month-1 numbers: res GPR 20,000, vacancy 1,000, res EGI 19,000;
com EGI 25,000 + 2,500 = 27,500; blended EGI 46,500; fixed opex 4,500;
blended NOI 42,000."""

import pytest

from app.services.proforma import engine, operations
from app.services.proforma.timeline import Timeline


def mixed_deal(**overrides) -> dict:
    deal = {
        "dealType": "acquisition", "propertyType": "mixed_use",
        "mixedUseComponents": ["multifamily", "retail"],
        "purchasePrice": 8_000_000, "closingCostsPct": 0, "acquisitionFeePct": 0,
        "holdPeriodYears": 5, "exitCapRatePct": 0.06, "costOfSalePct": 0,
        "unitMix": [{"unitType": "1BR", "unitCount": 10, "inPlaceRent": 2000}],
        "vacancyPct": 0.05, "creditLossPct": 0,
        "commercialLeases": [{
            "tenant": "Shop", "suiteId": "R1", "sf": 10_000,
            "startDate": "2026-01-01", "endDate": "2033-12-31",
            "baseRentPsfAnnual": 30, "escalationType": "none",
            "recoveryType": "NNN", "freeRentMonths": 0,
        }],
        "realEstateTaxes": 54_000, "managementFeePct": 0, "otherIncome": 0,
        "rentGrowthMode": "flat", "expenseGrowthMode": "flat",
        "ltvOrLtc": 0, "lpSplitPct": 0.9, "gpSplitPct": 0.1,
        "preferredReturnPct": 0.08, "waterfallTiers": [],
    }
    deal.update(overrides)
    return deal


def test_month_one_hand_numbers():
    ops = operations.build_noi_vector(mixed_deal(), Timeline(12, 0, 0, 1))
    assert ops["gprSource"] == "mixed"
    assert ops["gpr"][0] == pytest.approx(45_000)  # 20,000 res + 25,000 com
    assert ops["vacancyLoss"][0] == pytest.approx(1_000)
    assert ops["otherIncome"][0] == pytest.approx(2_500)  # commercial recoveries
    assert ops["egi"][0] == pytest.approx(46_500)
    assert ops["opex"][0] == pytest.approx(4_500)
    assert ops["noi"][0] == pytest.approx(42_000)


def test_component_nois_sum_to_blended_every_month():
    ops = operations.build_noi_vector(mixed_deal(), Timeline(60, 0, 0, 1))
    components = ops["components"]
    for m in range(60):
        total = components["residential"]["noi"][m] + components["commercial"]["noi"][m]
        assert total == pytest.approx(ops["noi"][m], abs=1e-9), m
        egi = components["residential"]["egi"][m] + components["commercial"]["egi"][m]
        assert egi == pytest.approx(ops["egi"][m], abs=1e-9), m


def test_commercial_recoveries_scaled_to_commercial_share():
    ops = operations.build_noi_vector(mixed_deal(), Timeline(12, 0, 0, 1))
    # 5/9 of $4,500/mo recoverable
    assert ops["recoveries"][0] == pytest.approx(4_500 * (300 / 540))


def test_component_cap_exit_blends_values():
    deal = mixed_deal(residentialExitCapPct=0.05, commercialExitCapPct=0.08)
    result = engine.compute(deal)
    statement = result["statement"]
    res_noi_annual = statement["components"]["residential"]["noi"][1] * 12
    com_noi_annual = statement["components"]["commercial"]["noi"][1] * 12
    expected = res_noi_annual / 0.05 + com_noi_annual / 0.08
    assert result["outputs"]["terminalValue"] == pytest.approx(expected, rel=1e-9)

    # Without component caps the single blended cap governs.
    single = engine.compute(mixed_deal())
    assert single["outputs"]["terminalValue"] == pytest.approx(42_000 * 12 / 0.06, rel=1e-9)


def test_per_component_yield_on_cost_outputs():
    result = engine.compute(mixed_deal(residentialExitCapPct=0.05, commercialExitCapPct=0.08))
    outputs = result["outputs"]
    assert "residentialYieldOnCost" in outputs and "commercialYieldOnCost" in outputs
    # Basis allocation is value-pro-rata, so the component YoCs bracket blended.
    blended = outputs["yieldOnCost"]
    assert min(outputs["residentialYieldOnCost"], outputs["commercialYieldOnCost"]) <= blended * (1 + 1e-9)
    assert max(outputs["residentialYieldOnCost"], outputs["commercialYieldOnCost"]) >= blended * (1 - 1e-9)


def test_single_component_deals_carry_no_component_artifacts():
    lease_only = mixed_deal(unitMix=[])
    result = engine.compute(lease_only)
    assert "components" not in result["statement"]
    assert "residentialYieldOnCost" not in result["outputs"]
    assert result["gprSource"] == "commercialLeases"

    res_only = mixed_deal(commercialLeases=[])
    result2 = engine.compute(res_only)
    assert "components" not in result2["statement"]
    assert result2["gprSource"] == "unitMix"


def test_statement_identities_hold_for_mixed(tmp_path):
    from tests.test_statement_detail import _assert_identities

    result = engine.compute(mixed_deal(ltvOrLtc=0.6, interestRate=0.06, amortYears=30))
    _assert_identities(result["statement"])
