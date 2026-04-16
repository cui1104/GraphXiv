"""FastAPI application factory with lifespan management for Redis and embedding model."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise Redis connection and embedding model placeholder.
    Shutdown: close Redis connection cleanly.
    """
    settings = get_settings()
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Embedding model loaded lazily on first search request (avoids startup delay when not searching)
    app.state.embedding_model = None
    app.state.settings = settings
    yield
    await app.state.redis.aclose()


app = FastAPI(
    title="Research Knowledge Graph API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes.arxiv import router as arxiv_router  # noqa: E402
from app.api.routes.pmc import router as pmc_router      # noqa: E402
from app.api.routes.search import router as search_router  # noqa: E402

app.include_router(arxiv_router)
app.include_router(pmc_router)
app.include_router(search_router)


@app.get("/health")
def health():
    return {"status": "ok"}
