from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ExtractionResult
from app.schemas import ExtractionConfirmRequest, ExtractionRequest, ExtractionResultOut
from app.services import extraction_service

router = APIRouter(prefix="/api/extraction", tags=["extraction"])


def _to_out(result: ExtractionResult) -> ExtractionResultOut:
    return ExtractionResultOut(
        id=result.id,
        documentIds=result.document_ids,
        fields=result.fields,
        unmatched=result.unmatched,
        crossValidation=result.cross_validation,
        warnings=result.warnings,
        confirmedValues=result.confirmed_values,
        confirmedAt=result.confirmed_at,
        createdAt=result.created_at,
    )


@router.post("", response_model=ExtractionResultOut)
def run_extraction(payload: ExtractionRequest, db: Session = Depends(get_db)):
    if not payload.documentIds:
        raise HTTPException(400, "documentIds must not be empty")

    documents = db.execute(select(Document).where(Document.id.in_(payload.documentIds))).scalars().all()
    found_ids = {d.id for d in documents}
    missing = set(payload.documentIds) - found_ids
    if missing:
        raise HTTPException(404, f"Document(s) not found: {', '.join(missing)}")

    try:
        outcome = extraction_service.run_extraction(list(documents))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Extraction failed: {exc}") from exc

    result = ExtractionResult(
        document_ids=payload.documentIds,
        fields=outcome["fields"],
        unmatched=outcome["unmatchedExtractions"],
        cross_validation=outcome["crossValidation"],
        warnings=outcome["warnings"],
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return _to_out(result)


@router.get("/{result_id}", response_model=ExtractionResultOut)
def get_extraction(result_id: str, db: Session = Depends(get_db)):
    result = db.get(ExtractionResult, result_id)
    if result is None:
        raise HTTPException(404, "Extraction result not found")
    return _to_out(result)


@router.post("/{result_id}/confirm", response_model=ExtractionResultOut)
def confirm_extraction(result_id: str, payload: ExtractionConfirmRequest, db: Session = Depends(get_db)):
    result = db.get(ExtractionResult, result_id)
    if result is None:
        raise HTTPException(404, "Extraction result not found")

    result.confirmed_values = payload.confirmedValues
    result.confirmed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(result)
    return _to_out(result)
