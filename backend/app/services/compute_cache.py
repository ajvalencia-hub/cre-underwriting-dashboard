"""LRU cache over engine.compute (H13).

The engine is pure (inputs dict -> result dict), so identical inputs can
reuse the previous result. Two safety rules:
- Keys are the canonical JSON of the inputs (sort_keys), so dict ordering
  never splits the cache.
- Hits return a DEEP COPY — callers (memo, deck, share) may mutate the
  result, and a poisoned cache would be a correctness bug, not a perf bug.
"""

import copy
import json
from collections import OrderedDict
from threading import Lock

from app.services.proforma import engine

MAX_ENTRIES = 128

_cache: OrderedDict[str, dict] = OrderedDict()
_lock = Lock()
_stats = {"hits": 0, "misses": 0}


def _key(inputs: dict) -> str | None:
    try:
        return json.dumps(inputs, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None  # unserializable inputs: just don't cache


def cached_compute(inputs: dict) -> dict:
    key = _key(inputs)
    if key is None:
        return engine.compute(inputs)

    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            _stats["hits"] += 1
            return copy.deepcopy(_cache[key])

    result = engine.compute(inputs)  # outside the lock: computes may be slow

    with _lock:
        _stats["misses"] += 1
        _cache[key] = copy.deepcopy(result)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)
    return result


def cache_stats() -> dict:
    with _lock:
        return {**_stats, "entries": len(_cache)}


def clear() -> None:
    with _lock:
        _cache.clear()
        _stats["hits"] = 0
        _stats["misses"] = 0
