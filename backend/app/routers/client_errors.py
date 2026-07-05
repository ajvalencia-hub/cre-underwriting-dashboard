"""Client error reporting sink (H13): the React error boundary posts here so
frontend crashes land in the SAME log stream as backend requests. Bounded
fields — this is a diagnostics channel, not a storage system."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/client-errors", tags=["client-errors"])

logger = logging.getLogger("app.client")

_MAX_FIELD = 4_000


class ClientErrorReport(BaseModel):
    message: str
    stack: str = ""
    componentStack: str = ""
    url: str = ""


@router.post("")
def report_client_error(payload: ClientErrorReport):
    logger.warning(
        "client-error url=%s message=%s\nstack=%s\ncomponents=%s",
        payload.url[:_MAX_FIELD],
        payload.message[:_MAX_FIELD],
        payload.stack[:_MAX_FIELD],
        payload.componentStack[:_MAX_FIELD],
    )
    return {"logged": True}
