FROM python:3.11-slim

WORKDIR /app

# System dependencies for s2orc-doc2json TEX2JSON path
# tralics: LaTeX-to-XML converter (required by process_tex_stream)
# texlive-extra-utils: provides latexpand (required for \input expansion)
# git: required for pip install from git+https:// URLs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tralics \
    texlive-extra-utils \
    git \
    && rm -rf /var/lib/apt/lists/*

# MinerU GPU config -- required for magic-pdf to use CUDA
RUN echo '{"device-mode": "cuda", "models-dir": "/models"}' > /root/magic-pdf.json

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Pre-cache tiktoken cl100k_base encoding to avoid first-run network download inside Docker
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY . .

CMD ["celery", "-A", "app.celery_app", "worker", "-Q", "fast,slow", "--concurrency=4", "--loglevel=info"]
