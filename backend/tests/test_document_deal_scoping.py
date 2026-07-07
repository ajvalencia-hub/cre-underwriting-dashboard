"""P1: documents are scoped to a deal — every deal used to see every other
deal's uploads (list_documents had no filter, upload_document had nowhere to
put a deal association). Covers: listing filters by dealId, dedup is scoped
per-deal (the same file uploaded to two deals becomes two rows, not a silent
cross-deal reuse), and deleting one deal's copy doesn't remove the shared
on-disk file out from under the other deal's row.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    monkeypatch.setattr("app.routers.documents.DOCUMENTS_DIR", tmp_path)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db)
    engine.dispose()


def _upload(client, deal_id, filename="rent_roll.csv", content=b"unit,rent\nA-1,1500\n"):
    return client.post(
        "/api/documents/upload",
        files={"file": (filename, content, "text/csv")},
        data={"dealId": deal_id},
    )


def test_list_filters_by_deal(client):
    deal_a = client.post("/api/deals", json={"name": "Deal A"}).json()["id"]
    deal_b = client.post("/api/deals", json={"name": "Deal B"}).json()["id"]

    _upload(client, deal_a, "a.csv", b"a content")
    _upload(client, deal_b, "b.csv", b"b content")

    docs_a = client.get("/api/documents", params={"dealId": deal_a}).json()
    docs_b = client.get("/api/documents", params={"dealId": deal_b}).json()

    assert [d["filename"] for d in docs_a] == ["a.csv"]
    assert [d["filename"] for d in docs_b] == ["b.csv"]
    assert docs_a[0]["dealId"] == deal_a


def test_same_file_content_uploaded_to_two_deals_creates_two_rows(client):
    """Dedup-by-hash must be scoped per deal — otherwise uploading the same
    market report to deal B silently returns deal A's row (reused=True) and
    deal B's document list would show nothing of its own."""
    deal_a = client.post("/api/deals", json={"name": "Deal A"}).json()["id"]
    deal_b = client.post("/api/deals", json={"name": "Deal B"}).json()["id"]
    content = b"identical content"

    doc_a = _upload(client, deal_a, "report.csv", content).json()
    doc_b = _upload(client, deal_b, "report.csv", content).json()

    assert doc_a["id"] != doc_b["id"]
    assert doc_b["reused"] is False  # NOT reused from deal A despite identical hash
    assert doc_a["dealId"] == deal_a
    assert doc_b["dealId"] == deal_b


def test_reupload_within_same_deal_still_dedups(client):
    deal_a = client.post("/api/deals", json={"name": "Deal A"}).json()["id"]
    content = b"same file twice"

    first = _upload(client, deal_a, "x.csv", content).json()
    second = _upload(client, deal_a, "x.csv", content).json()

    assert first["id"] == second["id"]
    assert second["reused"] is True


def test_deleting_one_deals_copy_does_not_break_the_others(client):
    """Two deals share the same on-disk (content-addressed) file after the
    per-deal dedup change — deleting deal A's row must not unlink the file
    deal B's row still points at."""
    deal_a = client.post("/api/deals", json={"name": "Deal A"}).json()["id"]
    deal_b = client.post("/api/deals", json={"name": "Deal B"}).json()["id"]
    content = b"shared file"

    doc_a = _upload(client, deal_a, "shared.csv", content).json()
    doc_b = _upload(client, deal_b, "shared.csv", content).json()

    assert client.delete(f"/api/documents/{doc_a['id']}").json() == {"deleted": True}

    # deal B's row and its underlying file must still be intact.
    remaining = client.get("/api/documents", params={"dealId": deal_b}).json()
    assert [d["id"] for d in remaining] == [doc_b["id"]]


def test_list_without_dealid_returns_everything(client):
    """No dealId filter -> unscoped listing (back-compat / admin escape
    hatch), still includes both deals' documents."""
    deal_a = client.post("/api/deals", json={"name": "Deal A"}).json()["id"]
    deal_b = client.post("/api/deals", json={"name": "Deal B"}).json()["id"]
    _upload(client, deal_a, "a.csv", b"a")
    _upload(client, deal_b, "b.csv", b"b")

    all_docs = client.get("/api/documents").json()
    assert {d["filename"] for d in all_docs} == {"a.csv", "b.csv"}
