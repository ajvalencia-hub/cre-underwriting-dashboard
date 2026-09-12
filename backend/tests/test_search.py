"""J13: global search endpoint — grouping, prefix>substring ranking, the
tenant scan over lease rolls, and the LIKE-index migration."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, run_migrations
from app.main import app
from app.models import SaleComp


def test_short_query_returns_nothing(client):
    assert client.get("/api/search?q=a").json()["groups"] == []


def test_groups_deals_tenants_comps_notes(client):
    riverside = client.post("/api/deals", json={"name": "Riverside Apartments"}).json()
    client.put(f"/api/deals/{riverside['id']}", json={"inputs": {
        "dealName": "Riverside Apartments", "market": "Austin",
        "commercialLeases": [{"tenant": "Riverside Cafe", "sf": 1200}],
    }})
    client.post(f"/api/deals/{riverside['id']}/notes", json={"body": "Riverside seller wants Q3 close"})

    db = client._session()  # type: ignore[attr-defined]
    db.add(SaleComp(name="Riverside Trade Center", address="9 Riverside Dr", market="Austin"))
    db.commit()
    db.close()

    groups = {g["kind"]: g["items"] for g in client.get("/api/search?q=riverside").json()["groups"]}
    assert "deals" in groups and groups["deals"][0]["title"] == "Riverside Apartments"
    assert groups["deals"][0]["dealId"] == riverside["id"]
    assert "tenants" in groups and groups["tenants"][0]["title"] == "Riverside Cafe"
    assert groups["tenants"][0]["dealId"] == riverside["id"]  # tenants deep-link to the deal
    assert "comps" in groups and "Riverside Trade Center" in groups["comps"][0]["title"]
    assert "notes" in groups and "Riverside" in groups["notes"][0]["title"]


def test_prefix_ranks_above_substring(client):
    for name in ("Oak Ridge", "Grand Oaks", "Oakwood Flats"):
        client.post("/api/deals", json={"name": name})
    titles = [
        item["title"]
        for group in client.get("/api/search?q=oak").json()["groups"]
        if group["kind"] == "deals"
        for item in group["items"]
    ]
    # "Oak Ridge" and "Oakwood Flats" start with "oak" -> rank above the
    # substring match "Grand Oaks"; ties broken alphabetically.
    assert titles == ["Oak Ridge", "Oakwood Flats", "Grand Oaks"]


def test_deal_matches_on_address_and_market(client):
    deal = client.post("/api/deals", json={"name": "Untitled"}).json()
    client.put(f"/api/deals/{deal['id']}", json={"inputs": {
        "dealName": "Untitled", "address": "500 Biscayne Blvd", "market": "Miami",
    }})
    by_addr = client.get("/api/search?q=biscayne").json()["groups"]
    by_market = client.get("/api/search?q=miami").json()["groups"]
    assert by_addr and by_addr[0]["items"][0]["dealId"] == deal["id"]
    assert by_market and by_market[0]["items"][0]["dealId"] == deal["id"]


def test_deal_type_facet_and_badges(client):
    riverside_acq = client.post("/api/deals", json={"name": "Riverside Acq"}).json()
    client.put(f"/api/deals/{riverside_acq['id']}", json={"inputs": {
        "dealType": "acquisition",
        "commercialLeases": [{"tenant": "Riverside Books", "sf": 900}],
    }})
    riverside_dev = client.post("/api/deals", json={"name": "Riverside Dev"}).json()
    client.put(f"/api/deals/{riverside_dev['id']}", json={"inputs": {"dealType": "development"}})
    client.post(f"/api/deals/{riverside_dev['id']}/notes", json={"body": "Riverside permits filed"})

    db = client._session()  # type: ignore[attr-defined]
    db.add(SaleComp(name="Riverside Comp", market="Austin"))
    db.commit()
    db.close()

    # Unfaceted: every item in a deal-scoped group carries its dealType.
    plain = client.get("/api/search?q=riverside").json()
    assert plain["typeFilter"] is None
    groups = {g["kind"]: g["items"] for g in plain["groups"]}
    assert {d["title"]: d["dealType"] for d in groups["deals"]} == {
        "Riverside Acq": "acquisition", "Riverside Dev": "development",
    }
    assert groups["tenants"][0]["dealType"] == "acquisition"
    assert groups["notes"][0]["dealType"] == "development"

    # acq: facet — only acquisition-scoped hits; global comps drop out.
    acq = client.get("/api/search?q=acq:riverside").json()
    assert acq["typeFilter"] == "acquisition"
    acq_groups = {g["kind"]: g["items"] for g in acq["groups"]}
    assert [d["title"] for d in acq_groups["deals"]] == ["Riverside Acq"]
    assert "notes" not in acq_groups  # the note belongs to the dev deal
    assert "comps" not in acq_groups

    # dev: facet mirrors.
    dev = client.get("/api/search?q=dev:riverside").json()
    dev_groups = {g["kind"]: g["items"] for g in dev["groups"]}
    assert [d["title"] for d in dev_groups["deals"]] == ["Riverside Dev"]
    assert "tenants" not in dev_groups

    # A bare prefix with a too-short remainder returns nothing, not junk.
    assert client.get("/api/search?q=acq:r").json()["groups"] == []


def test_migration_creates_indexes():
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(db_engine)
    run_migrations(db_engine)
    inspector = inspect(db_engine)
    deal_indexes = {ix["name"] for ix in inspector.get_indexes("deals")}
    comp_indexes = {ix["name"] for ix in inspector.get_indexes("sale_comps")}
    assert "ix_deals_name" in deal_indexes
    assert {"ix_sale_comps_address", "ix_sale_comps_name"} <= comp_indexes
    # Idempotent — a second run must not raise.
    run_migrations(db_engine)
    db_engine.dispose()
