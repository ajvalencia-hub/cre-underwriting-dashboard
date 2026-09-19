"""Optional shared-token gate for the API.

The app has a single-user posture, but docker-compose binds the API on every
interface and the admin surface can overwrite the database. Setting
CRE_API_TOKEN turns on a gate for every /api route except /api/health and
/api/auth/*: requests must carry the token (Authorization: Bearer / X-API-Token)
or the session cookie that /api/auth/login sets. The cookie holds an HMAC of
the token, not the token itself, so a leaked cookie cannot be replayed as
the raw credential once the token is rotated. Unset (the default) means no
gate — existing local installs keep working unchanged.
"""

import hashlib
import hmac
import secrets

from fastapi import Request

from app import config

SESSION_COOKIE = "cre_session"
PUBLIC_PREFIXES = ("/api/health", "/api/auth/")


def token_required() -> bool:
    return bool(config.CRE_API_TOKEN)


def session_value(token: str) -> str:
    return hmac.new(token.encode("utf-8"), b"cre-dashboard-session", hashlib.sha256).hexdigest()


def token_matches(candidate: str | None) -> bool:
    if not candidate or not config.CRE_API_TOKEN:
        return False
    return secrets.compare_digest(candidate, config.CRE_API_TOKEN)


def is_public_path(path: str) -> bool:
    return not path.startswith("/api") or path.startswith(PUBLIC_PREFIXES)


def is_authorized(request: Request) -> bool:
    """True when no token is configured, or the request proves it."""
    if not token_required():
        return True
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer ") and token_matches(header[7:].strip()):
        return True
    if token_matches(request.headers.get("X-API-Token")):
        return True
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie and secrets.compare_digest(cookie, session_value(config.CRE_API_TOKEN)):
        return True
    return False
