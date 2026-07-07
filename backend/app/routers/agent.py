"""K4: the Underwriting Agent's HTTP surface. One thread per deal (the chat
dock and the Agent tab render the same thread — see plan K6); each POST is
one full non-streaming turn."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AGENT_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY
from app.database import get_db
from app.models import AgentMessage, AgentProposal, AgentThread, Deal
from app.routers.deals import _to_out as _deal_to_out
from app.services import deal_history
from app.services.agent import plays, runner

router = APIRouter(prefix="/api/agent", tags=["agent"])

# User-selectable providers only — "scripted" (K11's e2e-only deterministic
# stub) is deliberately excluded from this list; it's reachable solely via
# the AGENT_PROVIDER env var, never through the UI.
_SELECTABLE_PROVIDERS = [
    {"id": "anthropic", "label": "Anthropic (Claude)", "hasKey": bool(ANTHROPIC_API_KEY)},
    {"id": "openai", "label": "OpenAI", "hasKey": bool(OPENAI_API_KEY)},
]
_SELECTABLE_PROVIDER_IDS = {p["id"] for p in _SELECTABLE_PROVIDERS}


def _get_or_create_thread(db: Session, deal_id: str) -> AgentThread:
    thread = db.execute(
        select(AgentThread).where(AgentThread.deal_id == deal_id).order_by(AgentThread.created_at.desc())
    ).scalars().first()
    if thread is None:
        thread = AgentThread(deal_id=deal_id, provider=AGENT_PROVIDER)
        db.add(thread)
        db.commit()
        db.refresh(thread)
    return thread


def _message_out(m: AgentMessage) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "toolCalls": m.tool_calls,
        "proposalIds": m.proposal_ids,
        "unverifiedClaims": m.unverified_claims,
        "stoppedReason": m.stopped_reason,
        "createdAt": m.created_at,
    }


def _proposal_out(p: AgentProposal) -> dict:
    return {
        "id": p.id,
        "kind": p.kind,
        "changes": p.changes,
        "rationale": p.rationale,
        "scenarioName": p.scenario_name,
        "preview": p.preview,
        "warnings": p.warnings,
        "status": p.status,
        "createdAt": p.created_at,
    }


@router.get("/threads/{deal_id}")
def get_thread(deal_id: str, db: Session = Depends(get_db)):
    if db.get(Deal, deal_id) is None:
        raise HTTPException(404, "Deal not found")
    thread = _get_or_create_thread(db, deal_id)
    messages = db.execute(
        select(AgentMessage).where(AgentMessage.thread_id == thread.id).order_by(AgentMessage.created_at)
    ).scalars().all()
    proposals = db.execute(
        select(AgentProposal).where(AgentProposal.thread_id == thread.id).order_by(AgentProposal.created_at)
    ).scalars().all()
    return {
        "id": thread.id,
        "dealId": thread.deal_id,
        "provider": thread.provider,
        "totalInputTokens": thread.total_input_tokens,
        "totalOutputTokens": thread.total_output_tokens,
        "messages": [_message_out(m) for m in messages],
        "proposals": [_proposal_out(p) for p in proposals],
    }


@router.get("/plays")
def list_plays():
    """K8: the canned-workflow library surfaced as suggestion chips in the
    UI — id + label only; the prompt and tool-subset stay server-side."""
    return [{"id": p.id, "label": p.label} for p in plays.PLAYS]


@router.get("/providers")
def list_providers():
    """Which providers the UI may switch to, and whether each has a key
    configured server-side — the UI never sees the key itself, only this
    boolean, so it can gray out an option instead of letting the user pick
    a provider that will just come back "unavailable"."""
    return _SELECTABLE_PROVIDERS


class SetProviderRequest(BaseModel):
    provider: str


@router.put("/threads/{deal_id}/provider")
def set_thread_provider(deal_id: str, payload: SetProviderRequest, db: Session = Depends(get_db)):
    """Switches which model answers the NEXT turn in this deal's thread.
    Takes effect immediately — no server restart, no .env edit — since the
    runner already reads thread.provider per turn rather than a fixed
    global. History from the previous provider is untouched; only future
    turns use the new one."""
    if payload.provider not in _SELECTABLE_PROVIDER_IDS:
        raise HTTPException(
            400, f"Unknown provider '{payload.provider}'. Valid options: {', '.join(sorted(_SELECTABLE_PROVIDER_IDS))}."
        )
    if db.get(Deal, deal_id) is None:
        raise HTTPException(404, "Deal not found")
    thread = _get_or_create_thread(db, deal_id)
    thread.provider = payload.provider
    db.commit()
    db.refresh(thread)
    return {"id": thread.id, "dealId": thread.deal_id, "provider": thread.provider}


class PostMessageRequest(BaseModel):
    content: str = ""
    playId: str | None = None


@router.post("/threads/{deal_id}/messages")
def post_message(deal_id: str, payload: PostMessageRequest, db: Session = Depends(get_db)):
    if db.get(Deal, deal_id) is None:
        raise HTTPException(404, "Deal not found")
    play = plays.PLAYS_BY_ID.get(payload.playId) if payload.playId else None
    if payload.playId and play is None:
        raise HTTPException(400, f"Unknown play '{payload.playId}'.")
    if play is None and not payload.content.strip():
        raise HTTPException(400, "Message content cannot be empty.")

    text = play.prompt if play else payload.content.strip()
    tool_names = play.tools if play else None
    thread = _get_or_create_thread(db, deal_id)
    result = runner.run_turn(db, thread, text, tool_names=tool_names)
    return {"threadId": thread.id, **result}


class ApproveProposalRequest(BaseModel):
    # Lets the user tweak a value before applying (e.g. round a proposed
    # price); defaults to the proposal's own changes as-authored.
    overrideChanges: dict[str, Any] | None = None


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, payload: ApproveProposalRequest, db: Session = Depends(get_db)):
    """K7: applies a proposal's changes through the same audit-trail
    mechanism every other deal edit uses (deal_history.record_snapshot),
    tagged kind="agent" so it's visibly distinguishable in the history
    drawer. Any other still-pending proposal for this deal is marked
    "stale" — its preview was computed against inputs that just changed."""
    proposal = db.get(AgentProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(400, f"Proposal is already {proposal.status}.")
    deal = db.get(Deal, proposal.deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")

    changes = payload.overrideChanges if payload.overrideChanges is not None else proposal.changes
    merged = {**(deal.inputs or {}), **changes}
    deal_history.record_snapshot(db, deal, merged, kind="agent")
    deal.inputs = merged
    proposal.status = "approved"

    db.execute(
        AgentProposal.__table__.update()
        .where(
            AgentProposal.deal_id == deal.id,
            AgentProposal.status == "pending",
            AgentProposal.id != proposal.id,
        )
        .values(status="stale")
    )

    db.commit()
    db.refresh(deal)
    db.refresh(proposal)
    return {"deal": _deal_to_out(deal).model_dump(), "proposal": _proposal_out(proposal)}


class RejectProposalRequest(BaseModel):
    note: str = ""


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, payload: RejectProposalRequest, db: Session = Depends(get_db)):
    proposal = db.get(AgentProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(400, f"Proposal is already {proposal.status}.")
    proposal.status = "rejected"
    if payload.note.strip():
        db.add(
            AgentMessage(
                thread_id=proposal.thread_id,
                role="user",
                content=f"(Rejected proposal: {payload.note.strip()})",
            )
        )
    db.commit()
    db.refresh(proposal)
    return {"proposal": _proposal_out(proposal)}
