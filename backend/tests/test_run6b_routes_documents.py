"""Run 6b: HTTP coverage for the documents + extraction routes. A synthetic
Yardi-style rent roll (tests/extraction_corpus/builders.py) is uploaded
through /api/documents/upload; the LLM fallbacks are forced off by blanking
the API key so nothing reaches the network."""

import pytest

from app.services import document_classifier
from app.services.extraction import llm_extraction
from tests.extraction_corpus import builders

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(document_classifier, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(llm_extraction, "ANTHROPIC_API_KEY", "")


@pytest.fixture
def rent_roll_bytes(tmp_path) -> bytes:
    path = tmp_path / "maple_rent_roll.xlsx"
    builders.build_yardi_rent_roll(path)
    return path.read_bytes()


def _upload(client, name: str, content: bytes) -> dict:
    response = client.post("/api/documents/upload", files={"file": (name, content, XLSX)})
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ documents


def test_list_documents_and_heuristic_classification(client, rent_roll_bytes):
    assert client.get("/api/documents").json() == []
    doc = _upload(client, "maple_rent_roll.xlsx", rent_roll_bytes)
    assert doc["fileExt"] == "xlsx"
    assert doc["documentType"] == "rent_roll"
    assert doc["typeSource"] == "heuristic"
    assert doc["reused"] is False

    listed = client.get("/api/documents").json()
    assert [d["id"] for d in listed] == [doc["id"]]
    assert listed[0]["filename"] == "maple_rent_roll.xlsx"

    # Same bytes again dedupe onto the existing row, flagged as reused.
    again = _upload(client, "renamed.xlsx", rent_roll_bytes)
    assert again["id"] == doc["id"] and again["reused"] is True


def test_update_document_type_valid_and_invalid(client, rent_roll_bytes):
    doc = _upload(client, "rr.xlsx", rent_roll_bytes)
    updated = client.put(
        f"/api/documents/{doc['id']}/type", json={"documentType": "t12_operating_statement"}
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["documentType"] == "t12_operating_statement"
    assert body["typeSource"] == "manual"
    assert body["typeConfidence"] == 1.0
    assert "Manually" in body["typeRationale"]

    invalid = client.put(f"/api/documents/{doc['id']}/type", json={"documentType": "lease"})
    assert invalid.status_code == 422
    # Unchanged after the rejected update.
    assert client.get("/api/documents").json()[0]["documentType"] == "t12_operating_statement"
    assert client.put(
        "/api/documents/missing/type", json={"documentType": "other"}
    ).status_code == 404


def test_delete_document_and_404(client, rent_roll_bytes):
    doc = _upload(client, "rr.xlsx", rent_roll_bytes)
    assert client.delete(f"/api/documents/{doc['id']}").json() == {"deleted": True}
    assert client.get("/api/documents").json() == []
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 404
    assert client.delete("/api/documents/never-existed").status_code == 404


def test_upload_rejects_unsupported_and_legacy_extensions(client):
    legacy = client.post("/api/documents/upload", files={"file": ("old.xls", b"x", XLSX)})
    assert legacy.status_code == 400 and ".xlsx" in legacy.json()["detail"]
    other = client.post("/api/documents/upload", files={"file": ("notes.docx", b"x", XLSX)})
    assert other.status_code == 400


# ----------------------------------------------------------------- extraction


def test_extraction_round_trip_and_confirm(client, rent_roll_bytes):
    doc = _upload(client, "maple_rent_roll.xlsx", rent_roll_bytes)
    run = client.post("/api/extraction", json={"documentIds": [doc["id"]]})
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["documentIds"] == [doc["id"]]
    assert isinstance(result["fields"], dict) and result["fields"]
    assert result["confirmedValues"] == {}
    assert result["confirmedAt"] is None
    # The Yardi fixture is a multifamily roll: the unit-mix proposal is built
    # from the parsed rows and the deterministic parse needs no LLM.
    assert result["unitMixProposal"] is not None
    assert isinstance(result["warnings"], list)
    assert isinstance(result["crossValidation"], list)

    fetched = client.get(f"/api/extraction/{result['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["fields"] == result["fields"]

    confirmed = client.post(
        f"/api/extraction/{result['id']}/confirm",
        json={"confirmedValues": {"grossPotentialRent": 129_600, "dealName": "Maple"}},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["confirmedValues"] == {"grossPotentialRent": 129_600, "dealName": "Maple"}
    assert body["confirmedAt"] is not None
    # Persisted, not just echoed.
    assert client.get(f"/api/extraction/{result['id']}").json()["confirmedAt"] == body["confirmedAt"]


def test_extraction_error_paths(client, rent_roll_bytes):
    assert client.post("/api/extraction", json={"documentIds": []}).status_code == 400
    missing = client.post("/api/extraction", json={"documentIds": ["ghost"]})
    assert missing.status_code == 404
    assert "ghost" in missing.json()["detail"]

    doc = _upload(client, "rr.xlsx", rent_roll_bytes)
    partial = client.post("/api/extraction", json={"documentIds": [doc["id"], "ghost"]})
    assert partial.status_code == 404  # one unknown id fails the whole request

    assert client.get("/api/extraction/nope").status_code == 404
    assert client.post(
        "/api/extraction/nope/confirm", json={"confirmedValues": {}}
    ).status_code == 404
    assert client.post("/api/extraction", json={}).status_code == 422
