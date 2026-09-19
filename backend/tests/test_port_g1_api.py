"""Run 6 API/security port — target-specific behaviour not covered by the
ported Run 6 test files: backup download over every snapshot kind, the PUT
order 404 -> 412 -> IC 409 -> write, tags while IC-locked, the finalize-draft
IC lock, soffice timeouts, external-route 429s, OPENAI_API_KEY in
/integrations, irrDiagnostics pass-through and the image build context."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from app import config
from app.models import Document, ExtractionResult
from app.services import backup_service, compute_cache, rate_limit, soffice
from app.services.data_sources import fred

_REPO = Path(__file__).resolve().parents[2]
_DEAL = json.loads((Path(__file__).parent / "fixtures" / "analytic_acquisition.json").read_text())
_DEAL.pop("_comment", None)


def _submit(client, deal_id):
    response = client.post(
        f"/api/deals/{deal_id}/ic/events", json={"kind": "submit", "actor": "Ana", "comment": "Base"}
    )
    assert response.status_code == 200, response.text


# --- backup download ---------------------------------------------------------

@pytest.fixture
def backups(tmp_path, monkeypatch):
    live = tmp_path / "live.sqlite3"
    conn = sqlite3.connect(str(live))
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup_service, "DB_PATH", live)
    return tmp_path


def test_download_returns_the_snapshot_db(client, backups):
    created = client.post("/api/admin/backups/run").json()["created"]
    res = client.get(f"/api/admin/backups/daily/{created}/download")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/vnd.sqlite3")
    assert f"cre-backup-daily-{created}.sqlite3" in res.headers["content-disposition"]
    assert res.content[:16] == b"SQLite format 3\x00"
    # Well-formed but absent -> 404.
    assert client.get("/api/admin/backups/daily/20200101T000000Z/download").status_code == 404


@pytest.mark.parametrize("kind", ["pre_restore", "pre_migration", "weekly"])
def test_download_covers_every_snapshot_kind(client, backups, kind):
    snap = backup_service.perform_backup(kind, backups_root=backups / "backups")
    res = client.get(f"/api/admin/backups/{kind}/{snap.name}/download")
    assert res.status_code == 200
    assert res.content[:16] == b"SQLite format 3\x00"


@pytest.mark.parametrize("kind,name", [
    ("daily", ".."), ("daily", "nope"), ("monthly", "20260101T000000Z"),
    ("daily", "20260101T000000Z..x"),
])
def test_download_rejects_malformed_kind_or_name(client, backups, kind, name):
    assert client.get(f"/api/admin/backups/{kind}/{name}/download").status_code in (400, 404)
    with pytest.raises(ValueError):
        backup_service.snapshot_path(kind, name, backups_root=backups / "backups")


def test_snapshot_path_stays_inside_the_root(tmp_path):
    root = tmp_path / "backups"
    (root / "daily" / "20260101T000000Z_1").mkdir(parents=True)
    resolved = backup_service.snapshot_path("daily", "20260101T000000Z_1", backups_root=root)
    assert resolved == (root / "daily" / "20260101T000000Z_1").resolve()


# --- ETag / If-Match order and tags under the IC lock --------------------------

def test_stale_if_match_is_412_before_the_ic_lock_409(client):
    deal_id = client.post("/api/deals", json={"name": "Locked", "inputs": dict(_DEAL)}).json()["id"]
    etag = client.get(f"/api/deals/{deal_id}").headers["ETag"]
    _submit(client, deal_id)  # the lock does not touch the deal row...
    changed = {**_DEAL, "purchasePrice": 1}

    stale = client.put(f"/api/deals/{deal_id}", json={"inputs": changed}, headers={"If-Match": '"nope"'})
    assert stale.status_code == 412
    assert stale.json()["current"]["id"] == deal_id
    # ...so a matching tag gets past the 412 and hits the IC lock.
    locked = client.put(f"/api/deals/{deal_id}", json={"inputs": changed}, headers={"If-Match": etag})
    assert locked.status_code == 409
    assert client.put("/api/deals/nope", json={"inputs": {}}, headers={"If-Match": '"x"'}).status_code == 404


def test_tags_and_archive_are_allowed_while_ic_locked(client):
    deal_id = client.post("/api/deals", json={"name": "Locked", "inputs": dict(_DEAL)}).json()["id"]
    _submit(client, deal_id)
    tagged = client.put(f"/api/deals/{deal_id}", json={"tags": ["IC", "q3"]})
    assert tagged.status_code == 200
    assert tagged.json()["tags"] == ["IC", "q3"]
    bulk = client.post("/api/deals/bulk-tags", json={"dealIds": [deal_id], "add": ["core"]})
    assert bulk.status_code == 200
    assert bulk.json()["updated"][0]["tags"] == ["IC", "q3", "core"]
    assert client.post(f"/api/deals/{deal_id}/archive").status_code == 200


def test_finalizing_a_locked_draft_from_extraction_is_409(client):
    deal_id = client.post("/api/deals", json={"name": "Draft", "inputs": dict(_DEAL)}).json()["id"]
    _submit(client, deal_id)
    with client._session() as db:
        stored = ExtractionResult(fields={}, cross_validation=[])
        db.add(stored)
        db.commit()
        extraction_id = stored.id
    response = client.post("/api/deals/from-extraction", json={
        "name": "Draft", "extractionResultId": extraction_id,
        "confirmedValues": {"purchasePrice": 1}, "dealId": deal_id,
    })
    assert response.status_code == 409
    assert client.get(f"/api/deals/{deal_id}").json()["inputs"]["purchasePrice"] == _DEAL["purchasePrice"]


def test_import_carries_an_etag_and_warns_on_junk_tags(client):
    source = client.post("/api/deals", json={"name": "Src"}).json()["id"]
    bundle = client.get(f"/api/deals/{source}/export").json()
    assert bundle["schemaVersion"] == 1 and bundle["deal"]["tags"] == []
    bundle["deal"]["tags"] = ["ok", 7, "ok "]
    res = client.post("/api/deals/import", json={"bundle": bundle})
    assert res.status_code == 200
    assert res.headers.get("ETag")
    assert res.json()["tags"] == ["ok"]
    assert any("weren't text" in w for w in res.json()["importWarnings"])


# --- file cabinet: provenance lists global documents only ------------------------

def test_provenance_badge_lists_global_documents_only(client, tmp_path):
    other = client.post("/api/deals", json={"name": "Other"}).json()["id"]
    with client._session() as db:
        for deal_id in (other, None):
            db.add(Document(
                filename="om.pdf", file_hash=f"h-{deal_id}", stored_path=str(tmp_path / "x.pdf"),
                file_ext="pdf", document_type="om", type_confidence=1.0, type_source="manual",
                type_rationale="", deal_id=deal_id,
            ))
        db.commit()
    deal_id = client.post("/api/deals", json={"name": "Mine", "inputs": {
        "_provenance": {"purchasePrice": {"sourceRef": {"doc": "om.pdf"}}},
    }}).json()["id"]
    rows = client.get(f"/api/deals/{deal_id}/attachments").json()
    assert [r["fileHash"] for r in rows] == ["h-None"]
    assert rows[0]["source"] == "extraction"


# --- soffice timeout --------------------------------------------------------------

def test_soffice_timeout_is_a_runtime_error_and_cleans_scratch(tmp_path, monkeypatch):
    src = tmp_path / "book.xlsx"
    src.write_bytes(b"x")
    monkeypatch.setattr(soffice, "is_available", lambda: True)
    monkeypatch.setattr(soffice, "_RETRY_DELAY_SECONDS", 0)

    def hang(cmd, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(soffice.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="timed out"):
        soffice.convert_file(src, "xlsx", timeout=1)
    assert not list(tmp_path.glob(".so-*"))


# --- external-route rate limiting --------------------------------------------------

def test_market_rates_429s_past_the_limit_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(config, "CRE_EXTERNAL_RATE_LIMIT_PER_MIN", 1)
    monkeypatch.setattr(fred, "get_market_rates", lambda: {"dataSource": "stub", "rates": {}})
    rate_limit.reset()
    try:
        assert client.get("/api/market/rates").status_code == 200
        blocked = client.get("/api/market/rates")
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        # Buckets are per route: another external route is unaffected.
        assert client.get("/api/demographics").status_code == 400  # validation, not 429
    finally:
        rate_limit.reset()


# --- admin integrations ---------------------------------------------------------------

def test_integrations_lists_the_agent_openai_key_as_a_flag_only(client, monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-secret-value")
    rows = {r["envVar"]: r for r in client.get("/api/admin/integrations").json()}
    assert rows["OPENAI_API_KEY"]["configured"] is True
    assert "sk-secret-value" not in json.dumps(rows)


# --- compute: conditional irrDiagnostics ------------------------------------------------

def test_compute_passes_irr_diagnostics_through_when_present(client, monkeypatch):
    base = {
        "outputs": {"leveredIrr": 0.1}, "warnings": [], "debt": None,
        "irrConvention": "periodic_monthly", "waterfallStyle": "european",
    }
    monkeypatch.setattr(compute_cache, "cached_compute", lambda values: dict(base))
    assert "irrDiagnostics" not in client.post("/api/compute", json={"values": {}}).json()

    diag = {"roots": [0.05, 0.4], "reported": 0.05}
    monkeypatch.setattr(compute_cache, "cached_compute", lambda values: {**base, "irrDiagnostics": diag})
    assert client.post("/api/compute", json={"values": {}}).json()["irrDiagnostics"] == diag


# --- image build context --------------------------------------------------------------

def test_dockerignore_keeps_local_secrets_out_of_the_image():
    lines = (_REPO / ".dockerignore").read_text().splitlines()
    assert "**/.env" in lines and "**/.env.*" in lines
    assert "!**/.env.example" in lines
    compose = (_REPO / "docker-compose.yml").read_text()
    assert "CRE_API_TOKEN: ${CRE_API_TOKEN:-}" in compose
