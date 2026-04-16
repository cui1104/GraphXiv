"""FastAPI dependency injection providers for DB session and Redis."""
from __future__ import annotations

from typing import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db import SessionLocal
import redis.asyncio as aioredis


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session, closing it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_redis(request: Request) -> aioredis.Redis:
    """Return the shared aioredis client stored on app.state."""
    return request.app.state.redis
