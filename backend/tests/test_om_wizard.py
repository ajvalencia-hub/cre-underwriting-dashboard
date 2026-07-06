"""J10: OM-to-deal wizard — the finalize endpoint that turns a REVIEWED
extraction into a deal with provenance rows, carrying the review gate's
blocking-acknowledgment mechanics server-side; plus the resumable draft.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Document, ExtractionResult
from app.services.extraction_service import run_extraction
from tests.extraction_corpus import builders


@pytest.fixture
def env():
    db_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(db_engine)
    TestSession = sessionmaker(bind=db_engine)

    def _override():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    yield TestClient(app), TestSession
    app.dependency_overrides.pop(get_db)
    db_engine.dispose()


def _doc(path, name: str, doc_type: str) -> Document:
    return Document(
        filename=name, file_hash=name, stored_path=str(path),
        file_ext=path.suffix.lstrip("."), document_type=doc_type,
        type_confidence=1.0, type_source="manual", type_rationale="",
    )


def _store(TestSession, outcome, document_ids) -> str:
    db = TestSession()
    try:
        result = ExtractionResult(
            document_ids=document_ids,
            fields=outcome["fields"],
            unit_mix_proposal=outcome.get("unitMixProposal"),
            commercial_lease_proposal=outcome.get("commercialLeaseProposal"),
            unmatched=outcome["unmatchedExtractions"],
            cross_validation=outcome["crossValidation"],
            warnings=outcome["warnings"],
        )
        db.add(result)
        db.commit()
        db.refresh(result)
        return result.id
    finally:
        db.close()


def _reviewed_values(outcome) -> dict:
    return {
        fid: entry["value"]
        for fid, entry in outcome["fields"].items()
        if not fid.startswith("_")
    }


def test_yardi_rr_plus_t12_populates_a_multifamily_deal(env, tmp_path):
    client, TestSession = env
    rr_path = tmp_path / "yardi_rr.xlsx"
    t12_path = tmp_path / "yardi_t12.xlsx"
    builders.build_yardi_rent_roll(rr_path)
    builders.build_yardi_t12(t12_path)
    outcome = run_extraction([
        _doc(rr_path, "yardi_rr.xlsx", "rent_roll"),
        _doc(t12_path, "yardi_t12.xlsx", "t12_operating_statement"),
    ])
    result_id = _store(TestSession, outcome, ["d-rr", "d-t12"])
    confirmed = _reviewed_values(outcome)
    has_failures = any(c["status"] == "fail" for c in outcome["crossValidation"])

    resp = client.post("/api/deals/from-extraction", json={
        "name": "Maple Gardens (from OM)",
        "extractionResultId": result_id,
        "confirmedValues": confirmed,
        "acknowledgeFailures": has_failures,
    })
    assert resp.status_code == 200, resp.text
    deal = resp.json()
    assert deal["name"] == "Maple Gardens (from OM)"
    inputs = deal["inputs"]
    assert inputs["dealName"] == "Maple Gardens (from OM)"
    # Populated from the rent roll + T-12.
    assert isinstance(inputs.get("unitMix"), list) and len(inputs["unitMix"]) >= 2
    assert inputs.get("grossPotentialRent") or inputs.get("realEstateTaxes")
    # Provenance rows link fields to their source documents.
    provenance = inputs["_provenance"]
    assert set(provenance) == set(confirmed)
    mix_source = provenance["unitMix"]["sourceRef"]
    assert mix_source and "yardi_rr" in str(mix_source.get("doc", ""))
    # The extraction records the confirmation (existing mechanics).
    stored = client.get(f"/api/extraction/{result_id}").json()
    assert stored["confirmedAt"] is not None
    assert stored["confirmedValues"] == confirmed


def test_costar_rr_populates_a_commercial_deal(env, tmp_path):
    client, TestSession = env
    path = tmp_path / "costar.xlsx"
    builders.build_costar_rent_roll(path)
    outcome = run_extraction([_doc(path, "costar.xlsx", "rent_roll")])
    result_id = _store(TestSession, outcome, ["d-costar"])
    confirmed = _reviewed_values(outcome)
    proposal = outcome.get("commercialLeaseProposal")
    if proposal:
        confirmed["commercialLeases"] = [
            {k: v for k, v in row.items() if k != "sourceRowCount"}
            for row in proposal["rows"]
        ]

    resp = client.post("/api/deals/from-extraction", json={
        "name": "Riverside Plaza",
        "extractionResultId": result_id,
        "confirmedValues": confirmed,
        "acknowledgeFailures": any(
            c["status"] == "fail" for c in outcome["crossValidation"]
        ),
    })
    assert resp.status_code == 200, resp.text
    inputs = resp.json()["inputs"]
    assert isinstance(inputs.get("commercialLeases") or inputs.get("rentRoll"), list)
    assert inputs["_provenance"]  # every populated field has a row


def test_blocking_failures_stop_the_gate_server_side(env, tmp_path):
    client, TestSession = env
    db = TestSession()
    result = ExtractionResult(
        document_ids=["d1"], fields={"grossPotentialRent": {
            "value": 100_000, "sourceRef": {"doc": "om.pdf"},
            "confidence": 0.9, "source": "deterministic",
        }},
        unmatched=[], warnings=[],
        cross_validation=[{
            "rule": "unit_count_consistency", "status": "fail",
            "severity": "error", "detail": "48 rows vs 52 stated units",
            "relatedFieldIds": ["unitMix"],
        }],
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    result_id = result.id
    db.close()

    payload = {
        "name": "Hostile Deal", "extractionResultId": result_id,
        "confirmedValues": {"grossPotentialRent": 100_000},
    }
    blocked = client.post("/api/deals/from-extraction", json=payload)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["failures"][0]["rule"] == "unit_count_consistency"

    # The same request WITH acknowledgment goes through — identical to the
    # review gate's checkbox mechanics.
    acked = client.post(
        "/api/deals/from-extraction", json={**payload, "acknowledgeFailures": True}
    )
    assert acked.status_code == 200


def test_draft_finalize_resume_path(env, tmp_path):
    client, TestSession = env
    # The wizard parks its state on a draft deal.
    draft = client.post("/api/deals", json={
        "name": "Draft — from documents",
        "inputs": {"_omWizard": {"step": 1, "documentIds": ["d1"]}},
    }).json()
    assert draft["inputs"]["_omWizard"]["step"] == 1

    path = tmp_path / "t12.csv"
    path.write_text(
        "Line Item,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec,Total\n"
        "Gross Potential Rent,0,0,0,0,0,0,0,0,0,0,0,0,120000\n"
        "Real Estate Taxes,0,0,0,0,0,0,0,0,0,0,0,0,12000\n",
        encoding="utf-8",
    )
    outcome = run_extraction([_doc(path, "t12.csv", "t12_operating_statement")])
    result_id = _store(TestSession, outcome, ["d1"])

    resp = client.post("/api/deals/from-extraction", json={
        "name": "Finalized Deal",
        "extractionResultId": result_id,
        "confirmedValues": _reviewed_values(outcome),
        "acknowledgeFailures": True,  # T-12 coverage check may fail on totals-only
        "dealId": draft["id"],
    })
    assert resp.status_code == 200, resp.text
    deal = resp.json()
    # Finalized IN PLACE: same id, wizard state gone, renamed, history kept.
    assert deal["id"] == draft["id"]
    assert deal["name"] == "Finalized Deal"
    assert "_omWizard" not in deal["inputs"]
    history = client.get(f"/api/deals/{deal['id']}/history").json()
    assert len(history) >= 1  # the finalize snapshotted the draft state
    # Drafts are deletable (abandon path).
    other = client.post("/api/deals", json={
        "name": "Abandoned", "inputs": {"_omWizard": {"step": 1, "documentIds": []}},
    }).json()
    assert client.delete(f"/api/deals/{other['id']}").json() == {"deleted": True}
