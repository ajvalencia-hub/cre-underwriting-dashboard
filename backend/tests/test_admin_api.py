"""Settings admin surface: integration status flags (never values) and the
backups endpoints' wiring (the backup mechanics themselves are covered in
test_backup.py)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import backup_service


@pytest.fixture
def client():
    return TestClient(app)


def test_integration_status_flags_without_values(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "FRED_API_KEY", "super-secret-fred-key")
    monkeypatch.setattr(config, "CENSUS_API_KEY", "")
    payload = client.get("/api/admin/integrations").json()

    by_var = {row["envVar"]: row for row in payload}
    assert by_var["FRED_API_KEY"]["configured"] is True
    assert by_var["CENSUS_API_KEY"]["configured"] is False
    assert {"FRED_API_KEY", "CENSUS_API_KEY", "HUD_API_TOKEN", "BEA_API_KEY",
            "BLS_API_KEY", "ANTHROPIC_API_KEY"} <= set(by_var)
    # The secret itself must never appear anywhere in the response.
    assert "super-secret-fred-key" not in str(payload)
    assert all(set(row) == {"envVar", "label", "configured", "purpose"} for row in payload)


def test_backup_endpoints_wire_to_the_service(client, monkeypatch, tmp_path):
    calls: list[tuple] = []

    monkeypatch.setattr(
        backup_service, "perform_backup",
        lambda kind="daily", **kw: calls.append(("run", kind)) or tmp_path / "20260812T000000Z",
    )
    monkeypatch.setattr(
        backup_service, "list_backups",
        lambda **kw: {"daily": [{"name": "20260812T000000Z", "createdAt": None,
                                 "uploadCount": 0, "hasDb": True}], "weekly": []},
    )

    listing = client.get("/api/admin/backups").json()
    assert listing["daily"][0]["name"] == "20260812T000000Z"

    run = client.post("/api/admin/backups/run").json()
    assert run == {"created": "20260812T000000Z", "kind": "daily"}
    assert ("run", "daily") in calls

    def fake_restore(kind, name, **kw):
        if name == "missing":
            raise FileNotFoundError(f"No DB snapshot at {kind}/{name}")
        return {"uploads": [{"name": "om.pdf"}]}

    monkeypatch.setattr(backup_service, "restore_backup", fake_restore)
    ok = client.post("/api/admin/backups/restore",
                     json={"kind": "daily", "name": "20260812T000000Z"}).json()
    assert ok["restored"] == "daily/20260812T000000Z"
    assert ok["uploads"] == [{"name": "om.pdf"}]
    assert "Restart" in ok["note"]

    missing = client.post("/api/admin/backups/restore",
                          json={"kind": "daily", "name": "missing"})
    assert missing.status_code == 404
