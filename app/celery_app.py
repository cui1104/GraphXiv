from celery import Celery
from kombu import Queue
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "app",
    include=["app.tasks.ingest", "app.tasks.parse", "app.tasks.normalize"],
)

celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_queues=(
        Queue("fast"),
        Queue("slow"),
    ),
    task_default_queue="fast",
    task_routes={
        "app.tasks.ingest.*": {"queue": "fast"},
        "app.tasks.parse.parse_latex": {"queue": "fast"},
        "app.tasks.parse.parse_jats": {"queue": "fast"},
        "app.tasks.parse.parse_pdf_mineru": {"queue": "slow"},
        "app.tasks.parse.parse_pdf_grobid": {"queue": "slow"},
        "app.tasks.normalize.*": {"queue": "fast"},
    },
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)
