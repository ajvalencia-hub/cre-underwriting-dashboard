"""Uploaded files are stored once per content hash (DOCUMENTS_DIR/{hash}{ext}),
so one file on disk can back several Document rows: a Documents-tab upload
and attachments on any number of deals. A file is removed only when the
last row pointing at it goes."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document


def release_file(db: Session, doc: Document) -> None:
    """Delete doc's stored file unless another row still uses it. Call
    BEFORE deleting the row itself."""
    still_used = db.execute(
        select(Document.id).where(Document.stored_path == doc.stored_path, Document.id != doc.id)
    ).first()
    if still_used is None:
        Path(doc.stored_path).unlink(missing_ok=True)
