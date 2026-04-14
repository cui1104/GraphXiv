from celery import shared_task


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_latex",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_latex(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements TEX2JSON via s2orc-doc2json."""
    return {"status": "stub", "parser": "latex", "paper_id": paper_id}


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_jats",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_jats(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements JATS2JSON via s2orc-doc2json."""
    return {"status": "stub", "parser": "jats", "paper_id": paper_id}


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_pdf_mineru",
    max_retries=3,
    time_limit=300,
    soft_time_limit=270,
    default_retry_delay=30,
)
def parse_pdf_mineru(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements MinerU PDF parsing on slow/GPU queue."""
    return {"status": "stub", "parser": "pdf_mineru", "paper_id": paper_id}


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_pdf_grobid",
    max_retries=3,
    time_limit=300,
    soft_time_limit=270,
    default_retry_delay=30,
)
def parse_pdf_grobid(self, paper_id: str) -> dict:
    """Stub: Phase 3 implements GROBID reference extraction."""
    return {"status": "stub", "parser": "pdf_grobid", "paper_id": paper_id}
