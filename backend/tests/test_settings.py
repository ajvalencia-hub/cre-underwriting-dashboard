"""M1: DB-backed settings — precedence layering, secret masking, revert,
catalog completeness. Uses an isolated in-memory engine (same pattern as
test_agent_router.py's `client` fixture) so writes never touch the real
dev database; settings.py opens its own SessionLocal() rather than a
request-scoped Depends(get_db) session, so SessionLocal itself is what
gets monkeypatched here."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.database import Base
from app.main import app
from app.services import settings as settings_service


@pytest.fixture
def isolated_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(settings_service, "SessionLocal", TestSession)
    yield TestSession
    engine.dispose()


@pytest.fixture
def client(isolated_db):
    return TestClient(app)


# ----------------------------------------------------------------------
# Precedence layering
# ----------------------------------------------------------------------

def test_resolves_catalog_default_when_nothing_else_set(isolated_db):
    value, source = settings_service.resolve_setting("maxUploadBytes")
    assert source == "default"
    assert value == settings_service.SETTINGS_CATALOG["maxUploadBytes"].default


def test_resolves_env_config_value_when_no_db_row(isolated_db, monkeypatch):
    monkeypatch.setattr(config, "FIRM_NAME", "Test Firm From Env")
    value, source = settings_service.resolve_setting("firmName")
    assert source == "env"
    assert value == "Test Firm From Env"


def test_db_row_wins_over_env(isolated_db, monkeypatch):
    monkeypatch.setattr(config, "FIRM_NAME", "Env Firm")
    settings_service.set_setting("firmName", "DB Firm")
    value, source = settings_service.resolve_setting("firmName")
    assert source == "db"
    assert value == "DB Firm"


def test_unknown_key_raises_keyerror(isolated_db):
    with pytest.raises(KeyError):
        settings_service.resolve_setting("notARealSetting")


# ----------------------------------------------------------------------
# Secret masking
# ----------------------------------------------------------------------

def test_mask_returns_isset_and_last4_for_secret():
    assert settings_service.mask("sk-ant-abc12345", is_secret=True) == {
        "isSet": True, "last4": "2345",
    }


def test_mask_returns_unset_for_empty_secret():
    assert settings_service.mask("", is_secret=True) == {"isSet": False, "last4": None}


def test_mask_returns_raw_value_for_non_secret():
    assert settings_service.mask("Acme Partners", is_secret=False) == {"value": "Acme Partners"}


def test_get_setting_entry_never_includes_raw_secret_value(isolated_db):
    settings_service.set_setting("anthropicApiKey", "sk-ant-super-secret-value")
    entry = settings_service.get_setting_entry("anthropicApiKey")
    assert entry["isSet"] is True
    assert entry["last4"] == "alue"
    assert "sk-ant-super-secret-value" not in json.dumps(entry)


def test_list_settings_never_includes_any_raw_secret_value(isolated_db):
    settings_service.set_setting("anthropicApiKey", "sk-ant-secret-one")
    settings_service.set_setting("openaiApiKey", "sk-secret-two")
    dumped = json.dumps(settings_service.list_settings())
    assert "sk-ant-secret-one" not in dumped
    assert "sk-secret-two" not in dumped


# ----------------------------------------------------------------------
# Set / delete (revert)
# ----------------------------------------------------------------------

def test_set_then_delete_reverts_to_default(isolated_db):
    settings_service.set_setting("firmName", "Custom Firm")
    assert settings_service.resolve_setting("firmName")[1] == "db"
    settings_service.delete_setting("firmName")
    value, source = settings_service.resolve_setting("firmName")
    assert source in ("env", "default")
    assert value != "Custom Firm"


def test_delete_unset_key_is_a_no_op(isolated_db):
    settings_service.delete_setting("firmName")  # never set — must not raise


def test_set_unknown_key_raises_keyerror(isolated_db):
    with pytest.raises(KeyError):
        settings_service.set_setting("notARealSetting", "x")


# ----------------------------------------------------------------------
# Catalog completeness
# ----------------------------------------------------------------------

def test_every_catalog_key_appears_in_list_settings(isolated_db):
    listed_keys = {entry["key"] for entry in settings_service.list_settings()}
    assert listed_keys == set(settings_service.SETTINGS_CATALOG)


# ----------------------------------------------------------------------
# HTTP surface
# ----------------------------------------------------------------------

def test_get_list_returns_every_catalog_entry(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    keys = {entry["key"] for entry in resp.json()}
    assert keys == set(settings_service.SETTINGS_CATALOG)


def test_get_unknown_key_is_404(client):
    resp = client.get("/api/settings/notARealSetting")
    assert resp.status_code == 404


def test_put_then_get_round_trips_non_secret(client):
    resp = client.put("/api/settings/firmName", json={"value": "New Firm Name"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "New Firm Name"
    assert resp.json()["source"] == "db"


def test_put_secret_then_get_never_returns_raw_value(client):
    resp = client.put("/api/settings/anthropicApiKey", json={"value": "sk-ant-real-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["isSet"] is True
    assert body["last4"] == "cret"
    assert "sk-ant-real-secret" not in json.dumps(body)


def test_delete_reverts_via_router(client):
    client.put("/api/settings/firmName", json={"value": "Temp Name"})
    resp = client.delete("/api/settings/firmName")
    assert resp.status_code == 200
    assert resp.json()["source"] in ("env", "default")


def test_put_unknown_key_is_404(client):
    resp = client.put("/api/settings/notARealSetting", json={"value": "x"})
    assert resp.status_code == 404


def test_delete_unknown_key_is_404(client):
    resp = client.delete("/api/settings/notARealSetting")
    assert resp.status_code == 404
