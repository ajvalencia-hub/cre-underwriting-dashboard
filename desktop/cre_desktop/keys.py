"""Optional API keys stored in the macOS Keychain.

The backend reads keys from the environment at import time (app.config), so
the launcher copies them from the Keychain into os.environ before importing
it. Changing a key therefore takes effect on the next launch — the Settings
screen offers a restart.
"""

import logging
import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from .paths import KEYCHAIN_SERVICE

log = logging.getLogger(__name__)

# Mirrors the entries listed by the backend's /api/admin/integrations.
KNOWN_KEYS = (
    "FRED_API_KEY",
    "CENSUS_API_KEY",
    "HUD_API_TOKEN",
    "BEA_API_KEY",
    "BLS_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


def load_into_environ() -> list[str]:
    """Copy stored keys into os.environ. Returns the names that were loaded.
    A key already present in the environment wins (useful for testing)."""
    loaded: list[str] = []
    for name in KNOWN_KEYS:
        if os.environ.get(name):
            continue
        try:
            value = keyring.get_password(KEYCHAIN_SERVICE, name)
        except KeyringError:
            log.exception("Keychain read failed for %s", name)
            continue
        if value:
            os.environ[name] = value
            loaded.append(name)
    return loaded


def stored_names() -> list[str]:
    names: list[str] = []
    for name in KNOWN_KEYS:
        try:
            if keyring.get_password(KEYCHAIN_SERVICE, name):
                names.append(name)
        except KeyringError:
            log.exception("Keychain read failed for %s", name)
    return names


def set_key(name: str, value: str) -> None:
    if name not in KNOWN_KEYS:
        raise ValueError(f"Unknown key {name}")
    value = value.strip()
    if value:
        keyring.set_password(KEYCHAIN_SERVICE, name, value)
    else:
        delete_key(name)


def delete_key(name: str) -> None:
    if name not in KNOWN_KEYS:
        raise ValueError(f"Unknown key {name}")
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, name)
    except PasswordDeleteError:
        pass  # already absent
