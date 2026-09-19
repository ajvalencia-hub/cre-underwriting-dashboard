"""Run 6b: HTTP coverage for the small read-only / sink routes (schema,
property-tax counties, preset fields, client-error sink, portfolio CSV
export) and an admin backup -> restore round trip against a REAL snapshot
on a scratch backups root."""

import csv
import io
import json
import sqlite3
from pathlib import Path

from app.routers import client_errors
from app.services import backup_service
from app.services.presets import PRESET_FIELD_IDS

FIXTURES = Path(__file__).parent / "fixtures"


def analytic(**overrides) -> dict:
    deal = json.loads((FIXTURES / "analytic_acquisition.json").read_text())
    deal.update(overrides)
    return deal


# --------------------------------------------------------------------- schema


def test_schema_exposes_deal_stages_and_field_registry(client):
    response = client.get("/api/schema")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["dealStages"]) == {"acquisition", "development"}
    assert schema["dealStages"]["acquisition"][0] == "screening"
    assert "dead" in schema["dealStages"]["development"]
    field_ids = {f["id"] for section in schema["sections"] for f in section["fields"]}
    assert {"purchasePrice", "exitCapRatePct", "grossPotentialRent"} <= field_ids
    assert {o["id"] for o in schema["outputs"]} >= {"leveredIrr", "equityMultiple"}
    assert "version" in schema


# --------------------------------------------------------- property tax / presets


def test_property_tax_counties(client):
    response = client.get("/api/property-tax/counties")
    assert response.status_code == 200
    rows = response.json()
    assert rows and all(set(row) == {"id", "label"} for row in rows)
    assert "miami_dade" in {row["id"] for row in rows}


def test_preset_fields_match_the_service_whitelist(client):
    response = client.get("/api/presets/fields")
    assert response.status_code == 200
    assert response.json() == PRESET_FIELD_IDS
    assert "vacancyPct" in response.json()


# -------------------------------------------------------------- client errors


def test_client_errors_sink_logs_and_truncates(client, monkeypatch):
    captured: list[tuple] = []
    monkeypatch.setattr(
        client_errors.logger, "warning", lambda fmt, *args: captured.append(args)
    )
    long_stack = "x" * 10_000
    response = client.post(
        "/api/client-errors",
        json={"message": "boom", "stack": long_stack, "url": "http://localhost/deals"},
    )
    assert response.status_code == 200
    assert response.json() == {"logged": True}
    assert len(captured) == 1
    url, message, stack, components = captured[0]
    assert url == "http://localhost/deals" and message == "boom"
    assert len(stack) == client_errors._MAX_FIELD  # bounded diagnostics channel
    assert components == ""

    assert client.post("/api/client-errors", json={"stack": "no message"}).status_code == 422


# ------------------------------------------------------------------ portfolio


def test_portfolio_csv_export_has_header_totals_and_excluded(client):
    client.post("/api/deals", json={"name": "Live One", "inputs": analytic(market="Austin")})
    client.post("/api/deals", json={"name": "Sparse", "inputs": {"dealName": "Sparse"}})
    dead = client.post("/api/deals", json={"name": "Dead", "inputs": analytic()}).json()
    client.put(f"/api/deals/{dead['id']}", json={"status": "dead"})

    response = client.get("/api/portfolio/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="portfolio.csv"' in response.headers["content-disposition"]

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["Deal", "Type", "Status", "Market", "Asset class", "Equity",
                       "Levered IRR", "Equity multiple"]
    assert rows[1][0] == "Live One" and rows[1][3] == "Austin"
    assert rows[1][5] == "400000"
    assert float(rows[1][6]) > 0.11  # levered IRR ~11.57%
    assert rows[2] == []  # blank spacer before the totals footer
    totals = rows[3]
    assert totals[0] == "PORTFOLIO" and totals[5] == "400000"
    assert float(totals[6]) == float(rows[1][6])  # single deal -> blend equals it
    excluded = rows[4]
    assert excluded[0] == "Sparse" and excluded[2] == "EXCLUDED"
    assert excluded[3].startswith("missing inputs")
    names = {row[0] for row in rows[1:] if row}
    assert "Dead" not in names  # dead deals leave the roll-up entirely


def test_portfolio_csv_export_empty(client):
    rows = list(csv.reader(io.StringIO(client.get("/api/portfolio/export.csv").text)))
    assert rows[0][0] == "Deal"
    assert rows[1] == []
    assert rows[2][0] == "PORTFOLIO" and rows[2][5] == "0"
    assert rows[2][6] == "" and rows[2][7] == ""  # no blend without deals


# ------------------------------------------------------------- admin restore


def _make_db(path: Path, deal_name: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO deals (name) VALUES (?)", (deal_name,))
    conn.commit()
    conn.close()


def _deal_name(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT name FROM deals").fetchone()[0]
    finally:
        conn.close()


def test_admin_backup_then_restore_real_snapshot(client, tmp_path, monkeypatch):
    live = tmp_path / "live.sqlite3"
    _make_db(live, "Original")
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup_service, "DB_PATH", live)

    run = client.post("/api/admin/backups/run")
    assert run.status_code == 200, run.text
    created = run.json()["created"]
    assert run.json()["kind"] == "daily"
    assert (tmp_path / "backups" / "daily" / created / "app.sqlite3").exists()

    listing = client.get("/api/admin/backups").json()
    assert [s["name"] for s in listing["daily"]] == [created]
    assert listing["daily"][0]["hasDb"] is True
    assert listing["weekly"] == []

    # Mutate the live DB, then restore the snapshot over it.
    conn = sqlite3.connect(str(live))
    conn.execute("UPDATE deals SET name = 'Changed'")
    conn.commit()
    conn.close()
    assert _deal_name(live) == "Changed"

    restored = client.post("/api/admin/backups/restore", json={"kind": "daily", "name": created})
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["restored"] == f"daily/{created}"
    # The manifest lists whatever the (session-shared) scratch storage root
    # holds — other test modules upload templates/documents there, so only
    # the shape is order-independent.
    assert isinstance(body["uploads"], list)
    assert all({"dir", "name", "sizeBytes"} <= set(u) for u in body["uploads"])
    assert "Restart the backend" in body["note"]
    assert _deal_name(live) == "Original"

    # Well-formed but absent snapshot -> 404; malformed -> 400; live DB untouched.
    assert client.post(
        "/api/admin/backups/restore", json={"kind": "daily", "name": "20200101T000000Z"}
    ).status_code == 404
    assert client.post(
        "/api/admin/backups/restore", json={"kind": "daily", "name": "../x"}
    ).status_code == 400
    assert client.post(
        "/api/admin/backups/restore", json={"kind": "monthly", "name": created}
    ).status_code == 400
    assert _deal_name(live) == "Original"
