from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MappingProfile, Scenario, Template
from app.schemas import AutoMatchResult, MappingProfileIn, MappingProfileOut
from app.services import mapping_service

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


def _to_out(profile: MappingProfile) -> MappingProfileOut:
    return MappingProfileOut(
        id=profile.id,
        templateId=profile.template_id,
        profileName=profile.profile_name,
        mappings=profile.mappings,
        unmappedRequiredFields=mapping_service.compute_unmapped_required(profile.mappings),
        createdAt=profile.created_at,
        updatedAt=profile.updated_at,
    )


@router.get("", response_model=list[MappingProfileOut])
def list_mappings(template_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(MappingProfile)
    if template_id:
        stmt = stmt.where(MappingProfile.template_id == template_id)
    profiles = db.execute(stmt.order_by(MappingProfile.updated_at.desc())).scalars().all()
    return [_to_out(p) for p in profiles]


@router.get("/auto-match/{template_id}", response_model=AutoMatchResult)
def auto_match(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    mappings = mapping_service.auto_match(template.named_ranges, Path(template.stored_path))
    return AutoMatchResult(mappings=mappings)


@router.post("", response_model=MappingProfileOut)
def create_mapping(payload: MappingProfileIn, db: Session = Depends(get_db)):
    template = db.get(Template, payload.templateId)
    if template is None:
        raise HTTPException(404, "Template not found")

    profile = MappingProfile(
        template_id=payload.templateId,
        profile_name=payload.profileName,
        mappings={k: v.model_dump() for k, v in payload.mappings.items()},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _to_out(profile)


@router.get("/{mapping_id}", response_model=MappingProfileOut)
def get_mapping(mapping_id: str, db: Session = Depends(get_db)):
    profile = db.get(MappingProfile, mapping_id)
    if profile is None:
        raise HTTPException(404, "Mapping profile not found")
    return _to_out(profile)


@router.put("/{mapping_id}", response_model=MappingProfileOut)
def update_mapping(mapping_id: str, payload: MappingProfileIn, db: Session = Depends(get_db)):
    profile = db.get(MappingProfile, mapping_id)
    if profile is None:
        raise HTTPException(404, "Mapping profile not found")

    profile.profile_name = payload.profileName
    profile.mappings = {k: v.model_dump() for k, v in payload.mappings.items()}
    db.commit()
    db.refresh(profile)
    return _to_out(profile)


@router.delete("/{mapping_id}")
def delete_mapping(mapping_id: str, db: Session = Depends(get_db)):
    profile = db.get(MappingProfile, mapping_id)
    if profile is None:
        raise HTTPException(404, "Mapping profile not found")

    db.execute(Scenario.__table__.delete().where(Scenario.mapping_profile_id == mapping_id))
    db.delete(profile)
    db.commit()
    return {"deleted": True}
