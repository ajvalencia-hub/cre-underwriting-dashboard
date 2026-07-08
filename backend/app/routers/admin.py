"""J16: admin actions — backup now / list / restore."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import backup_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/backups")
def list_backups():
    return backup_service.list_backups()


@router.post("/backups/run")
def backup_now():
    path = backup_service.perform_backup("daily")
    return {"created": path.name, "kind": "daily"}


class RestoreRequest(BaseModel):
    kind: str
    name: str


@router.post("/backups/restore")
def restore_backup(payload: RestoreRequest):
    """Restores a snapshot's DB over the live database. RESTART the backend
    afterward so SQLAlchemy reopens the file. Returns the uploads manifest so
    the operator can confirm which files must still be on the data volume."""
    try:
        manifest = backup_service.restore_backup(payload.kind, payload.name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "restored": f"{payload.kind}/{payload.name}",
        "uploads": manifest.get("uploads", []),
        "note": "Restart the backend so the restored database is loaded.",
    }
