"""J12: deal file cabinet + notes.

Attachments generalize the Document model (nullable deal_id): any file type,
same size cap as every other upload (MAX_UPLOAD_BYTES), stored alongside the
existing document storage. Extraction documents remain global and surface in
a deal's cabinet when the deal's provenance names them (badge, not copy).
PDF preview is the first page's TEXT via pdfplumber — rendering a thumbnail
image would need a rasterizer dependency for a cosmetic feature (rejected).
Notes are a timestamped timeline; markdown-lite rendering happens client-side
without a markdown dependency.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DOCUMENTS_DIR
from app.database import get_db
from app.models import Deal, DealNote, Document
from app.routers.upload_limit import read_upload_limited
from app.services.template_service import compute_file_hash

router = APIRouter(prefix="/api/deals", tags=["file-cabinet"])

# Attachments accept ANY extension (unlike extraction uploads) — the cabinet
# is storage, not a parser input.
_INLINE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "pdf"}


def _attachment_out(doc: Document, source: str) -> dict:
    path = Path(doc.stored_path)
    return {
        "id": doc.id,
        "filename": doc.filename,
        "fileHash": doc.file_hash,
        "fileExt": doc.file_ext,
        "sizeBytes": path.stat().st_size if path.exists() else None,
        "source": source,  # attachment | extraction
        "documentType": doc.document_type,
        "createdAt": doc.created_at,
    }


def _get_deal(db: Session, deal_id: str) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    return deal


@router.get("/{deal_id}/attachments")
def list_attachments(deal_id: str, db: Session = Depends(get_db)):
    deal = _get_deal(db, deal_id)
    rows = [
        _attachment_out(doc, "attachment")
        for doc in db.execute(
            select(Document).where(Document.deal_id == deal_id).order_by(Document.created_at.desc())
        ).scalars()
    ]
    # Extraction-linked documents: the deal's provenance names its source
    # files — show them here with a badge (global docs, never duplicated).
    provenance = (deal.inputs or {}).get("_provenance") or {}
    source_names = {
        str((entry.get("sourceRef") or {}).get("doc"))
        for entry in provenance.values()
        if isinstance(entry, dict) and isinstance(entry.get("sourceRef"), dict)
    }
    if source_names:
        seen = {row["fileHash"] for row in rows}
        for doc in db.execute(
            select(Document).where(Document.filename.in_(source_names))
        ).scalars():
            if doc.file_hash not in seen:
                rows.append(_attachment_out(doc, "extraction"))
    return rows


@router.post("/{deal_id}/attachments")
async def upload_attachment(deal_id: str, file: UploadFile, db: Session = Depends(get_db)):
    _get_deal(db, deal_id)
    ext = Path(file.filename or "").suffix.lower()
    file_bytes = await read_upload_limited(file)  # 413 over the cap
    file_hash = compute_file_hash(file_bytes)

    stored_path = DOCUMENTS_DIR / f"{file_hash}{ext or '.bin'}"
    if not stored_path.exists():
        stored_path.write_bytes(file_bytes)

    doc = Document(
        filename=file.filename or "attachment",
        file_hash=file_hash,
        stored_path=str(stored_path),
        file_ext=ext.lstrip(".") or "bin",
        document_type="other",
        type_confidence=1.0,
        type_source="manual",
        type_rationale="Deal attachment (file cabinet).",
        deal_id=deal_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _attachment_out(doc, "attachment")


@router.get("/{deal_id}/attachments/{document_id}/download")
def download_attachment(
    deal_id: str, document_id: str, inline: bool = False, db: Session = Depends(get_db)
):
    _get_deal(db, deal_id)
    doc = db.get(Document, document_id)
    if doc is None or not Path(doc.stored_path).exists():
        raise HTTPException(404, "Attachment not found")
    disposition = "inline" if inline and doc.file_ext in _INLINE_EXTS else "attachment"
    headers = {}
    if doc.file_ext == "svg":
        # An uploaded SVG can carry script; opened directly it would run in
        # the app's origin. Sandboxed, it renders as a picture only.
        headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        )
    return FileResponse(
        doc.stored_path,
        filename=doc.filename,
        content_disposition_type=disposition,
        headers=headers,
    )


@router.get("/{deal_id}/attachments/{document_id}/preview")
def preview_attachment(deal_id: str, document_id: str, db: Session = Depends(get_db)):
    """First-page TEXT preview for PDFs (cheap, reuses pdfplumber); other
    types return a typed no-preview response, never an error."""
    _get_deal(db, deal_id)
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Attachment not found")
    if doc.file_ext != "pdf":
        return {"kind": "none", "note": f".{doc.file_ext} files have no text preview."}
    try:
        import pdfplumber

        with pdfplumber.open(doc.stored_path) as pdf:
            text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception:  # noqa: BLE001 — corrupt files preview as empty
        return {"kind": "none", "note": "The PDF could not be read."}
    return {"kind": "text", "text": text[:1200]}


class NoteIn(BaseModel):
    body: str


@router.get("/{deal_id}/notes")
def list_notes(deal_id: str, db: Session = Depends(get_db)):
    _get_deal(db, deal_id)
    notes = db.execute(
        select(DealNote).where(DealNote.deal_id == deal_id).order_by(DealNote.created_at.desc())
    ).scalars()
    return [
        {"id": n.id, "body": n.body, "createdAt": n.created_at, "updatedAt": n.updated_at}
        for n in notes
    ]


@router.post("/{deal_id}/notes")
def create_note(deal_id: str, payload: NoteIn, db: Session = Depends(get_db)):
    _get_deal(db, deal_id)
    if not payload.body.strip():
        raise HTTPException(400, "Note body cannot be empty")
    note = DealNote(deal_id=deal_id, body=payload.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"id": note.id, "body": note.body, "createdAt": note.created_at, "updatedAt": note.updated_at}


@router.put("/{deal_id}/notes/{note_id}")
def update_note(deal_id: str, note_id: str, payload: NoteIn, db: Session = Depends(get_db)):
    note = db.get(DealNote, note_id)
    if note is None or note.deal_id != deal_id:
        raise HTTPException(404, "Note not found")
    if not payload.body.strip():
        raise HTTPException(400, "Note body cannot be empty")
    note.body = payload.body
    db.commit()
    db.refresh(note)
    return {"id": note.id, "body": note.body, "createdAt": note.created_at, "updatedAt": note.updated_at}


@router.delete("/{deal_id}/notes/{note_id}")
def delete_note(deal_id: str, note_id: str, db: Session = Depends(get_db)):
    note = db.get(DealNote, note_id)
    if note is None or note.deal_id != deal_id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
    return {"deleted": True}
