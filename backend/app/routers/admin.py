"""Admin surface: backups (J16) + integration status (Settings page)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import backup_service
from app.api_models import BackupListingOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/integrations")
def integration_status():
    """Which optional API keys are configured — FLAGS ONLY, the values never
    leave the server. Feeds the Settings > Integrations panel; every source
    degrades gracefully when unset (that's the existing contract)."""
    from app import config

    entries = [
        ("FRED_API_KEY", "FRED (St. Louis Fed)", config.FRED_API_KEY,
         "Index rates — SOFR seed for floating debt, market-rates context."),
        ("CENSUS_API_KEY", "Census ACS", config.CENSUS_API_KEY,
         "Demographics and median-rent benchmarks."),
        ("HUD_API_TOKEN", "HUD", config.HUD_API_TOKEN,
         "Fair Market Rents for the rent-vs-market benchmark."),
        ("BEA_API_KEY", "BEA", config.BEA_API_KEY,
         "Regional income data in market context."),
        ("BLS_API_KEY", "BLS", config.BLS_API_KEY,
         "Employment trends (also works unauthenticated at low volume)."),
        ("ANTHROPIC_API_KEY", "Anthropic", config.ANTHROPIC_API_KEY,
         "LLM fallback for document classification and extraction."),
    ]
    return [
        {"envVar": env_var, "label": label, "configured": bool(value), "purpose": purpose}
        for env_var, label, value, purpose in entries
    ]


@router.get("/tools")
def external_tools_status():
    """Which optional system programs were found — read-only. Lets the UI
    explain up front why template recalculation / memo PDF / OCR are
    unavailable instead of failing at use time. Discovery itself lives in
    soffice.py and extraction/ocr.py and is unchanged."""
    from app.services import soffice
    from app.services.extraction import ocr

    return {
        "libreoffice": {
            "available": soffice.is_available(),
            "path": soffice.LIBREOFFICE_BIN,
            "enables": [
                "Reading recalculated results back from your Excel template",
                "Sensitivity runs verified through your Excel template",
                "IC memo as PDF",
            ],
        },
        "ocr": {
            "available": ocr.is_available(),
            "enables": ["Reading scanned (image-only) PDFs"],
        },
    }


@router.get("/backups", response_model=BackupListingOut)
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
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "restored": f"{payload.kind}/{payload.name}",
        "uploads": manifest.get("uploads", []),
        "preRestoreSnapshot": manifest.get("preRestoreSnapshot"),
        "note": "Restart the backend so the restored database is loaded.",
    }
