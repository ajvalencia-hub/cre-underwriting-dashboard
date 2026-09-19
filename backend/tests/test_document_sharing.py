"""Uploads are stored by content hash, so one file on disk can back several
records: a Documents-tab upload and attachments on any number of deals.
Deleting one record used to delete the shared file (another deal's
attachment then 404'd), and a later upload of that file failed with a 500
because the reuse lookup expected at most one row per hash."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.routers import documents, file_cabinet

PDF = b"%PDF-1.4 shared offering memorandum bytes"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "DOCUMENTS_DIR", tmp_path)
    monkeypatch.setattr(file_cabinet, "DOCUMENTS_DIR", tmp_path)
    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    TestSession = sessionmaker(bind=db_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    db_engine.dispose()


def _deal(client, name):
    return client.post("/api/deals", json={"name": name}).json()["id"]


def _attach(client, deal_id):
    response = client.post(f"/api/deals/{deal_id}/attachments", files={"file": ("om.pdf", PDF, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_deleting_one_record_keeps_a_file_other_records_use(client):
    deal_a, deal_b = _deal(client, "A"), _deal(client, "B")
    att_a, att_b = _attach(client, deal_a), _attach(client, deal_b)

    assert client.delete(f"/api/documents/{att_a}").status_code == 200
    download = client.get(f"/api/deals/{deal_b}/attachments/{att_b}/download")
    assert download.status_code == 200 and download.content == PDF

    # The last record going removes the file.
    assert client.delete(f"/api/documents/{att_b}").status_code == 200
    assert list(documents.DOCUMENTS_DIR.iterdir()) == []


def test_uploading_a_file_that_is_already_attached_twice_works(client):
    _attach(client, _deal(client, "A"))
    _attach(client, _deal(client, "B"))
    response = client.post("/api/documents/upload", files={"file": ("om.pdf", PDF, "application/pdf")})
    assert response.status_code == 200, response.text
    # A deal's attachment isn't handed back as a general document.
    assert response.json()["reused"] is False


def test_reupload_restores_a_file_missing_from_disk(client):
    first = client.post("/api/documents/upload", files={"file": ("om.pdf", PDF, "application/pdf")}).json()
    for path in documents.DOCUMENTS_DIR.iterdir():
        path.unlink()
    again = client.post("/api/documents/upload", files={"file": ("om.pdf", PDF, "application/pdf")})
    assert again.json()["id"] == first["id"]
    assert [p.read_bytes() for p in documents.DOCUMENTS_DIR.iterdir()] == [PDF]


def test_deleting_a_deal_keeps_a_file_a_general_document_uses(client):
    deal = _deal(client, "A")
    _attach(client, deal)
    doc = client.post("/api/documents/upload", files={"file": ("om.pdf", PDF, "application/pdf")}).json()
    assert client.delete(f"/api/deals/{deal}").status_code == 200
    assert client.get("/api/documents").json()[0]["id"] == doc["id"]
    assert [p.read_bytes() for p in documents.DOCUMENTS_DIR.iterdir()] == [PDF]
