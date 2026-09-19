from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.database import get_db
from app.models import MappingProfile, Scenario, Template
from app.routers.upload_limit import read_upload_limited
from pydantic import BaseModel

from app.schemas import MappingEntry, SheetGrid, TemplateSummary
from app.services import recalc_agreement, recalc_service, template_service

router = APIRouter(prefix="/api/templates", tags=["templates"])

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _to_summary(template: Template, reused: bool = False) -> TemplateSummary:
    return TemplateSummary(
        id=template.id,
        filename=template.filename,
        fileHash=template.file_hash,
        createdAt=template.created_at,
        sheets=template.sheets,
        namedRanges=template.named_ranges,
        reused=reused,
    )


@router.get("", response_model=list[TemplateSummary])
def list_templates(db: Session = Depends(get_db)):
    templates = db.execute(select(Template).order_by(Template.created_at.desc())).scalars().all()
    return [_to_summary(t) for t in templates]


@router.post("/upload", response_model=TemplateSummary)
async def upload_template(file: UploadFile, db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload .xlsx or .xlsm.")

    file_bytes = await read_upload_limited(file)
    file_hash = template_service.compute_file_hash(file_bytes)

    existing = db.execute(
        select(Template).where(Template.file_hash == file_hash)
    ).scalar_one_or_none()
    if existing is not None:
        return _to_summary(existing, reused=True)

    stored_path = TEMPLATES_DIR / f"{file_hash}{ext}"
    stored_path.write_bytes(file_bytes)

    try:
        parsed = template_service.parse_workbook(stored_path)
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not parse workbook: {exc}") from exc

    template = Template(
        filename=file.filename or "template.xlsx",
        file_hash=file_hash,
        stored_path=str(stored_path),
        sheets=parsed["sheets"],
        named_ranges=parsed["namedRanges"],
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _to_summary(template)


@router.get("/{template_id}", response_model=TemplateSummary)
def get_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    return _to_summary(template)


@router.get("/{template_id}/sheets/{sheet_name}/grid", response_model=SheetGrid)
def get_sheet_grid(
    template_id: str,
    sheet_name: str,
    max_rows: int = 60,
    max_cols: int = 30,
    start_row: int = 1,
    db: Session = Depends(get_db),
):
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    try:
        return template_service.get_sheet_grid(
            Path(template.stored_path),
            sheet_name,
            max_rows=min(max_rows, 500),
            max_cols=min(max_cols, 100),
            start_row=start_row,
        )
    except KeyError:
        raise HTTPException(404, f"Sheet '{sheet_name}' not found in template")


@router.delete("/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")

    profile_ids = db.execute(
        select(MappingProfile.id).where(MappingProfile.template_id == template_id)
    ).scalars().all()
    if profile_ids:
        db.execute(
            Scenario.__table__.delete().where(Scenario.mapping_profile_id.in_(profile_ids))
        )
    db.execute(MappingProfile.__table__.delete().where(MappingProfile.template_id == template_id))
    db.execute(Scenario.__table__.delete().where(Scenario.template_id == template_id))

    Path(template.stored_path).unlink(missing_ok=True)
    db.delete(template)
    db.commit()
    return {"deleted": True}


class RecalcCheckRequest(BaseModel):
    mappings: dict[str, MappingEntry]


@router.post("/{template_id}/recalc-check")
def recalc_check(template_id: str, payload: RecalcCheckRequest, db: Session = Depends(get_db)):
    """Recalculate the unmodified template in LibreOffice and compare each
    mapped output with the value Excel saved (see recalc_agreement)."""
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    if not recalc_service.is_available():
        raise HTTPException(503, "LibreOffice isn't installed, so there's nothing to compare yet.")
    path = Path(template.stored_path)
    if not path.exists():
        raise HTTPException(404, f"The template file for {template.filename} is missing from storage — upload it again.")
    mappings = {k: v.model_dump() for k, v in payload.mappings.items()}
    try:
        return recalc_agreement.check(path, mappings)
    except Exception as exc:  # noqa: BLE001 — a LibreOffice failure is reported, not a 500
        raise HTTPException(502, f"LibreOffice couldn't recalculate this template: {exc}") from exc
