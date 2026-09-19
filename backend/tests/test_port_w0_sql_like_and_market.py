"""Run 6 port (Wave 0): LIKE escaping (services/sql_like.py) and the
bidirectional comps market match (services/comps.market_matches /
market_prefilter)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import RentComp, SaleComp
from app.services import comps as comps_service
from app.services.sql_like import LIKE_ESCAPE, contains, escape_like


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


# --- sql_like ------------------------------------------------------------------

def test_escape_like_escapes_metacharacters_and_the_escape_itself():
    assert escape_like("plain") == "plain"
    assert escape_like("50%") == "50\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("c:\\x") == "c:\\\\x"
    # Backslash escaped first, so an escaped % is not double-processed.
    assert escape_like("\\%") == "\\\\\\%"
    assert contains("__") == "%\\_\\_%"
    assert LIKE_ESCAPE == "\\"


def test_contains_matches_metacharacters_literally(db):
    for name in ("100% Occupied", "Plain Name", "a_b", "axb", "back\\slash"):
        db.add(SaleComp(name=name))
    db.commit()

    def names(text):
        stmt = select(SaleComp.name).where(SaleComp.name.ilike(contains(text), escape=LIKE_ESCAPE))
        return sorted(db.execute(stmt).scalars())

    assert names("%") == ["100% Occupied"]
    assert names("__") == []
    assert names("a_b") == ["a_b"]
    assert names("\\") == ["back\\slash"]
    assert names("plain") == ["Plain Name"]


# --- market_matches -----------------------------------------------------------

@pytest.mark.parametrize(
    "comp_market, search, expected",
    [
        ("North Miami", "Miami", True),  # comp contains search
        ("Miami", "North Miami", True),  # search contains comp (the Run 6 fix)
        ("miami", "  MIAMI ", True),
        ("Austin", "Miami", False),
        ("", "Miami", False),
        (None, "Miami", False),
        ("Anything", "", True),  # blank search matches everything
        (None, "   ", True),
        ("M_ami", "Miami", False),  # `_` is literal, not a wildcard
        ("%", "Miami", False),
        ("M_ami", "M_ami", True),
    ],
)
def test_market_matches(comp_market, search, expected):
    assert comps_service.market_matches(comp_market, search) is expected


def _prefiltered(db, model, market):
    rows = db.execute(comps_service.market_prefilter(select(model), model, market)).scalars()
    return [r for r in rows if comps_service.market_matches(r.market, market)]


def test_market_prefilter_is_a_superset_and_bidirectional(db):
    for name, market in [
        ("General", "Miami"), ("Specific", "North Miami"), ("Unrelated", "Austin"),
        ("Wild", "%"), ("Under", "M_ami"),
    ]:
        db.add(SaleComp(name=name, market=market))
    db.commit()

    def names(market):
        return sorted(c.name for c in _prefiltered(db, SaleComp, market))

    assert names("North Miami") == ["General", "Specific"]
    assert names("Miami") == ["General", "Specific"]
    assert names("M_ami") == ["Under"]
    assert names("%") == ["Wild"]
    assert names("") == ["General", "Specific", "Under", "Unrelated", "Wild"]
    # Every row market_matches accepts survives the SQL prefilter.
    all_rows = db.execute(select(SaleComp)).scalars().all()
    for search in ("Miami", "North Miami", "M_ami", "%", "austin"):
        prefiltered = {
            c.id for c in db.execute(
                comps_service.market_prefilter(select(SaleComp), SaleComp, search)
            ).scalars()
        }
        expected = {c.id for c in all_rows if comps_service.market_matches(c.market, search)}
        assert expected <= prefiltered


def test_benchmark_flags_match_market_bidirectionally(db):
    """Comps stored under the general "Miami" market must still feed the
    benchmark flags when the DEAL's own market is the more specific
    "North Miami"."""
    for rent in (1_800, 2_000, 2_200):
        db.add(RentComp(name=f"R{rent}", market="Miami", avg_rent=rent, property_type="Multifamily"))
    db.commit()

    flags = comps_service.benchmark_flags(
        db, "North Miami", "multifamily", {"avgRentMonthly": 2_600}
    )
    by_metric = {f["metric"]: f for f in flags}
    assert by_metric["rent_vs_comps"]["benchmarkValue"] == pytest.approx(2_000)
    # And an unrelated market still sees nothing.
    assert comps_service.benchmark_flags(db, "Austin", "multifamily", {"avgRentMonthly": 2_600}) == []
