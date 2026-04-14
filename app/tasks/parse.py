from app.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="app.tasks.parse.parse_latex",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_latex(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements LaTeX → structured JSON parsing."""
    return {"status": "stub", "paper_id": paper_id, "parse_source": "latex"}


@celery_app.task(
    bind=True,
    name="app.tasks.parse.parse_jats",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_jats(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements JATS XML → structured JSON parsing."""
    return {"status": "stub", "paper_id": paper_id, "parse_source": "jats"}


@celery_app.task(
    bind=True,
    name="app.tasks.parse.parse_pdf_mineru",
    max_retries=3,
    time_limit=300,
    soft_time_limit=270,
    default_retry_delay=30,
)
def parse_pdf_mineru(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements PDF → structured JSON via MinerU (GPU-accelerated)."""
    return {"status": "stub", "paper_id": paper_id, "parse_source": "pdf_mineru"}


@celery_app.task(
    bind=True,
    name="app.tasks.parse.parse_pdf_grobid",
    max_retries=3,
    time_limit=300,
    soft_time_limit=270,
    default_retry_delay=30,
)
def parse_pdf_grobid(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements PDF → structured JSON via GROBID."""
    return {"status": "stub", "paper_id": paper_id, "parse_source": "pdf_grobid"}
