from __future__ import annotations

import time
from typing import Any


_cache: dict[str, tuple[Any, float]] = {}
TTL = 3600


def get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < TTL:
        return entry[0]
    if entry:
        _cache.pop(key, None)
    return None


def set(key: str, value: Any) -> None:
    _cache[key] = (value, time.time())


def delete(key: str) -> bool:
    return _cache.pop(key, None) is not None


def clear() -> None:
    _cache.clear()
