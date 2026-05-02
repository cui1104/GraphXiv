# GraphXiv

GraphXiv is a local academic-literature ingestion and retrieval system for
turning scholarly PDFs into structured records that can be searched and read by
LLM agents. The project combines a Dockerized backend, parser-routing
experiments, a forked DeepXiv-style SDK/CLI, and cached evaluation artifacts for
citation-aware question answering.

## What Is Included

- `app/`: FastAPI backend, database models, crawler utilities, parser tasks,
  and Celery worker entrypoints.
- `benchmark/`: parser benchmark scripts, metric implementations, ground-truth
  JSON, summary CSVs, and findings.
- `cli/` and `graphxiv`: terminal interface for backend checks, BM25 search,
  cached demos, and live question answering.
- `eval/`: curated questions, scoring utilities, cached replay data, and
  evaluation findings.
- `sdk/`: local DeepXiv SDK fork adapted for the GraphXiv backend.
- `report/`: LaTeX source for the practicum report.

Large local database files, downloaded PDFs, Docker volumes, API keys, personal
documents, logs, and generated build outputs are intentionally excluded from the
repository.

## Requirements

- Python 3.11 or newer
- Docker and Docker Compose
- Optional for live LLM runs: `OPENAI_API_KEY`

Install Python dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,eval]"
```

Create a local environment file:

```bash
cp .env.example .env
```

The example values are suitable for local Docker development. Do not commit
`.env` or real API keys.

## Run The Backend

Start the local services:

```bash
docker compose up -d
```

Check that the API is reachable:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## CLI Smoke Tests

Run the doctor command:

```bash
./graphxiv doctor
```

Search the local corpus with BM25:

```bash
./graphxiv search "confusion matrix interpretability" --limit 5
```

Replay a cached citation-aware evaluation example without an API call:

```bash
./graphxiv demo Q001
```

Run a live LLM-backed question-answering comparison:

```bash
export OPENAI_API_KEY=sk-...
./graphxiv ask 2602.19770 "How does this paper extend its cited works?"
```

## Benchmark And Evaluation Artifacts

The parser benchmark summary is stored at:

- `benchmark/results/benchmark.csv`
- `benchmark/FINDINGS.md`

The cached agent evaluation summary is stored at:

- `eval/results/`
- `eval/FINDINGS.md`

Benchmark reruns can require Docker services, local PDFs, parser dependencies,
and LLM/API access depending on the task. Cached replay commands are provided so
the main demo can be inspected without regenerating every artifact.

## Tests

Run the main test suite:

```bash
DATABASE_URL=postgresql://app:changeme@localhost:5432/papers \
REDIS_URL=redis://localhost:6379/0 \
python3 -m pytest
```

The overrides are needed when running tests from the host shell because
`.env.example` and Docker Compose use service names such as `postgres` and
`redis` inside the Compose network. GPU- or parser-heavy experiments are not
required for the unit-test smoke path.

## Report

The practicum report source lives in `report/graphxiv_report.tex`. The generated
PDF is treated as a build artifact and can be regenerated with Tectonic or a
standard LaTeX toolchain.
