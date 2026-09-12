"""Run 6: in-process token bucket for the routes that fan out to external
public-data APIs (FRED, Census/ACS, BLS, Nominatim, HUD ...).

Those upstreams have their own quotas and a single misbehaving client
(a polling tab, a scripted loop) would burn them for everyone on a shared
LAN install. The bucket is keyed by ROUTE NAME, not by client — the app
is single-tenant and the quota being protected is the upstream's, which
is shared regardless of who asks.

The limit is read from ``app.config`` at request time (never captured at
import) so a test can monkeypatch ``CRE_EXTERNAL_RATE_LIMIT_PER_MIN`` down
to a small number and exercise the 429 path; ``0`` disables the gate.
A bucket rebuilds itself when the configured limit changes so a stale
capacity never lingers after a monkeypatch is undone.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException

from app import config


@dataclass
class _Bucket:
    limit: int  # tokens per minute == capacity
    tokens: float
    updated: float  # monotonic seconds

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(float(self.limit), self.tokens + elapsed * (self.limit / 60.0))
        self.updated = now


_lock = threading.Lock()
_buckets: dict[str, _Bucket] = {}


def _clock() -> float:
    return time.monotonic()


def current_limit() -> int:
    """Requests per minute per route; <= 0 means disabled."""
    try:
        return int(config.CRE_EXTERNAL_RATE_LIMIT_PER_MIN)
    except (TypeError, ValueError):
        return 0


def try_acquire(route: str, now: float | None = None) -> float:
    """Take one token for ``route``. Returns 0.0 on success, otherwise the
    number of seconds until a token will be available (always > 0)."""
    limit = current_limit()
    if limit <= 0:
        return 0.0
    ts = _clock() if now is None else now
    with _lock:
        bucket = _buckets.get(route)
        if bucket is None or bucket.limit != limit:
            bucket = _Bucket(limit=limit, tokens=float(limit), updated=ts)
            _buckets[route] = bucket
        bucket.refill(ts)
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return 0.0
        deficit = 1.0 - bucket.tokens
        return deficit / (limit / 60.0)


def reset() -> None:
    """Forget every bucket (tests)."""
    with _lock:
        _buckets.clear()


def limited(route: str) -> Callable[[], None]:
    """FastAPI dependency factory: ``dependencies=[Depends(limited("x"))]``.
    Over the limit -> 429 with a ``Retry-After`` header (whole seconds,
    rounded up, never 0)."""

    def dependency() -> None:
        wait = try_acquire(route)
        if wait > 0:
            retry_after = max(1, math.ceil(wait))
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many requests to an external-data route "
                    f"({route}) — retry in {retry_after}s."
                ),
                headers={"Retry-After": str(retry_after)},
            )

    dependency.__name__ = f"rate_limit_{route}"
    return dependency
