"""Token session endpoints (see app.auth). The frontend calls /status at
boot; when a token is required and the browser has no session it shows a
token prompt and posts to /login, which sets the HttpOnly session cookie so
plain `<a href>` downloads keep working without a header."""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app import auth, config
from app.api_models import AuthStatusOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_MAX_AGE = 30 * 24 * 3600


@router.get("/status", response_model=AuthStatusOut)
def auth_status(request: Request):
    return {
        "required": auth.token_required(),
        "authenticated": auth.is_authorized(request),
    }


class LoginRequest(BaseModel):
    token: str


@router.post("/login", response_model=AuthStatusOut)
def login(payload: LoginRequest, response: Response):
    if not auth.token_required():
        return {"authenticated": True, "required": False}
    if not auth.token_matches(payload.token.strip()):
        raise HTTPException(401, "Invalid API token")
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.session_value(config.CRE_API_TOKEN),
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"authenticated": True, "required": True}


@router.post("/logout", response_model=AuthStatusOut)
def logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"authenticated": False, "required": auth.token_required()}
