from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal, Scenario
from app.schemas import DealIn, DealOut, DealUpdate

router = APIRouter(prefix="/api/deals", tags=["deals"])


def _to_out(deal: Deal) -> DealOut:
    return DealOut(
        id=deal.id,
        name=deal.name,
        inputs=deal.inputs,
        activeTemplateId=deal.active_template_id,
        activeMappingProfileId=deal.active_mapping_profile_id,
        createdAt=deal.created_at,
        updatedAt=deal.updated_at,
    )


@router.get("", response_model=list[DealOut])
def list_deals(db: Session = Depends(get_db)):
    deals = db.execute(select(Deal).order_by(Deal.updated_at.desc())).scalars().all()
    return [_to_out(d) for d in deals]


@router.post("", response_model=DealOut)
def create_deal(payload: DealIn, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Deal name cannot be empty")
    deal = Deal(name=payload.name.strip(), inputs=payload.inputs)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return _to_out(deal)


@router.get("/{deal_id}", response_model=DealOut)
def get_deal(deal_id: str, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    return _to_out(deal)


@router.put("/{deal_id}", response_model=DealOut)
def update_deal(deal_id: str, payload: DealUpdate, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")

    # Partial-update semantics: only fields present in the request body are
    # applied, so the autosave (inputs only) can't clobber a concurrent
    # template selection (activeTemplateId only) and vice versa.
    provided = payload.model_fields_set
    if "name" in provided:
        if not (payload.name or "").strip():
            raise HTTPException(400, "Deal name cannot be empty")
        deal.name = payload.name.strip()
    if "inputs" in provided and payload.inputs is not None:
        deal.inputs = payload.inputs
    if "activeTemplateId" in provided:
        deal.active_template_id = payload.activeTemplateId
    if "activeMappingProfileId" in provided:
        deal.active_mapping_profile_id = payload.activeMappingProfileId

    db.commit()
    db.refresh(deal)
    return _to_out(deal)


@router.delete("/{deal_id}")
def delete_deal(deal_id: str, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    # Scenarios are meaningless without their deal — cascade, matching how
    # template deletion already removes dependent scenarios.
    db.execute(Scenario.__table__.delete().where(Scenario.deal_id == deal_id))
    db.delete(deal)
    db.commit()
    return {"deleted": True}
