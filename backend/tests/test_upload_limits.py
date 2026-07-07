"""Regression tests for FINDINGS.md M9: uploads were read fully into memory
with no size cap. Oversized files must be rejected with a 413 on both the
document and template upload routes.
"""

import asyncio
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.routers import upload_limit


class _StubUpload:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


def test_under_limit_reads_fully():
    data = b"x" * 2048
    out = asyncio.run(upload_limit.read_upload_limited(_StubUpload(data), max_bytes=4096))
    assert out == data


def test_over_limit_raises_413_without_buffering_everything():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_limit.read_upload_limited(_StubUpload(b"x" * 5000), max_bytes=4096))
    assert exc.value.status_code == 413


def test_document_upload_route_returns_413(monkeypatch):
    monkeypatch.setattr(upload_limit, "MAX_UPLOAD_BYTES", 1024)
    client = TestClient(app)
    resp = client.post(
        "/api/documents/upload",
        files={"file": ("big.csv", b"x" * 2048, "text/csv")},
        data={"dealId": "deal-1"},
    )
    assert resp.status_code == 413


def test_template_upload_route_returns_413(monkeypatch):
    monkeypatch.setattr(upload_limit, "MAX_UPLOAD_BYTES", 1024)
    client = TestClient(app)
    resp = client.post(
        "/api/templates/upload",
        files={"file": ("big.xlsx", b"x" * 2048, "application/octet-stream")},
    )
    assert resp.status_code == 413
