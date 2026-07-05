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

        # In line -> ok verdicts.
        flags = comps_service.benchmark_flags(
            db, "Miami", "multifamily", {"avgRentMonthly": 2_000, "exitCapRatePct": 0.056}
        )
        assert all(f["verdict"] == "ok" for f in flags)

        # Below the 3-comp minimum -> silent (no anecdotal flags).
        assert comps_service.benchmark_flags(
            db, "Austin", "multifamily", {"avgRentMonthly": 2_600}
        ) == []
