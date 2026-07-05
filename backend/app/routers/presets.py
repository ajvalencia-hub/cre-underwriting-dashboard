from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AssumptionPreset
from app.services.presets import PRESET_FIELD_IDS, filter_preset_values

router = APIRouter(prefix="/api/presets", tags=["presets"])


class PresetIn(BaseModel):
    name: str
    description: str = ""
    values: dict


def _to_out(preset: AssumptionPreset) -> dict:
    return {
        "id": preset.id,
        "name": preset.name,
        "description": preset.description,
        "values": preset.values,
        "source": preset.source,
        "createdAt": preset.created_at,
        "updatedAt": preset.updated_at,
    }


@router.get("/fields")
def preset_fields():
    """The capturable field whitelist — the client builds its capture UI
    from this so the two sides can't drift."""
    return PRESET_FIELD_IDS


@router.get("")
def list_presets(db: Session = Depends(get_db)):
    presets = db.execute(
        select(AssumptionPreset).order_by(AssumptionPreset.created_at)
    ).scalars().all()
    return [_to_out(p) for p in presets]


@router.post("")
def create_preset(payload: PresetIn, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Preset name cannot be empty")
    values = filter_preset_values(payload.values)
    if not values:
        raise HTTPException(400, "Preset contains no capturable assumption fields.")
    preset = AssumptionPreset(
        name=payload.name.strip(), description=payload.description, values=values
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _to_out(preset)


@router.put("/{preset_id}")
def update_preset(preset_id: str, payload: PresetIn, db: Session = Depends(get_db)):
    preset = db.get(AssumptionPreset, preset_id)
    if preset is None:
        raise HTTPException(404, "Preset not found")
    if not payload.name.strip():
        raise HTTPException(400, "Preset name cannot be empty")
    values = filter_preset_values(payload.values)
    if not values:
        raise HTTPException(400, "Preset contains no capturable assumption fields.")
    preset.name = payload.name.strip()
    preset.description = payload.description
    preset.values = values
    preset.source = "user"  # an edited seed is the user's now
    db.commit()
    db.refresh(preset)
    return _to_out(preset)


@router.delete("/{preset_id}")
def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    preset = db.get(AssumptionPreset, preset_id)
    if preset is None:
        raise HTTPException(404, "Preset not found")
    db.delete(preset)
    db.commit()
    return {"deleted": True}
