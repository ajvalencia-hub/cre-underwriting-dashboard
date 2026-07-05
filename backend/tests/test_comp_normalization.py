"""I6: comp normalization — tiered rent comparison (unit-type weighted ->
$/SF -> pooled with a low-confidence note), the per-tier minimum-3 rule,
and the sale-comp basis note."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import RentComp, SaleComp
from app.services import comps as comps_service
from app.services.comps import weighted_type_median


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def _rent(name, rent, unit_type="", sf=None):
    return RentComp(name=name, market="Miami", avg_rent=rent, unit_type=unit_type, avg_sf=sf)


TYPED_COMPS = [
    _rent("a", 1_800, "1BR"), _rent("b", 1_900, "1 Bd"), _rent("c", 2_000, "1BR"),
    _rent("d", 2_400, "2BR"), _rent("e", 2_500, "2br"), _rent("f", 2_600, "2 Bed"),
]


def test_weighted_type_median_math():
    """50/50 mix of 1BR (median 1,900) and 2BR (median 2,500) -> 2,200."""
    result = weighted_type_median(TYPED_COMPS, [
        {"bedrooms": 1, "count": 5}, {"bedrooms": 2, "count": 5},
    ])
    assert result is not None
    blended, used = result
    assert blended == pytest.approx(2_200)
    assert used == 6

    # 80/20 weighting shifts the blend toward the heavier class.
    blended_80, _ = weighted_type_median(TYPED_COMPS, [
        {"bedrooms": 1, "count": 8}, {"bedrooms": 2, "count": 2},
    ])
    assert blended_80 == pytest.approx(0.8 * 1_900 + 0.2 * 2_500)


def test_typed_tier_requires_full_mix_coverage():
    """A subject class with < 3 typed comps disqualifies tier 1 entirely —
    a half-covered mix would silently skew the blend."""
    assert weighted_type_median(TYPED_COMPS, [
        {"bedrooms": 1, "count": 5}, {"bedrooms": 3, "count": 5},  # no 3BR comps
    ]) is None


def _flags(session_factory, comps_list, subject, asset_class="multifamily"):
    with session_factory() as db:
        for comp in comps_list:
            db.add(comp)
        db.commit()
        return comps_service.benchmark_flags(db, "Miami", asset_class, subject)


def test_tier1_fires_and_states_its_basis(session_factory):
    flags = _flags(session_factory, TYPED_COMPS, {
        "avgRentMonthly": 2_700,
        "bedroomMix": [{"bedrooms": 1, "count": 5}, {"bedrooms": 2, "count": 5}],
    })
    flag = next(f for f in flags if f["metric"] == "rent_vs_comps")
    assert flag["benchmarkValue"] == pytest.approx(2_200)
    assert "unit-type weighted" in flag["explanation"]
    assert "Low-confidence" not in flag["explanation"]
    # 2,700 / 2,200 - 1 = +22.7% -> warning (thresholds unchanged per tier).
    assert flag["verdict"] == "warning"


def test_tier2_psf_when_types_missing(session_factory):
    comps_list = [
        _rent("a", 1_800, "", 900), _rent("b", 2_000, "", 1_000), _rent("c", 2_200, "", 1_100),
    ]  # $/SF: 2.0 each -> median 2.0
    flags = _flags(session_factory, comps_list, {
        "avgRentMonthly": 2_400, "avgUnitSf": 1_000,
        "bedroomMix": [{"bedrooms": 1, "count": 10}],  # typed tier can't cover
    })
    flag = next(f for f in flags if f["metric"] == "rent_vs_comps")
    assert "$/SF median" in flag["explanation"]
    assert flag["subjectValue"] == pytest.approx(2.4)
    assert flag["benchmarkValue"] == pytest.approx(2.0)
    assert flag["verdict"] == "caution"  # +20% is not > 20%; > 10% -> caution


def test_tier3_pooled_carries_the_low_confidence_note(session_factory):
    comps_list = [_rent("a", 1_800), _rent("b", 2_000), _rent("c", 2_200)]  # no types, no SF
    flags = _flags(session_factory, comps_list, {"avgRentMonthly": 2_000})
    flag = next(f for f in flags if f["metric"] == "rent_vs_comps")
    assert "pooled median" in flag["explanation"]
    assert "Low-confidence" in flag["explanation"]
    assert flag["verdict"] == "ok"


def test_minimum_three_applies_per_tier(session_factory):
    """Two comps total: every tier fails -> no flag at all."""
    flags = _flags(session_factory, [_rent("a", 1_800), _rent("b", 2_000)], {
        "avgRentMonthly": 2_600, "avgUnitSf": 900,
        "bedroomMix": [{"bedrooms": 1, "count": 10}],
    })
    assert not [f for f in flags if f["metric"] == "rent_vs_comps"]


def test_sale_basis_note_by_asset_class(session_factory):
    sales = [
        SaleComp(name=f"s{i}", market="Miami", cap_rate_pct=0.055,
                 price=10_000_000, units=40, sf=50_000)
        for i in range(3)
    ]
    mf = _flags(session_factory, sales, {"exitCapRatePct": 0.055}, "multifamily")
    flag = next(f for f in mf if f["metric"] == "exit_cap_vs_comps")
    assert "$250,000/unit" in flag["explanation"]

    # Same comps, commercial subject -> $/SF basis stated instead.
    with session_factory() as db:
        commercial = comps_service.benchmark_flags(
            db, "Miami", "office", {"exitCapRatePct": 0.055}
        )
    flag = next(f for f in commercial if f["metric"] == "exit_cap_vs_comps")
    assert "$200/SF" in flag["explanation"]
