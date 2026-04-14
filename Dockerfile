FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

CMD ["celery", "-A", "app.celery_app", "worker", "-Q", "fast,slow", "--concurrency=4", "--loglevel=info"]
