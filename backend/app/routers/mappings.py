from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MappingProfile, Scenario, Template
from app.schemas import AutoMatchResult, MappingEntry, MappingProfileIn, MappingProfileOut
from app.services import mapping_preview, mapping_service

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


class MappingPreviewIn(BaseModel):
    templateId: str
    mappings: dict[str, MappingEntry]
    values: dict[str, Any] = {}


@router.post("/preview")
def preview_mapping(payload: MappingPreviewIn, db: Session = Depends(get_db)):
    """Read-only: where each field's value would land in the template, what
    that cell holds now, and whether Generate would write or skip it. Takes
    the mapping as sent (so unsaved on-screen edits can be previewed)."""
    template = db.get(Template, payload.templateId)
    if template is None:
        raise HTTPException(404, "Template not found")
    path = Path(template.stored_path)
    if not path.exists():
        raise HTTPException(
            404, f"The template file for {template.filename} is missing from storage — upload it again."
        )
    mappings = {k: v.model_dump() for k, v in payload.mappings.items()}
    return {"fields": mapping_preview.preview(path, mappings, payload.values)}


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
