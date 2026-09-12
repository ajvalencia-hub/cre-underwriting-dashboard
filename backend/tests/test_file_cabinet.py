"""J12: deal file cabinet (attachments) + notes timeline + bundle listing."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.routers import upload_limit


def _deal(client) -> str:
    return client.post("/api/deals", json={"name": "Cabinet Deal"}).json()["id"]


def test_upload_list_download_any_type(client):
    deal_id = _deal(client)
    resp = client.post(
        f"/api/deals/{deal_id}/attachments",
        files={"file": ("site_photo.png", b"\x89PNG fakebytes", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    att = resp.json()
    assert att["source"] == "attachment"
    assert att["fileExt"] == "png"
    assert att["sizeBytes"] == len(b"\x89PNG fakebytes")

    # Any extension is allowed — the cabinet is storage, not a parser input.
    docx = client.post(
        f"/api/deals/{deal_id}/attachments",
        files={"file": ("loi.docx", b"word bytes", "application/octet-stream")},
    )
    assert docx.status_code == 200

    listed = client.get(f"/api/deals/{deal_id}/attachments").json()
    assert {a["filename"] for a in listed} == {"site_photo.png", "loi.docx"}

    download = client.get(
        f"/api/deals/{deal_id}/attachments/{att['id']}/download"
    )
    assert download.status_code == 200
    assert download.content == b"\x89PNG fakebytes"
    # Non-PDFs return a typed no-preview, never an error.
    preview = client.get(
        f"/api/deals/{deal_id}/attachments/{att['id']}/preview"
    ).json()
    assert preview["kind"] == "none"


def test_size_cap_applies(client, monkeypatch):
    deal_id = _deal(client)
    monkeypatch.setattr(upload_limit, "MAX_UPLOAD_BYTES", 64)
    resp = client.post(
        f"/api/deals/{deal_id}/attachments",
        files={"file": ("big.bin", b"x" * 256, "application/octet-stream")},
    )
    assert resp.status_code == 413


def test_notes_crud_timeline(client):
    deal_id = _deal(client)
    created = client.post(
        f"/api/deals/{deal_id}/notes", json={"body": "**Seller** wants a quick close"}
    ).json()
    assert created["body"].startswith("**Seller**")

    updated = client.put(
        f"/api/deals/{deal_id}/notes/{created['id']}", json={"body": "revised terms"}
    ).json()
    assert updated["body"] == "revised terms"

    second = client.post(f"/api/deals/{deal_id}/notes", json={"body": "call broker"}).json()
    listing = client.get(f"/api/deals/{deal_id}/notes").json()
    assert [n["id"] for n in listing] == [second["id"], created["id"]]  # newest first

    assert client.post(f"/api/deals/{deal_id}/notes", json={"body": "   "}).status_code == 400
    assert client.delete(f"/api/deals/{deal_id}/notes/{created['id']}").json() == {"deleted": True}
    assert len(client.get(f"/api/deals/{deal_id}/notes").json()) == 1
    # Notes are deal-scoped: a different deal can't touch them.
    other = _deal(client)
    assert client.delete(f"/api/deals/{other}/notes/{second['id']}").status_code == 404


def test_bundle_lists_attachments_by_hash_and_carries_notes(client):
    deal_id = _deal(client)
    client.post(f"/api/deals/{deal_id}/notes", json={"body": "bundle me"})
    att = client.post(
        f"/api/deals/{deal_id}/attachments",
        files={"file": ("om.pdf", b"pdf bytes", "application/pdf")},
    ).json()

    bundle = client.get(f"/api/deals/{deal_id}/export").json()
    assert bundle["notes"][0]["body"] == "bundle me"
    # Attachments are LISTED by name/hash, never embedded.
    assert bundle["attachments"] == [
        {"filename": "om.pdf", "fileHash": att["fileHash"], "fileExt": "pdf"}
    ]
    assert "content" not in str(bundle["attachments"])

    imported = client.post("/api/deals/import", json={"bundle": bundle}).json()
    assert imported["importedNotes"] == 1
    assert any("not embedded" in w for w in imported["importWarnings"])
    notes = client.get(f"/api/deals/{imported['id']}/notes").json()
    assert notes[0]["body"] == "bundle me"
    # ...and the imported deal has no attachments (files weren't bundled).
    assert client.get(f"/api/deals/{imported['id']}/attachments").json() == []
