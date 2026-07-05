"""I4: mixed-use opex allocation basis.

Base fixture = the H2 hand deal: 10x 1BR at $2,000 (res GPR 240k/yr) + one
10,000sf NNN lease at $30psf (300k/yr), recoverable taxes 54,000/yr
(4,500/mo). Hand shares:
  revenue_share_y1:  300/540 = 5/9          -> recoveries 2,500/mo
  sf (900sf units):  10,000/19,000 = 10/19  -> recoveries ~2,368.42/mo
  revenue_share_annual, flat rents: every year = y1 -> identical to default
"""

import pytest

from app.services.proforma import operations
from app.services.proforma.timeline import Timeline

from tests.test_mixed_use import mixed_deal


def _ops(deal, months=24):
    return operations.build_noi_vector(deal, Timeline(months, 0, 0, 1))


def test_default_basis_reproduces_run3():
    default = _ops(mixed_deal())
    explicit = _ops(mixed_deal(opexAllocationBasis="revenue_share_y1"))
    for key in ("noi", "recoveries", "egi"):
        assert explicit[key] == pytest.approx(default[key])
    assert default["recoveries"][0] == pytest.approx(4_500 * 300 / 540)


def test_sf_basis_hand_share():
    deal = mixed_deal(opexAllocationBasis="sf")
    deal["unitMix"] = [{"unitType": "1BR", "unitCount": 10, "inPlaceRent": 2000, "avgSf": 900}]
    ops = _ops(deal)
    share = 10_000 / (10_000 + 9_000)
    assert ops["recoveries"][0] == pytest.approx(4_500 * share)
    # Reporting follows the same basis: commercial opex share = sf share.
    fixed_total = 4_500
    assert ops["components"]["commercial"]["opex"][0] == pytest.approx(fixed_total * share)


def test_sf_basis_without_unit_sf_falls_back_with_warning():
    ops = _ops(mixed_deal(opexAllocationBasis="sf"))  # unit mix has no avgSf
    assert any("'sf' needs SF on both sides" in w for w in ops["warnings"])
    assert ops["recoveries"][0] == pytest.approx(4_500 * 300 / 540)  # y1 fallback


def test_revenue_share_annual_with_flat_rents_equals_y1():
    annual = _ops(mixed_deal(opexAllocationBasis="revenue_share_annual"))
    default = _ops(mixed_deal())
    assert annual["recoveries"] == pytest.approx(default["recoveries"])


def test_revenue_share_annual_moves_with_escalations():
    """Commercial escalates 10%/yr while residential is flat: the commercial
    share (and its recoveries) must RISE year over year."""
    deal = mixed_deal(opexAllocationBasis="revenue_share_annual")
    deal["commercialLeases"][0].update(
        {"escalationType": "fixed_pct", "escalationValue": 0.10}
    )
    ops = _ops(deal, months=24)
    share_y1 = 300 / 540
    assert ops["recoveries"][0] == pytest.approx(4_500 * share_y1)
    share_y2 = 330 / (330 + 240)
    assert ops["recoveries"][12] == pytest.approx(4_500 * share_y2)
    assert ops["recoveries"][12] > ops["recoveries"][0]


@pytest.mark.parametrize("basis", ["revenue_share_y1", "sf", "revenue_share_annual"])
def test_component_nois_sum_to_blended_under_every_basis(basis):
    deal = mixed_deal(opexAllocationBasis=basis)
    deal["unitMix"] = [{"unitType": "1BR", "unitCount": 10, "inPlaceRent": 2000, "avgSf": 900}]
    ops = _ops(deal, months=36)
    components = ops["components"]
    for m in range(36):
        total = components["residential"]["noi"][m] + components["commercial"]["noi"][m]
        assert total == pytest.approx(ops["noi"][m], abs=1e-9), (basis, m)
