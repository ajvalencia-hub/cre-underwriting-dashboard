"""Per-source on-disk cache (default 24h TTL) for the benchmark data sources.

Only successful payloads are cached — an "unavailable" result is retried on
the next request rather than pinning a failure for a day. Cache problems are
never fatal: unreadable/unwritable cache files just mean a refetch.
"""

import json
import re
import time
from collections.abc import Callable

from app.config import STORAGE_ROOT

DEFAULT_TTL_SECONDS = 24 * 3600


def _path_for(key: str):
    cache_dir = STORAGE_ROOT / "cache" / "benchmarks"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", key)
    return cache_dir / f"{safe}.json"


def cached_fetch(
    key: str,
    fetch: Callable[[], dict],
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> dict:
    path = _path_for(key)
    if path.exists():
        try:
            entry = json.loads(path.read_text())
            if time.time() - entry.get("fetchedAt", 0) < ttl_seconds:
                return entry["data"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    data = fetch()
    if isinstance(data, dict) and data.get("dataSource") not in (None, "unavailable"):
        try:
            path.write_text(json.dumps({"fetchedAt": time.time(), "data": data}))
        except OSError:
            pass
    return data
