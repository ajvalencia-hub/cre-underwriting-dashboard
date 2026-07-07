"""K4: the Underwriting Agent's HTTP surface. One thread per deal (the chat
dock and the Agent tab render the same thread — see plan K6); each POST is
one full non-streaming turn."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AGENT_PROVIDER
from app.database import get_db
from app.models import AgentMessage, AgentProposal, AgentThread, Deal
from app.services.agent import runner

router = APIRouter(prefix="/api/agent", tags=["agent"])


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


class PostMessageRequest(BaseModel):
    content: str


@router.post("/threads/{deal_id}/messages")
def post_message(deal_id: str, payload: PostMessageRequest, db: Session = Depends(get_db)):
    if db.get(Deal, deal_id) is None:
        raise HTTPException(404, "Deal not found")
    if not payload.content.strip():
        raise HTTPException(400, "Message content cannot be empty.")
    thread = _get_or_create_thread(db, deal_id)
    result = runner.run_turn(db, thread, payload.content.strip())
    return {"threadId": thread.id, **result}
