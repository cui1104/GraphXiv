from celery import shared_task


@shared_task(
    bind=True,
    name="app.tasks.ingest.ingest_paper",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def ingest_paper(self, paper_id: str) -> dict:
    """Stub: Phase 2 implements arXiv/PMC metadata ingestion."""
    return {"status": "stub", "paper_id": paper_id}


@shared_task(
    bind=True,
    name="app.tasks.ingest.download_asset",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def download_asset(self, paper_id: str, source_type: str) -> dict:
    """Stub: Phase 2 implements asset download (tar.gz or PDF)."""
    return {"status": "stub", "paper_id": paper_id, "source_type": source_type}
