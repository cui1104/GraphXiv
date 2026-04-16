"""Redis cache utilities for cache-aside pattern.

Implements D-14 through D-17 from 05-CONTEXT.md:
- D-14: Cache-aside pattern: check Redis -> hit: return cached JSON -> miss: query DB
- D-15: Cache key format: papers:{canonical_id}:{view}
- D-16: Search cache key: search:{md5(q+limit+search_mode)}, TTL 300s
- D-17: Paper view TTL: 3600s; search TTL: 300s
"""
from __future__ import annotations

import hashlib
import json

from redis.asyncio import Redis

PAPER_TTL = 3600   # 1 hour (D-17)
SEARCH_TTL = 300   # 5 minutes (D-17)


async def get_cached(redis: Redis, key: str) -> dict | None:
    """Check Redis for a cached value; return parsed dict or None on miss.

    Args:
        redis: Async Redis client.
        key: Cache key to look up.

    Returns:
        Parsed dict if cache hit, None if miss.
    """
    cached = await redis.get(key)
    if cached:
        return json.loads(cached)
    return None


async def set_cache(redis: Redis, key: str, data: dict, ttl: int) -> None:
    """Serialize and store a dict in Redis with the given TTL.

    Uses json.dumps(default=str) to handle UUID and datetime serialization.

    Args:
        redis: Async Redis client.
        key: Cache key.
        data: Dict to serialize and cache.
        ttl: Time-to-live in seconds.
    """
    await redis.set(key, json.dumps(data, default=str), ex=ttl)


def paper_cache_key(canonical_id: str, view: str) -> str:
    """Build cache key for a paper view (D-15).

    Args:
        canonical_id: Paper's canonical UUID as string.
        view: View name — one of: head, brief, sections, full, references, cited_by, related.

    Returns:
        Cache key string: papers:{canonical_id}:{view}
    """
    return f"papers:{canonical_id}:{view}"


def search_cache_key(q: str, limit: int, search_mode: str) -> str:
    """Build cache key for a search query (D-16).

    Key is an MD5 of the raw query parameters to keep key length bounded.

    Args:
        q: Search query string.
        limit: Result limit.
        search_mode: One of bm25, vector, hybrid.

    Returns:
        Cache key string: search:{md5(q:limit:search_mode)}
    """
    raw = f"{q}:{limit}:{search_mode}"
    md5 = hashlib.md5(raw.encode()).hexdigest()
    return f"search:{md5}"
