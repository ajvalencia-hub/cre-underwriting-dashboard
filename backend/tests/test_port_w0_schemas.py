"""Run 6 port (Wave 0): tag normalization, DealOut/DealSummaryOut shape,
UnitMixProposal "sf", and the new api_models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import api_models
from app.schemas import (
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_DEAL,
    DealOut,
    DealSummaryOut,
    DealUpdate,
    UnitMixProposal,
    normalize_tags,
)


def test_normalize_tags_strips_drops_empties_and_dedupes_keeping_first_spelling():
    assert normalize_tags(["  Core ", "", "   ", "core", "1031", "CORE", "broker:JLL"]) == [
        "Core",
        "1031",
        "broker:JLL",
    ]


def test_normalize_tags_casefold_dedupe():
    assert normalize_tags(["Straße", "STRASSE"]) == ["Straße"]


def test_normalize_tags_empty_list():
    assert normalize_tags([]) == []


def test_normalize_tags_limits():
    assert len(normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_DEAL)])) == MAX_TAGS_PER_DEAL
    with pytest.raises(ValueError, match="at most"):
        normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_DEAL + 1)])
    # Duplicates don't count against the cap.
    assert len(normalize_tags([f"t{i}" for i in range(MAX_TAGS_PER_DEAL)] + ["T0"])) == MAX_TAGS_PER_DEAL
    assert normalize_tags(["x" * MAX_TAG_LENGTH]) == ["x" * MAX_TAG_LENGTH]
    with pytest.raises(ValueError, match="exceeds"):
        normalize_tags(["x" * (MAX_TAG_LENGTH + 1)])
    # Length is measured after stripping.
    assert normalize_tags(["  " + "y" * MAX_TAG_LENGTH + "  "]) == ["y" * MAX_TAG_LENGTH]


def test_normalize_tags_rejects_non_strings():
    with pytest.raises(ValueError, match="strings"):
        normalize_tags(["ok", 5])


def test_deal_update_normalizes_tags_and_leaves_absent_tags_none():
    assert DealUpdate(tags=[" a ", "A", "b"]).tags == ["a", "b"]
    assert DealUpdate(name="x").tags is None
    with pytest.raises(ValidationError):
        DealUpdate(tags=["x" * (MAX_TAG_LENGTH + 1)])
    with pytest.raises(ValidationError):
        DealUpdate(tags=[f"t{i}" for i in range(MAX_TAGS_PER_DEAL + 1)])


def test_deal_update_422_over_http(client):
    deal = client.post("/api/deals", json={"name": "Tagged"}).json()
    resp = client.put(f"/api/deals/{deal['id']}", json={"tags": ["x" * (MAX_TAG_LENGTH + 1)]})
    assert resp.status_code == 422


def test_deal_out_defaults_archived_and_tags():
    now = datetime.now(timezone.utc)
    out = DealOut(
        id="d", name="n", inputs={}, activeTemplateId=None, activeMappingProfileId=None,
        createdAt=now, updatedAt=now,
    )
    assert out.archivedAt is None and out.tags == []


def test_deal_api_exposes_archived_at_and_tags(client):
    deal = client.post("/api/deals", json={"name": "Fresh"}).json()
    assert deal["archivedAt"] is None
    assert deal["tags"] == []


def test_deal_summary_out_shape():
    now = datetime.now(timezone.utc)
    out = DealSummaryOut(
        id="d", name="n", activeTemplateId=None, activeMappingProfileId=None,
        summary={"dealType": "acquisition", "market": "Miami"}, createdAt=now, updatedAt=now,
    )
    assert out.summary.market == "Miami" and out.summary.dealName is None
    assert "inputs" not in out.model_dump()


def test_unit_mix_proposal_accepts_sf_grouping():
    proposal = UnitMixProposal(rows=[], groupedBy="sf", warnings=[])
    assert proposal.groupedBy == "sf"
    with pytest.raises(ValidationError):
        UnitMixProposal(rows=[], groupedBy="nonsense", warnings=[])


def test_new_api_model_enums():
    def enum_of(model, field):
        return model.model_json_schema()["properties"][field]["enum"]

    assert "cancelled" in enum_of(api_models.MonteCarloJobOut, "status")
    assert "agent" in enum_of(api_models.SnapshotMetaOut, "kind")
    assert set(enum_of(api_models.MonteCarloCancelOut, "status")) == {
        "cancelling", "cancelled", "done", "failed",
    }
    bar = api_models.TornadoBarOut(key="k", label="l", low=None, high=None, impact=0.0)
    assert bar.inert is False and bar.reason is None


def test_agent_models_validate_run6_route_shapes():
    now = datetime.now(timezone.utc)
    proposal = {
        "id": "p", "kind": "input_changes", "changes": {"purchasePrice": 1}, "rationale": "r",
        "scenarioName": None, "preview": None, "warnings": [], "status": "pending",
    }
    turn = api_models.AgentTurnOut.model_validate({
        "threadId": "t", "text": "hi",
        "toolCalls": [{"name": "get_deal", "arguments": {}, "result": {"ok": 1}, "privilege": "read"}],
        "proposals": [proposal],
        "unverifiedClaims": [{"raw": "$5m", "value": 5_000_000.0, "kind": "dollar"}],
        "stoppedReason": None,
    })
    assert turn.proposals[0].id == "p"
    thread = api_models.AgentThreadOut.model_validate({
        "id": "t", "dealId": "d", "provider": "anthropic", "totalInputTokens": 0,
        "totalOutputTokens": 0,
        "messages": [{
            "id": "m", "role": "assistant", "content": "x", "toolCalls": [], "proposalIds": [],
            "unverifiedClaims": [], "stoppedReason": None, "createdAt": now,
        }],
        "proposals": [{**proposal, "createdAt": now}],
    })
    assert thread.messages[0].role == "assistant"
    assert api_models.AuthStatusOut(required=False, authenticated=True).authenticated
