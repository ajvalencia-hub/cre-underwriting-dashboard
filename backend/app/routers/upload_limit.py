"""Shared upload-size guard for the document and template upload routes.

Uploads were read fully into memory with no cap (FINDINGS.md M9); a single
oversized file could exhaust the process. Reads are chunked so the request is
rejected with a 413 as soon as it crosses the cap, not after buffering it all.

M1: the default cap is settings-backed (SETTINGS_CATALOG["maxUploadBytes"])
rather than this hardcoded constant — resolved per call, so a change via the
Settings UI takes effect on the next upload without a restart.
"""

from fastapi import HTTPException, UploadFile

from app.services import settings as settings_service

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # kept as the catalog's own fallback default
_CHUNK_BYTES = 1024 * 1024


async def read_upload_limited(file: UploadFile, max_bytes: int | None = None) -> bytes:
    limit = max_bytes
    if limit is None:
        limit = int(settings_service.resolve_setting("maxUploadBytes")[0])
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                413, f"File exceeds the {limit // (1024 * 1024)} MB upload limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)
