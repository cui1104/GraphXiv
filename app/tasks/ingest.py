from app.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.tasks.ingest.ingest_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def ingest_paper(self, arxiv_id: str) -> dict:
    """Stub: Phase 2 implements. Returns immediately for Phase 1 verification."""
    return {"status": "stub", "arxiv_id": arxiv_id}
