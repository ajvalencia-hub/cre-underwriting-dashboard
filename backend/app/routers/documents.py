from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DOCUMENTS_DIR
from app.database import get_db
from app.models import Document
from app.routers.upload_limit import read_upload_limited
from app.schemas import DocumentSummary, DocumentTypeUpdate
from app.services import document_classifier
from app.services.template_service import compute_file_hash

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}


def _to_summary(doc: Document, reused: bool = False) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        fileHash=doc.file_hash,
        fileExt=doc.file_ext,
        dealId=doc.deal_id,
        documentType=doc.document_type,
        typeConfidence=doc.type_confidence,
        typeSource=doc.type_source,
        typeRationale=doc.type_rationale,
        createdAt=doc.created_at,
        reused=reused,
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(dealId: str | None = None, db: Session = Depends(get_db)):
    query = select(Document).order_by(Document.created_at.desc())
    if dealId is not None:
        query = query.where(Document.deal_id == dealId)
    docs = db.execute(query).scalars().all()
    return [_to_summary(d) for d in docs]


@router.post("/upload", response_model=DocumentSummary)
async def upload_document(
    file: UploadFile = File(...), dealId: str = Form(...), db: Session = Depends(get_db)
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type '{ext}'. Upload .pdf, .xlsx, .xls, or .csv."
        )

    file_bytes = await read_upload_limited(file)
    file_hash = compute_file_hash(file_bytes)

    # Dedup is scoped to THIS deal — the same file uploaded to two different
    # deals (e.g. a shared market report) becomes two separate rows rather
    # than silently attaching deal A's upload to deal B.
    existing = db.execute(
        select(Document).where(Document.file_hash == file_hash, Document.deal_id == dealId)
    ).scalar_one_or_none()
    if existing is not None:
        return _to_summary(existing, reused=True)

    stored_path = DOCUMENTS_DIR / f"{file_hash}{ext}"
    if not stored_path.exists():
        stored_path.write_bytes(file_bytes)

    classification = document_classifier.classify_document(stored_path, file.filename or "document")

    doc = Document(
        filename=file.filename or "document",
        file_hash=file_hash,
        stored_path=str(stored_path),
        file_ext=ext.lstrip("."),
        deal_id=dealId,
        document_type=classification["documentType"],
        type_confidence=classification["confidence"],
        type_source=classification["source"],
        type_rationale=classification["rationale"],
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_summary(doc)


@router.put("/{document_id}/type", response_model=DocumentSummary)
def update_document_type(document_id: str, payload: DocumentTypeUpdate, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")

    doc.document_type = payload.documentType
    doc.type_source = "manual"
    doc.type_confidence = 1.0
    doc.type_rationale = "Manually classified by user."
    db.commit()
    db.refresh(doc)
    return _to_summary(doc)


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    # The physical file is content-addressed (named by hash) and, now that
    # dedup is per-deal, may be shared by more than one Document row (the
    # same file uploaded to two different deals) — only remove it from disk
    # when no other row still references that path.
    other_ref = db.execute(
        select(Document.id).where(Document.stored_path == doc.stored_path, Document.id != doc.id)
    ).first()
    if other_ref is None:
        Path(doc.stored_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return {"deleted": True}
