"""H5: comps database — CRUD round-trips, the two-phase CSV import (preview
writes nothing; mapping submits rows with coercion warnings), Yardi-style
header auto-mapping, and the comps-derived benchmark flags."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import RentComp, SaleComp
from app.services import comps as comps_service


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


@pytest.fixture
def client(session_factory):
    def _override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)


YARDI_SALE_CSV = """Property Name,Address,Market,Sale Date,Sale Price,# Units,RBA,Cap Rate,Year Built
Palm Court,100 Palm Ave,Miami,03/15/2026,"$12,500,000",50,"48,000",5.25%,1998
Bayview Flats,200 Bay Rd,Miami,2026-01-20,"$8,000,000",32,,4.8,2015
No Numbers Here,300 Void St,Miami,,,,,,
"""


def test_sale_comp_crud_round_trip(client):
    created = client.post(
        "/api/comps/sale",
        json={"name": "Palm Court", "market": "Miami", "price": 12_500_000, "units": 50,
              "capRatePct": 0.0525},
    ).json()
    assert created["pricePerUnit"] == pytest.approx(250_000)

    updated = client.put(
        f"/api/comps/sale/{created['id']}",
        json={"name": "Palm Court", "price": 13_000_000, "units": 50},
    ).json()
    assert updated["pricePerUnit"] == pytest.approx(260_000)
    assert updated["capRatePct"] == pytest.approx(0.0525)  # untouched

    listed = client.get("/api/comps/sale", params={"market": "mia"}).json()
    assert len(listed) == 1
    assert client.get("/api/comps/sale", params={"market": "austin"}).json() == []

    assert client.delete(f"/api/comps/sale/{created['id']}").json() == {"deleted": True}
    assert client.delete(f"/api/comps/sale/{created['id']}").status_code == 404


def test_market_search_matches_bidirectionally(client):
    """A comp stored under the more GENERAL market name ("Miami") must still
    surface when the deal searches under a more SPECIFIC name ("North
    Miami") — plain `column ILIKE '%search%'` only catches the opposite
    direction (comp contains search), silently hiding comps whenever the
    deal's own market string happens to be the more specific one."""
    client.post("/api/comps/sale", json={"name": "General Miami Comp", "market": "Miami", "price": 1})
    client.post("/api/comps/sale", json={"name": "Specific Comp", "market": "North Miami", "price": 1})
    client.post("/api/comps/sale", json={"name": "Unrelated Comp", "market": "Austin", "price": 1})

    by_specific = client.get("/api/comps/sale", params={"market": "North Miami"}).json()
    assert {c["name"] for c in by_specific} == {"General Miami Comp", "Specific Comp"}

    by_general = client.get("/api/comps/sale", params={"market": "Miami"}).json()
    assert {c["name"] for c in by_general} == {"General Miami Comp", "Specific Comp"}


def test_unknown_kind_rejected(client):
    assert client.get("/api/comps/bogus").status_code == 400


def test_yardi_headers_auto_map():
    headers, _ = comps_service.parse_csv_text(YARDI_SALE_CSV)
    mapping = comps_service.suggest_mapping(headers, "sale")
    assert mapping["name"] == "Property Name"
    assert mapping["price"] == "Sale Price"
    assert mapping["units"] == "# Units"
    assert mapping["sf"] == "RBA"
    assert mapping["capRatePct"] == "Cap Rate"
    assert mapping["saleDate"] == "Sale Date"


def test_import_preview_writes_nothing(client, session_factory):
    preview = client.post(
        "/api/comps/import", json={"kind": "sale", "csvText": YARDI_SALE_CSV}
    ).json()
    assert preview["phase"] == "preview"
    assert preview["rowCount"] == 3
    assert preview["suggestedMapping"]["price"] == "Sale Price"
    with session_factory() as db:
        assert db.query(SaleComp).count() == 0


def test_import_with_mapping_coerces_and_warns(client, session_factory):
    preview = client.post(
        "/api/comps/import", json={"kind": "sale", "csvText": YARDI_SALE_CSV}
    ).json()
    result = client.post(
        "/api/comps/import",
        json={"kind": "sale", "csvText": YARDI_SALE_CSV,
              "mapping": preview["suggestedMapping"], "defaultMarket": "Miami"},
    ).json()
    assert result["phase"] == "imported"
    assert result["imported"] == 2
    assert any("No Numbers Here" in w for w in result["warnings"])

    comps = client.get("/api/comps/sale").json()
    by_name = {c["name"]: c for c in comps}
    palm = by_name["Palm Court"]
    assert palm["price"] == pytest.approx(12_500_000)      # $ and commas stripped
    assert palm["capRatePct"] == pytest.approx(0.0525)     # "5.25%" -> fraction
    assert palm["saleDate"] == "2026-03-15"                # mm/dd/yyyy normalized
    assert palm["sf"] == pytest.approx(48_000)
    assert palm["source"] == "yardi_csv"
    bay = by_name["Bayview Flats"]
    assert bay["capRatePct"] == pytest.approx(0.048)       # bare "4.8" -> percent
    assert bay["saleDate"] == "2026-01-20"                 # ISO passthrough


def test_import_rejects_mapping_to_missing_column(client):
    response = client.post(
        "/api/comps/import",
        json={"kind": "sale", "csvText": YARDI_SALE_CSV, "mapping": {"name": "Nope"}},
    )
    assert response.status_code == 400


def test_rent_import_requires_rent():
    mapping = {"name": "Name", "avgRent": "Rent"}
    comp, warning = comps_service.coerce_row({"Name": "A", "Rent": ""}, mapping, "rent")
    assert comp is None
    assert "no average rent" in warning
    comp, _ = comps_service.coerce_row({"Name": "A", "Rent": "$2,100"}, mapping, "rent")
    assert comp["avgRent"] == pytest.approx(2_100)


# --- hygiene (I11) -----------------------------------------------------------


def test_address_normalization_and_duplicate_window(session_factory):
    from app.services.comps import find_duplicates, normalize_address

    assert normalize_address("100 Palm Avenue, Miami") == normalize_address("100 palm ave miami")
    assert normalize_address("200 W. Ocean Street") == normalize_address("200 west ocean st")
    assert normalize_address(None) == ""

    with session_factory() as db:
        db.add(SaleComp(name="Existing", market="Miami",
                        address="100 Palm Avenue", sale_date="2026-03-15", price=1))
        db.commit()
        candidates = [
            {"name": "InWindow", "address": "100 palm ave", "saleDate": "2026-03-30"},
            {"name": "OutOfWindow", "address": "100 Palm Avenue", "saleDate": "2026-06-01"},
            {"name": "OtherAddress", "address": "500 Bay Rd", "saleDate": "2026-03-15"},
            {"name": "NoDate", "address": "100 Palm Avenue"},
        ]
        duplicates = find_duplicates(db, "sale", candidates)
        assert [d["rowIndex"] for d in duplicates] == [0]
        assert duplicates[0]["existingName"] == "Existing"
        assert duplicates[0]["daysApart"] == 15


def test_import_preview_flags_duplicates_and_skip_rows(client, session_factory):
    with session_factory() as db:
        db.add(SaleComp(name="Palm Court (existing)", market="Miami",
                        address="100 Palm Ave", sale_date="2026-03-10", price=12_000_000))
        db.commit()

    preview = client.post(
        "/api/comps/import", json={"kind": "sale", "csvText": YARDI_SALE_CSV}
    ).json()
    # Palm Court's row (index 0) sells 03/15 at the same normalized address.
    assert preview["duplicates"] == [
        {"rowIndex": 0, "existingId": preview["duplicates"][0]["existingId"],
         "existingName": "Palm Court (existing)", "daysApart": 5}
    ]

    result = client.post(
        "/api/comps/import",
        json={"kind": "sale", "csvText": YARDI_SALE_CSV,
              "mapping": preview["suggestedMapping"], "skipRows": [0]},
    ).json()
    assert result["imported"] == 1  # Bayview only; Palm skipped as duplicate
    assert any("skipped as duplicates" in w for w in result["warnings"])
    names = {c["name"] for c in client.get("/api/comps/sale").json()}
    assert "Palm Court" not in names  # the CSV row never landed


def test_staleness_count_feeds_flag_note(session_factory):
    from app.services.comps import benchmark_flags

    with session_factory() as db:
        db.add(RentComp(name="Fresh", market="Miami", avg_rent=2_000, as_of="2026-06-01"))
        db.add(RentComp(name="Old1", market="Miami", avg_rent=2_000, as_of="2024-01-01"))
        db.add(RentComp(name="Old2", market="Miami", avg_rent=2_000, as_of="2023-06-01"))
        db.commit()
        flags = benchmark_flags(db, "Miami", "multifamily", {"avgRentMonthly": 2_000})
        flag = next(f for f in flags if f["metric"] == "rent_vs_comps")
        assert "2 of the comps are older than 12 months" in flag["explanation"]


def test_comps_map_skips_failed_geocodes(client, session_factory, monkeypatch):
    from app.routers import comps as comps_router  # noqa: F401
    from app.services.data_sources import geocode

    with session_factory() as db:
        db.add(SaleComp(name="Mapped", market="Miami", address="100 Palm Ave", price=1))
        db.add(SaleComp(name="Unresolvable", market="Miami", address="???", price=1))
        db.add(SaleComp(name="NoAddress", market="Miami", price=1))
        db.commit()

    def fake_geocode(market, submarket="", address=""):
        if address == "100 Palm Ave":
            return {"resolved": True, "lat": 25.77, "lon": -80.19}
        return {"resolved": False}

    monkeypatch.setattr(geocode, "geocode", fake_geocode)
    # Bypass the on-disk cache so the fake geocoder is always exercised.
    import app.routers.comps as comps_module  # noqa: F401
    from app.services.data_sources import source_cache
    monkeypatch.setattr(source_cache, "cached_fetch", lambda key, fetch, ttl_seconds=0: fetch())

    body = client.get("/api/comps/sale/map").json()
    assert [p["name"] for p in body["points"]] == ["Mapped"]
    assert body["points"][0]["lat"] == pytest.approx(25.77)
    assert len(body["warnings"]) == 2  # unresolvable + no address


def test_benchmark_flags_from_comps(session_factory):
    with session_factory() as db:
        for rent in (1_800, 2_000, 2_200):
            db.add(RentComp(name=f"R{rent}", market="Miami", avg_rent=rent,
                            property_type="Multifamily"))
        for cap in (0.052, 0.055, 0.058):
            db.add(SaleComp(name=f"S{cap}", market="Miami", cap_rate_pct=cap))
        db.commit()

        # Subject rent 30% above the $2,000 median -> warning.
        flags = comps_service.benchmark_flags(
            db, "Miami", "multifamily", {"avgRentMonthly": 2_600, "exitCapRatePct": 0.044}
        )
        by_metric = {f["metric"]: f for f in flags}
        assert by_metric["rent_vs_comps"]["verdict"] == "warning"
        assert by_metric["rent_vs_comps"]["benchmarkValue"] == pytest.approx(2_000)
        # Exit cap 110bps inside the 5.5% comps median -> warning.
        assert by_metric["exit_cap_vs_comps"]["verdict"] == "warning"


def test_benchmark_flags_match_market_bidirectionally(session_factory):
    """Comps stored under the general "Miami" market must still feed the
    benchmark flags when the DEAL's own market is the more specific
    "North Miami" — this is the actual real-world shape (comps entered
    broadly, deals addressed to a named submarket/neighborhood)."""
    with session_factory() as db:
        for rent in (1_800, 2_000, 2_200):
            db.add(RentComp(name=f"R{rent}", market="Miami", avg_rent=rent,
                            property_type="Multifamily"))
        db.commit()

        flags = comps_service.benchmark_flags(
            db, "North Miami", "multifamily", {"avgRentMonthly": 2_600}
        )
        by_metric = {f["metric"]: f for f in flags}
        assert by_metric["rent_vs_comps"]["benchmarkValue"] == pytest.approx(2_000)

        # In line -> ok verdicts.
        flags = comps_service.benchmark_flags(
            db, "Miami", "multifamily", {"avgRentMonthly": 2_000, "exitCapRatePct": 0.056}
        )
        assert all(f["verdict"] == "ok" for f in flags)

        # Below the 3-comp minimum -> silent (no anecdotal flags).
        assert comps_service.benchmark_flags(
            db, "Austin", "multifamily", {"avgRentMonthly": 2_600}
        ) == []
