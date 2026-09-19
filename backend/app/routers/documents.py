from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DOCUMENTS_DIR
from app.database import get_db
from app.models import Document
from app.routers.upload_limit import read_upload_limited
from app.schemas import DocumentSummary, DocumentTypeUpdate
from app.services import document_classifier, document_storage
from app.services.template_service import compute_file_hash

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}


def _to_summary(doc: Document, reused: bool = False) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        fileHash=doc.file_hash,
        fileExt=doc.file_ext,
        documentType=doc.document_type,
        typeConfidence=doc.type_confidence,
        typeSource=doc.type_source,
        typeRationale=doc.type_rationale,
        createdAt=doc.created_at,
        reused=reused,
    )


@router.get("", response_model=list[DocumentSummary])
def list_documents(db: Session = Depends(get_db)):
    docs = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    return [_to_summary(d) for d in docs]


@router.post("/upload", response_model=DocumentSummary)
async def upload_document(file: UploadFile, db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400, f"Unsupported file type '{ext}'. Upload .pdf, .xlsx, .xls, or .csv."
        )

    file_bytes = await read_upload_limited(file)
    file_hash = compute_file_hash(file_bytes)

    # Reuse only a general document (deal attachments belong to their deal).
    # Several rows can share a hash, so take the first rather than expect one.
    existing = db.execute(
        select(Document)
        .where(Document.file_hash == file_hash, Document.deal_id.is_(None))
        .order_by(Document.created_at)
    ).scalars().first()
    if existing is not None:
        existing_path = Path(existing.stored_path)
        if not existing_path.exists():  # lost from disk: restore it
            existing_path.parent.mkdir(parents=True, exist_ok=True)
            existing_path.write_bytes(file_bytes)
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
    # The file may also back other deals' attachments — keep it for them.
    document_storage.release_file(db, doc)
    db.delete(doc)
    db.commit()
    return {"deleted": True}
