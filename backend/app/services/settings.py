"""M1: DB-backed settings, layered ABOVE app.config's env/code defaults.

[FIN] No "seed once from env" migration (see DECISIONS.md): resolution
happens at READ time (DB row, if present, else app.config's already-
resolved value, else the catalog's own default) rather than copying env
values into the DB once at first boot. Seeding would let a stale DB copy
silently outlive a later .env edit, since the DB row would then always win
even after the user updates their .env file — precedence-at-read-time makes
seeding unnecessary, env keeps working until a user explicitly overrides it
here.

Secrets are stored as plaintext (this is a local single-user desktop app —
the same trust model the .env file itself already has) but a raw secret
value is NEVER returned from mask()/list_settings() — callers only ever see
{isSet, last4}.

Each helper opens its own short-lived DB session (via database.SessionLocal)
rather than requiring a request-scoped `Depends(get_db)` session, since
non-request code (provider adapters, document_classifier, llm_extraction)
needs to read settings too and none of those call chains carry a FastAPI
DB dependency today.
"""

from dataclasses import dataclass
from typing import Literal

from app import config
from app.database import SessionLocal
from app.models import Setting

Source = Literal["db", "env", "default"]


@dataclass(frozen=True)
class SettingDef:
    category: str
    label: str
    is_secret: bool
    # Name of the app.config module attribute that supplies the env/code
    # default, or None for settings that don't exist in config.py yet.
    config_attr: str | None = None
    default: str = ""


# One entry per known setting. "env" as a resolved `source` actually means
# "app.config's already-computed value" — config.py itself falls back to a
# hardcoded default when the matching env var is unset, so this label can't
# distinguish "the user set ANTHROPIC_API_KEY in .env" from "config.py's own
# fallback kicked in" for non-empty-by-default attributes (e.g.
# AGENT_PROVIDER). Not worth introspecting raw os.environ per attribute just
# to draw that distinction in the UI.
SETTINGS_CATALOG: dict[str, SettingDef] = {
    # --- AI providers -----------------------------------------------------
    "anthropicApiKey": SettingDef("aiProviders", "Anthropic API Key", True, "ANTHROPIC_API_KEY"),
    "anthropicAgentModel": SettingDef("aiProviders", "Anthropic Agent Model", False, "ANTHROPIC_AGENT_MODEL"),
    "anthropicClassifierModel": SettingDef(
        "aiProviders", "Anthropic Classifier Model", False, "ANTHROPIC_CLASSIFIER_MODEL"
    ),
    "anthropicExtractionModel": SettingDef(
        "aiProviders", "Anthropic Extraction Model", False, "ANTHROPIC_EXTRACTION_MODEL"
    ),
    "openaiApiKey": SettingDef("aiProviders", "OpenAI API Key", True, "OPENAI_API_KEY"),
    "openaiAgentModel": SettingDef("aiProviders", "OpenAI Agent Model", False, "OPENAI_AGENT_MODEL"),
    "agentProvider": SettingDef("aiProviders", "Default Agent Provider", False, "AGENT_PROVIDER"),
    # --- Branding -----------------------------------------------------------
    "firmName": SettingDef("branding", "Firm Name", False, "FIRM_NAME"),
    "memoBrandColor": SettingDef("branding", "Memo Brand Color", False, "MEMO_BRAND_COLOR"),
    # --- Limits ---------------------------------------------------------
    "maxUploadBytes": SettingDef(
        "limits", "Max Upload Size (bytes)", False, default=str(50 * 1024 * 1024)
    ),
    # --- Public / market data (free API keys) ----------------------------
    "censusApiKey": SettingDef("publicData", "Census API Key", True, "CENSUS_API_KEY"),
    "blsApiKey": SettingDef("publicData", "BLS API Key", True, "BLS_API_KEY"),
    "beaApiKey": SettingDef("publicData", "BEA API Key", True, "BEA_API_KEY"),
    "fredApiKey": SettingDef("publicData", "FRED API Key", True, "FRED_API_KEY"),
    "hudApiToken": SettingDef("publicData", "HUD API Token", True, "HUD_API_TOKEN"),
    # --- Map / geocoding --------------------------------------------------
    "geocodeUserAgent": SettingDef("map", "Geocode User-Agent", False, "GEOCODE_USER_AGENT"),
}


def resolve_setting(key: str) -> tuple[str, Source]:
    """DB row wins if present; else app.config's resolved value (if the
    catalog entry names one and it's non-empty); else the catalog default."""
    definition = SETTINGS_CATALOG.get(key)
    if definition is None:
        raise KeyError(f"Unknown setting '{key}'.")
    with SessionLocal() as db:
        row = db.get(Setting, key)
    if row is not None:
        return row.value, "db"
    if definition.config_attr is not None:
        env_value = getattr(config, definition.config_attr, "")
        if env_value:
            return str(env_value), "env"
    return definition.default, "default"


def mask(value: str, is_secret: bool) -> dict:
    """{value} for non-secrets (nothing to mask); {isSet, last4} for
    secrets — the raw value is never included in the returned dict."""
    if not is_secret:
        return {"value": value}
    if not value:
        return {"isSet": False, "last4": None}
    return {"isSet": True, "last4": value[-4:]}


def list_settings() -> list[dict]:
    out = []
    for key, definition in SETTINGS_CATALOG.items():
        value, source = resolve_setting(key)
        entry = {
            "key": key,
            "category": definition.category,
            "label": definition.label,
            "isSecret": definition.is_secret,
            "source": source,
        }
        entry.update(mask(value, definition.is_secret))
        out.append(entry)
    return out


def get_setting_entry(key: str) -> dict:
    if key not in SETTINGS_CATALOG:
        raise KeyError(f"Unknown setting '{key}'.")
    definition = SETTINGS_CATALOG[key]
    value, source = resolve_setting(key)
    entry = {
        "key": key,
        "category": definition.category,
        "label": definition.label,
        "isSecret": definition.is_secret,
        "source": source,
    }
    entry.update(mask(value, definition.is_secret))
    return entry


def set_setting(key: str, value: str) -> None:
    definition = SETTINGS_CATALOG.get(key)
    if definition is None:
        raise KeyError(f"Unknown setting '{key}'.")
    with SessionLocal() as db:
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value, is_secret=definition.is_secret))
        else:
            row.value = value
        db.commit()


def delete_setting(key: str) -> None:
    """Revert to the env/code default — removes the DB override row, if any."""
    if key not in SETTINGS_CATALOG:
        raise KeyError(f"Unknown setting '{key}'.")
    with SessionLocal() as db:
        row = db.get(Setting, key)
        if row is not None:
            db.delete(row)
            db.commit()
