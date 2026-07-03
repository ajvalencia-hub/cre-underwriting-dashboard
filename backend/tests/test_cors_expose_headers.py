"""Regression test for FINDINGS.md M11: every custom header the generate
endpoint sets must be CORS-exposed, or cross-origin clients silently see None
for it (the dev proxy masks this by making requests same-origin).
"""

import re
from pathlib import Path

from app.main import app

_GENERATE_SOURCE = (Path(__file__).parent.parent / "app" / "routers" / "generate.py").read_text()


def _configured_expose_headers() -> list[str]:
    for middleware in app.user_middleware:
        if "expose_headers" in middleware.kwargs:
            return middleware.kwargs["expose_headers"]
    raise AssertionError("CORS middleware with expose_headers not found")


def test_every_custom_generate_header_is_exposed():
    custom_headers = set(re.findall(r'"(X-[A-Za-z-]+)":', _GENERATE_SOURCE))
    assert custom_headers, "expected generate.py to set X-* headers"
    exposed = {h.lower() for h in _configured_expose_headers()}
    missing = {h for h in custom_headers if h.lower() not in exposed}
    assert not missing, f"headers set by generate.py but not CORS-exposed: {missing}"


def test_content_disposition_is_exposed():
    assert "content-disposition" in {h.lower() for h in _configured_expose_headers()}
