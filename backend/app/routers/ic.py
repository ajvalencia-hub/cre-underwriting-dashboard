"""Investment-committee sign-off routes (roadmap #28). The workflow and the
input lock live in services/ic_workflow.py."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_models import IcState, IcSummaryOut
from app.database import get_db
from app.models import Deal
from app.services import ic_workflow

router = APIRouter(tags=["ic"])


class IcStepIn(BaseModel):
    kind: Literal["submit", "approve", "reject", "return", "reopen", "comment"]
    actor: str
    comment: str = ""
    # submit only: distinct approvals needed (default 1)
    requiredApprovals: int | None = None


def _deal(db: Session, deal_id: str) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    return deal


@router.get("/api/deals/{deal_id}/ic", response_model=IcSummaryOut)
def get_ic(deal_id: str, db: Session = Depends(get_db)):
    _deal(db, deal_id)
    return ic_workflow.summary(db, deal_id)


@router.post("/api/deals/{deal_id}/ic/events", response_model=IcSummaryOut)
def add_ic_step(deal_id: str, payload: IcStepIn, db: Session = Depends(get_db)):
    deal = _deal(db, deal_id)
    try:
        ic_workflow.record(db, deal, payload.kind, payload.actor, payload.comment, payload.requiredApprovals)
    except ic_workflow.IcError as exc:
        db.rollback()
        raise HTTPException(409 if exc.conflict else 400, str(exc)) from None
    db.commit()
    return ic_workflow.summary(db, deal_id)


@router.get("/api/ic/states", response_model=dict[str, IcState])
def ic_states(db: Session = Depends(get_db)):
    """Each deal's IC state other than draft (the pipeline's IC column)."""
    return ic_workflow.states_by_deal(db)
