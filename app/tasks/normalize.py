from celery import shared_task


@shared_task(
    bind=True,
    name="app.tasks.normalize.normalize_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def normalize_paper(self, paper_id: str, parse_source: str) -> dict:
    """Stub: Phase 4 implements PaperJSON normalization + upsert."""
    return {"status": "stub", "paper_id": paper_id, "parse_source": parse_source}
