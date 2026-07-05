import json
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from typing import Any

from pydantic import BaseModel

from app.config import GENERATED_DIR
from app.database import get_db
from app.models import MappingProfile, Template
from app.schemas import GenerateRequest
from app.services import excel_model_export, excel_writer, mapping_service, recalc_service
from app.services.proforma import engine as proforma_engine

router = APIRouter(prefix="/api/generate", tags=["generate"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM_MEDIA_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.12"


def _content_disposition(filename: str) -> str:
    """ASGI response headers must encode as latin-1, so a template filename
    containing non-ASCII characters crashed every download, and an embedded
    double quote corrupted the header. Send an ASCII-safe fallback in
    filename= plus the real name RFC 5987-encoded in filename*.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "'")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


class ModelExportRequest(BaseModel):
    values: dict[str, Any]


@router.post("/model")
def export_native_model(payload: ModelExportRequest):
    """H11: formula-live Excel model built from the deal inputs — no template
    or mapping needed. 422s with the blocker list when the deal shape can't
    be mirrored as formulas."""
    try:
        content, warnings = excel_model_export.build_model_workbook(payload.values)
    except excel_model_export.UnsupportedModelFeatures as exc:
        raise HTTPException(
            422,
            "Excel model export doesn't support: " + "; ".join(exc.features),
        ) from exc
    except proforma_engine.InsufficientInputsError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": _content_disposition("native-model.xlsx"),
            "X-Generation-Warnings": json.dumps(warnings),
        },
    )


@router.post("")
def generate(payload: GenerateRequest, db: Session = Depends(get_db)):
    template = db.get(Template, payload.templateId)
    if template is None:
        raise HTTPException(404, "Template not found")

    mapping_profile = db.get(MappingProfile, payload.mappingProfileId)
    if mapping_profile is None:
        raise HTTPException(404, "Mapping profile not found")
    if mapping_profile.template_id != template.id:
        raise HTTPException(400, "Mapping profile does not belong to this template")

    template_path = Path(template.stored_path)
    output_path = GENERATED_DIR / f"{uuid.uuid4()}{template_path.suffix}"

    try:
        result = excel_writer.inject_values(
            template_path, output_path, mapping_profile.mappings, payload.values
        )
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Failed to generate workbook: {exc}") from exc

    outputs: dict = {}
    if payload.recalc:
        try:
            recalc_service.recalc_with_libreoffice(output_path)
            output_field_ids = [f["id"] for f in mapping_service.load_output_fields()]
            outputs = excel_writer.read_output_values(
                output_path, mapping_profile.mappings, output_field_ids
            )
        except Exception as exc:
            result["warnings"].append(f"Server-side recalc skipped: {exc}")

    file_bytes = output_path.read_bytes()
    output_path.unlink(missing_ok=True)

    media_type = XLSM_MEDIA_TYPE if template_path.suffix.lower() == ".xlsm" else XLSX_MEDIA_TYPE
    headers = {
        "Content-Disposition": _content_disposition(template.filename),
        "X-Generation-Warnings": json.dumps(result["warnings"]),
        "X-Generation-Written-Count": str(len(result["written"])),
        "X-Generation-Outputs": json.dumps(outputs, default=str),
    }
    return Response(content=file_bytes, media_type=media_type, headers=headers)
