from app.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.tasks.normalize.normalize_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def normalize_paper(self, paper_id: str) -> dict:
    """Stub: Phase 4 implements normalization to deepxiv_sdk JSON contract."""
    return {"status": "stub", "paper_id": paper_id}
