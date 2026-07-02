from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MappingProfile, Template
from app.schemas import SensitivityRequest, SensitivityResponse
from app.services import recalc_service, sensitivity_service

router = APIRouter(prefix="/api/sensitivity", tags=["sensitivity"])


@router.post("", response_model=SensitivityResponse)
def run_sensitivity(payload: SensitivityRequest, db: Session = Depends(get_db)):
    if not payload.drivers or len(payload.drivers) > 2:
        raise HTTPException(400, "Provide 1 or 2 drivers.")
    if not payload.outputFieldIds:
        raise HTTPException(400, "Select at least one output metric to track.")

    template = db.get(Template, payload.templateId)
    if template is None:
        raise HTTPException(404, "Template not found")

    mapping_profile = db.get(MappingProfile, payload.mappingProfileId)
    if mapping_profile is None:
        raise HTTPException(404, "Mapping profile not found")
    if mapping_profile.template_id != template.id:
        raise HTTPException(400, "Mapping profile does not belong to this template")

    unmapped = [d.fieldId for d in payload.drivers if d.fieldId not in mapping_profile.mappings]
    if unmapped:
        raise HTTPException(
            400,
            f"These driver field(s) aren't mapped in the selected profile, so varying them "
            f"wouldn't change the output: {', '.join(unmapped)}. Map them in "
            f"'Template & Mapping' first.",
        )

    total_points = 1
    for d in payload.drivers:
        total_points *= len(d.values)
    if total_points > sensitivity_service.MAX_GRID_POINTS:
        raise HTTPException(
            400,
            f"Grid too large ({total_points} points) — reduce driver value counts "
            f"(max {sensitivity_service.MAX_GRID_POINTS} total combinations, since each one "
            "requires a real server-side recalculation).",
        )

    if not recalc_service.is_available():
        raise HTTPException(
            400,
            "Sensitivity analysis requires LibreOffice for server-side recalculation, which "
            "isn't installed/detected on this server.",
        )

    template_path = Path(template.stored_path)
    try:
        outcome = sensitivity_service.run_sensitivity(
            template_path,
            mapping_profile.mappings,
            payload.baseValues,
            [d.model_dump() for d in payload.drivers],
            payload.outputFieldIds,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Sensitivity analysis failed: {exc}") from exc

    return SensitivityResponse(points=outcome["points"])
