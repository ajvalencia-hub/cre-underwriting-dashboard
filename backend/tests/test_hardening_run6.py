"""Run 6 audit hardening: LIKE escaping, shared-file delete guards, cabinet
deal isolation + inline-SVG refusal, dangling template refs, Monte Carlo job
robustness, header sanitization."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Deal, MappingProfile, Template
from app.routers.generate import _content_disposition
from app.services import monte_carlo
from app.services.sql_like import contains, escape_like


@pytest.fixture
def session_factory():
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(db_engine)
    yield sessionmaker(bind=db_engine)
    db_engine.dispose()


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


@pytest.fixture
def documents_dir(tmp_path, monkeypatch):
    from app.routers import file_cabinet

    monkeypatch.setattr(file_cabinet, "DOCUMENTS_DIR", tmp_path)
    return tmp_path


def _deal(client, name="Deal"):
    return client.post("/api/deals", json={"name": name}).json()["id"]


_DRIVER = {"inputPath": "exitCapRatePct", "distribution": "uniform",
           "params": {"min": 0.05, "max": 0.06}}


# --- LIKE escaping ----------------------------------------------------------

def test_escape_like_neutralizes_wildcards():
    assert escape_like("50% off_now\\x") == "50\\% off\\_now\\\\x"
    assert contains("a_b") == "%a\\_b%"


def test_search_treats_underscore_and_percent_literally(client):
    _deal(client, "Maple Court")
    _deal(client, "Oak_Ridge")
    # `__` used to match EVERY deal (two single-char wildcards).
    assert client.get("/api/search?q=__").json()["groups"] == []
    hits = client.get("/api/search?q=k_r").json()["groups"]
    assert [g["items"][0]["title"] for g in hits if g["kind"] == "deals"] == ["Oak_Ridge"]
    assert client.get("/api/search?q=%25%25").json()["groups"] == []


def test_comps_market_filter_is_literal(client):
    client.post("/api/comps/sale", json={"name": "A", "market": "Miami"})
    client.post("/api/comps/sale", json={"name": "B", "market": "Tampa"})
    # `%` used to disable the filter and return everything.
    assert client.get("/api/comps/sale?market=%25").json() == []
    assert [c["name"] for c in client.get("/api/comps/sale?market=iam").json()] == ["A"]


# --- shared-file delete guards ---------------------------------------------

def test_deleting_one_attachment_row_keeps_a_shared_file(client, documents_dir):
    a, b = _deal(client, "A"), _deal(client, "B")
    payload = {"file": ("shared.pdf", b"%PDF same bytes", "application/pdf")}
    doc_a = client.post(f"/api/deals/{a}/attachments", files=payload).json()
    doc_b = client.post(f"/api/deals/{b}/attachments", files=payload).json()
    assert doc_a["fileHash"] == doc_b["fileHash"]
    stored = documents_dir / f"{doc_a['fileHash']}.pdf"
    assert stored.exists()

    # Global documents route and the cabinet route both guard the unlink.
    assert client.delete(f"/api/documents/{doc_a['id']}").json() == {"deleted": True}
    assert stored.exists(), "file still referenced by deal B's row"
    assert client.get(f"/api/deals/{b}/attachments/{doc_b['id']}/download").status_code == 200
    assert client.delete(f"/api/deals/{b}/attachments/{doc_b['id']}").json() == {"deleted": True}
    assert not stored.exists()
    assert client.get(f"/api/deals/{b}/attachments").json() == []


def test_cabinet_delete_refuses_other_deals_and_global_docs(client, documents_dir):
    a, b = _deal(client, "A"), _deal(client, "B")
    doc = client.post(
        f"/api/deals/{a}/attachments", files={"file": ("x.txt", b"hi", "text/plain")}
    ).json()
    assert client.delete(f"/api/deals/{b}/attachments/{doc['id']}").status_code == 404
    assert len(client.get(f"/api/deals/{a}/attachments").json()) == 1


# --- cabinet deal isolation + inline hardening ------------------------------

def test_attachments_are_not_reachable_from_another_deal(client, documents_dir):
    a, b = _deal(client, "A"), _deal(client, "B")
    doc = client.post(
        f"/api/deals/{a}/attachments",
        files={"file": ("OM.pdf", b"%PDF private", "application/pdf")},
    ).json()
    # Deal B names "OM.pdf" in its provenance — deal A's private file must
    # NOT surface in B's cabinet, and B can't download/preview it by id.
    client.put(f"/api/deals/{b}", json={"inputs": {
        "_provenance": {"purchasePrice": {"sourceRef": {"doc": "OM.pdf", "page": 1}}}
    }})
    assert client.get(f"/api/deals/{b}/attachments").json() == []
    assert client.get(f"/api/deals/{b}/attachments/{doc['id']}/download").status_code == 404
    assert client.get(f"/api/deals/{b}/attachments/{doc['id']}/preview").status_code == 404
    assert client.get(f"/api/deals/{a}/attachments/{doc['id']}/download").status_code == 200


def test_svg_never_serves_inline_and_inline_responses_are_sandboxed(client, documents_dir):
    deal = _deal(client)
    svg = client.post(
        f"/api/deals/{deal}/attachments",
        files={"file": ("logo.svg", b"<svg onload=alert(1)/>", "image/svg+xml")},
    ).json()
    res = client.get(f"/api/deals/{deal}/attachments/{svg['id']}/download?inline=true")
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["x-content-type-options"] == "nosniff"

    png = client.post(
        f"/api/deals/{deal}/attachments", files={"file": ("a.png", b"\x89PNG", "image/png")}
    ).json()
    res = client.get(f"/api/deals/{deal}/attachments/{png['id']}/download?inline=true")
    assert res.headers["content-disposition"].startswith("inline")
    assert "sandbox" in res.headers["content-security-policy"]


def test_attachment_extension_is_whitelisted(client, documents_dir):
    deal = _deal(client)
    weird = client.post(
        f"/api/deals/{deal}/attachments",
        files={"file": ("notes.txt:stream", b"x", "text/plain")},
    ).json()
    assert weird["fileExt"] == "bin"
    long = client.post(
        f"/api/deals/{deal}/attachments",
        files={"file": ("f." + "a" * 200, b"y", "text/plain")},
    ).json()
    assert long["fileExt"] == "bin"
    assert {p.suffix for p in documents_dir.iterdir()} == {".bin"}


# --- dangling template / mapping references --------------------------------

def test_template_and_mapping_delete_clear_deal_selections(client, session_factory):
    deal_id = _deal(client)
    with session_factory() as db:
        template = Template(filename="t.xlsx", file_hash="h1", stored_path="nope.xlsx",
                            sheets=["MODEL"], named_ranges=[])
        db.add(template)
        db.flush()
        profile = MappingProfile(template_id=template.id, profile_name="p", mappings={})
        db.add(profile)
        db.flush()
        deal = db.get(Deal, deal_id)
        deal.active_template_id = template.id
        deal.active_mapping_profile_id = profile.id
        db.commit()
        template_id, profile_id = template.id, profile.id

    assert client.delete(f"/api/mappings/{profile_id}").json() == {"deleted": True}
    out = client.get(f"/api/deals/{deal_id}").json()
    assert out["activeMappingProfileId"] is None
    assert out["activeTemplateId"] == template_id

    assert client.delete(f"/api/templates/{template_id}").json() == {"deleted": True}
    out = client.get(f"/api/deals/{deal_id}").json()
    assert out["activeTemplateId"] is None


# --- Monte Carlo job robustness --------------------------------------------

def test_monte_carlo_rejects_negative_seed_synchronously():
    with pytest.raises(monte_carlo.MonteCarloError):
        monte_carlo.start_job({}, [_DRIVER], None, 5, -1, 0.08)


def test_monte_carlo_worker_crash_marks_job_failed(monkeypatch):
    def boom(*args, **kwargs):
        raise KeyError("malformed values")

    monkeypatch.setattr(monte_carlo, "run_simulation", boom)
    job_id = monte_carlo.start_job({}, [_DRIVER], None, 5, 1, 0.08)
    deadline = time.time() + 10
    status = monte_carlo.job_status(job_id)
    while status["status"] == "running" and time.time() < deadline:
        time.sleep(0.02)
        status = monte_carlo.job_status(job_id)
    assert status["status"] == "failed"
    assert "malformed values" in status["error"]
    assert monte_carlo.pending_jobs() == 0


def test_monte_carlo_pool_saturation_is_a_429(client, monkeypatch):
    monkeypatch.setattr(
        monte_carlo, "_pending", monte_carlo._MAX_WORKERS + monte_carlo._MAX_QUEUED
    )
    res = client.post("/api/compute/monte-carlo", json={"values": {}, "n": 5, "drivers": [_DRIVER]})
    assert res.status_code == 429
    assert res.headers["retry-after"] == "5"


# --- header sanitization ---------------------------------------------------

def test_content_disposition_strips_control_characters():
    header = _content_disposition("IC Memo - Evil\r\nX-Injected: 1 - Base.pdf")
    assert "\r" not in header and "\n" not in header
    assert "%0A" not in header and "%0D" not in header
    assert "Evil" in header


def test_request_id_header_is_bounded_and_sanitized(client):
    res = client.get("/api/health", headers={"X-Request-ID": "abc FORGED=1 " + "z" * 200})
    rid = res.headers["x-request-id"]
    assert " " not in rid and "=" not in rid
    assert len(rid) <= 64


def test_ic_deck_scenario_must_belong_to_the_deal(client):
    a, b = _deal(client, "A"), _deal(client, "B")
    scenario = client.post("/api/scenarios", json={
        "scenarioName": "s", "kind": "quickscreen", "dealId": b, "inputs": {}, "outputs": {},
    }).json()
    res = client.get(f"/api/deals/{a}/ic-deck.pptx?scenario_id={scenario['id']}")
    assert res.status_code in (404, 422)
    if res.status_code == 404:
        assert "Scenario" in res.json()["detail"]


def test_csv_import_multipart_413s_over_cap(client, monkeypatch):
    from app.routers import comps as comps_router

    monkeypatch.setattr(comps_router, "MAX_CSV_BYTES", 64)
    res = client.post(
        "/api/comps/import/file", data={"kind": "sale"},
        files={"file": ("big.csv", b"name,market\n" + b"x," * 100, "text/csv")},
    )
    assert res.status_code == 413


def test_legacy_xls_is_refused_with_guidance(client):
    res = client.post(
        "/api/documents/upload",
        files={"file": ("old.xls", b"\xd0\xcf", "application/vnd.ms-excel")},
    )
    assert res.status_code == 400
    assert ".xlsx" in res.json()["detail"]
