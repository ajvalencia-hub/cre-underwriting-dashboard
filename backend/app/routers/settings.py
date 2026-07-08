"""M1: DB-backed settings CRUD. All masking/precedence logic lives in
app/services/settings.py — this router is a thin HTTP wrapper."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import settings as settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    value: str


@router.get("")
def list_settings():
    return settings_service.list_settings()


@router.get("/usage")
def get_usage(dealId: str | None = None):
    """M5: registered BEFORE /{key} — otherwise "usage" would be swallowed
    as a (nonexistent) setting key, since FastAPI matches path routes in
    registration order and /{key} would match "/usage" first."""
    from app.services.agent import model_router

    return model_router.get_usage_summary(dealId)


@router.get("/{key}")
def get_setting(key: str):
    try:
        return settings_service.get_setting_entry(key)
    except KeyError:
        raise HTTPException(404, f"Unknown setting '{key}'.")


@router.put("/{key}")
def update_setting(key: str, payload: SettingUpdate):
    try:
        settings_service.set_setting(key, payload.value)
        return settings_service.get_setting_entry(key)
    except KeyError:
        raise HTTPException(404, f"Unknown setting '{key}'.")


@router.delete("/{key}")
def revert_setting(key: str):
    try:
        settings_service.delete_setting(key)
        return settings_service.get_setting_entry(key)
    except KeyError:
        raise HTTPException(404, f"Unknown setting '{key}'.")
