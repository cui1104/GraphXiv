"""One-off driver for Phase 08-01: ingest arxiv papers end-to-end.

For each arxiv_id, this script:
  1. Looks up canonical_id in ``papers`` (skips if not present).
  2. Ensures an asset is downloaded (``download_asset`` task).
  3. Triggers ``route_paper`` which fans out to parse_* + normalize_paper.
  4. Polls ``papers.content.sections`` until non-empty (or times out).

Intended to run **inside the worker container** (so DATABASE_URL /
REDIS_URL resolve correctly)::

    docker compose exec worker python eval/ingest_for_eval.py \
        --arxiv-ids 2601.18685,2602.10119 --timeout 180

Or ingesting from a file (one arxiv_id per line)::

    docker compose exec worker python eval/ingest_for_eval.py \
        --arxiv-ids-file /tmp/seeds.txt --timeout 180 --workers 4

The script is idempotent: if a paper already has non-empty sections, it is
skipped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))
if os.path.isdir("/app") and "/app" not in sys.path:
    sys.path.insert(0, "/app")

# Support --host mode: when running from the host (not inside worker container),
# ./data/ is the mount, localhost is the service URL, and GROBID is at localhost:8070.
_RUNNING_ON_HOST = not os.path.exists("/.dockerenv")
if _RUNNING_ON_HOST:
    # Force host-side service URLs even if .env says docker-internal hostnames.
    # pydantic-settings prefers os.environ over .env, so explicit assignment wins.
    os.environ["DATABASE_URL"] = os.environ.get(
        "DATABASE_URL_HOST", "postgresql://app:changeme@localhost:5432/papers"
    )
    os.environ["REDIS_URL"] = os.environ.get(
        "REDIS_URL_HOST", "redis://localhost:6379/0"
    )
    os.environ["DATA_DIR"] = os.environ.get("DATA_DIR_HOST", str(_APP_ROOT / "data"))
    os.environ["GROBID_URL"] = os.environ.get(
        "GROBID_URL_HOST", "http://localhost:8070"
    )

from sqlalchemy.orm import Session

# Bind celery current_app at module import so ThreadPool workers inherit it.
from app.celery_app import celery_app  # noqa: E402,F401

# Also override GROBID_URL (hardcoded in app/parsers/grobid.py) for host mode.
if _RUNNING_ON_HOST:
    import app.parsers.grobid as _grobid_mod
    _grobid_mod.GROBID_URL = os.environ.get("GROBID_URL", "http://localhost:8070")

logger = logging.getLogger("ingest_for_eval")


def _resolve_canonical(session: Session, arxiv_id: str):
    """Return (canonical_id, title, n_sections, asset_path_exists) or None."""
    from app.models import Paper, PaperSource

    paper = session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
    if paper is None:
        return None
    sections = (paper.content or {}).get("sections") or []
    ps_list = (
        session.query(PaperSource)
        .filter(PaperSource.canonical_id == paper.canonical_id)
        .all()
    )
    asset_present = any(ps.asset_path for ps in ps_list)
    return {
        "canonical_id": str(paper.canonical_id),
        "arxiv_id": arxiv_id,
        "title": paper.title,
        "n_sections": len(sections),
        "asset_present": asset_present,
        "parse_status_any": any(ps.parse_status == "pending" for ps in ps_list),
    }


def _wait_for_asset(arxiv_id: str, canonical_id: str, timeout_s: int) -> bool:
    """Block until a PaperSource row for this paper has asset_path, or timeout."""
    from app.db import SessionLocal
    from app.models import PaperSource

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        session = SessionLocal()
        try:
            ps = (
                session.query(PaperSource)
                .filter(PaperSource.canonical_id == canonical_id)
                .first()
            )
            if ps and ps.asset_path:
                return True
        finally:
            session.close()
        time.sleep(2)
    return False


def _wait_for_sections(canonical_id: str, timeout_s: int) -> tuple[bool, int, int]:
    """Block until papers.content.sections non-empty. Returns (ok, n_sections, n_refs)."""
    from app.db import SessionLocal
    from app.models import Paper

    deadline = time.time() + timeout_s
    last_n = 0
    while time.time() < deadline:
        session = SessionLocal()
        try:
            paper = (
                session.query(Paper)
                .filter(Paper.canonical_id == canonical_id)
                .first()
            )
            if paper:
                content = paper.content or {}
                sections = content.get("sections") or []
                refs = content.get("references") or content.get("bib_entries") or []
                last_n = len(sections)
                if sections:
                    return True, len(sections), len(refs)
        finally:
            session.close()
        time.sleep(2)
    return False, last_n, 0


def _reset_to_pending(canonical_id: str, status: str = "pending") -> int:
    """Reset paper_source.parse_status so route/parse tasks will re-run.

    ``status="cascade_to_pdf_grobid"`` primes parse_pdf_grobid for PRIMARY mode
    (sections + citations via GROBID only; skips MinerU entirely).
    """
    from app.db import SessionLocal
    from app.models import PaperSource

    session = SessionLocal()
    try:
        rows = (
            session.query(PaperSource)
            .filter(PaperSource.canonical_id == canonical_id)
            .filter(PaperSource.asset_path.isnot(None))
            .all()
        )
        n = 0
        for r in rows:
            r.parse_status = status
            n += 1
        session.commit()
        return n
    finally:
        session.close()


def _ingest_one(
    arxiv_id: str,
    timeout_s: int,
    force_retry: bool = False,
    grobid_only: bool = False,
) -> dict:
    from app.db import SessionLocal
    from app.tasks.ingest import download_asset
    from app.tasks.normalize import normalize_paper
    from app.tasks.parse import parse_pdf_grobid
    from app.tasks.router import route_paper
    from celery import chain

    session = SessionLocal()
    try:
        info = _resolve_canonical(session, arxiv_id)
    finally:
        session.close()

    if info is None:
        return {"arxiv_id": arxiv_id, "status": "not_in_db"}

    canonical_id = info["canonical_id"]

    if info["n_sections"] > 0:
        # Already parsed -- just run regex enrichment to pick up any new in-corpus cites.
        in_corpus_added = _enrich_citations_with_arxiv_regex(canonical_id)
        return {
            "arxiv_id": arxiv_id,
            "canonical_id": canonical_id,
            "status": "already_parsed",
            "n_sections": info["n_sections"],
            "in_corpus_added": in_corpus_added,
        }

    if not info["asset_present"]:
        try:
            celery_app.send_task(
                "app.tasks.ingest.download_asset",
                args=[arxiv_id, "arxiv"],
            )
        except Exception as exc:
            return {"arxiv_id": arxiv_id, "status": "dispatch_download_failed", "error": str(exc)}
        if not _wait_for_asset(arxiv_id, canonical_id, timeout_s):
            return {"arxiv_id": arxiv_id, "status": "asset_timeout"}

    if grobid_only:
        # Inline GROBID parse + normalize -- avoids celery forkpool deadlocks on macOS.
        try:
            result = _grobid_parse_inline(arxiv_id, canonical_id)
        except Exception as exc:
            return {"arxiv_id": arxiv_id, "status": "inline_parse_failed", "error": str(exc)}
        return result

    try:
        if force_retry:
            reset_n = _reset_to_pending(canonical_id)
            if reset_n == 0:
                return {"arxiv_id": arxiv_id, "status": "no_assets_to_retry"}
        celery_app.send_task(
            "app.tasks.router.route_paper",
            args=[canonical_id],
        )
    except Exception as exc:
        return {"arxiv_id": arxiv_id, "status": "dispatch_failed", "error": str(exc)}

    ok, n_sections, n_refs = _wait_for_sections(canonical_id, timeout_s)
    return {
        "arxiv_id": arxiv_id,
        "canonical_id": canonical_id,
        "status": "ok" if ok else "parse_timeout",
        "n_sections": n_sections,
        "n_refs": n_refs,
    }


def _grobid_parse_inline(arxiv_id: str, canonical_id: str) -> dict:
    """Run parse_pdf_grobid PRIMARY mode + normalize_paper fully inline (no celery).

    Mirrors the Celery task logic at app/tasks/parse.py:447-473 and
    app/tasks/normalize.py:33-110, but avoids fork-pool concurrency races
    on macOS Docker Desktop.
    """
    import os

    from app.db import SessionLocal
    from app.models import Paper, PaperSource
    from app.parsers.grobid import extract_fulltext
    from app.tasks import normalize as normalize_mod
    from app.tasks.normalize import normalize_paper

    # Host mode lacks sentence_transformers; skip embedding write to unblock normalize.
    if _RUNNING_ON_HOST:
        normalize_mod._write_embedding = lambda *a, **k: None

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == canonical_id).first()
        if not paper:
            return {"arxiv_id": arxiv_id, "status": "paper_disappeared"}

        ps = (
            session.query(PaperSource)
            .filter(PaperSource.canonical_id == canonical_id)
            .filter(PaperSource.asset_path.isnot(None))
            .first()
        )
        if ps is None:
            return {"arxiv_id": arxiv_id, "status": "no_asset_source"}

        asset_path = ps.asset_path
        data_root = os.environ.get("DATA_DIR", "/data")
        if _RUNNING_ON_HOST and asset_path.startswith("/data/"):
            asset_path = asset_path.replace("/data/", data_root.rstrip("/") + "/", 1)
        elif not os.path.isabs(asset_path):
            asset_path = os.path.join(data_root, asset_path)
        if not asset_path.endswith(".pdf") or not os.path.exists(asset_path):
            return {"arxiv_id": arxiv_id, "status": "no_pdf_file", "path": asset_path}

        sections, fulltext_citations = extract_fulltext(asset_path, timeout=120)
        if not sections:
            return {
                "arxiv_id": arxiv_id,
                "canonical_id": canonical_id,
                "status": "grobid_empty",
                "n_sections": 0,
                "n_refs": len(fulltext_citations),
            }

        from sqlalchemy.orm.attributes import flag_modified

        paper.parse_source = "pdf_grobid"
        paper.parse_quality = "ok"
        # Rebuild as a new dict so SQLAlchemy sees JSONB mutation (pitfall: in-place
        # edits on a JSONB-backed dict do not trigger UPDATE without flag_modified).
        content = dict(paper.content or {})
        content["grobid_sections"] = sections
        content["grobid_citations"] = fulltext_citations
        paper.content = content
        flag_modified(paper, "content")
        ps.parse_status = "success"
        session.commit()
    finally:
        session.close()

    normalize_paper.run(canonical_id, "pdf_grobid")

    in_corpus_added = _enrich_citations_with_arxiv_regex(canonical_id)

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == canonical_id).first()
        cites = (paper.content or {}).get("citations") or []
        n_sections = len((paper.content or {}).get("sections") or [])
        return {
            "arxiv_id": arxiv_id,
            "canonical_id": canonical_id,
            "status": "ok",
            "n_sections": n_sections,
            "n_refs": len(cites),
            "in_corpus_added": in_corpus_added,
        }
    finally:
        session.close()


_ARXIV_RE = None


def _enrich_citations_with_arxiv_regex(canonical_id: str) -> int:
    """Extract arXiv IDs from citation raw_text and upsert/update paper_citations.

    GROBID only extracts DOIs/titles. Many references in CS/ML papers include
    ``arXiv:XXXX.YYYYY`` inline in the raw citation text. This step scans
    ``content.citations[i].raw_text`` and, when an arXiv ID matches our
    ``id_map``, writes a ``paper_citations`` row with ``target_arxiv_id`` and
    ``target_paper_id`` set.

    Returns the number of new in-corpus citations added or updated.
    """
    import re

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db import SessionLocal
    from app.models import IdMap, Paper, PaperCitation

    global _ARXIV_RE
    if _ARXIV_RE is None:
        _ARXIV_RE = re.compile(r"arXiv[:\s]+([0-9]{4}\.[0-9]{4,5})", re.IGNORECASE)

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == canonical_id).first()
        if not paper:
            return 0
        cites = (paper.content or {}).get("citations") or []
        # Gather candidate (raw_text, extracted_aid) pairs
        candidates: list[tuple[str, str]] = []
        for c in cites:
            raw = c.get("raw_text") or ""
            m = _ARXIV_RE.search(raw)
            if m:
                candidates.append((raw, m.group(1)))
        if not candidates:
            return 0
        # Look up which extracted IDs are in our corpus
        extracted_ids = [aid for _, aid in candidates]
        rows = (
            session.query(IdMap)
            .filter(IdMap.arxiv_id.in_(extracted_ids))
            .all()
        )
        aid_to_canon = {r.arxiv_id: r.canonical_id for r in rows}
        if not aid_to_canon:
            return 0
        n_added = 0
        for raw, aid in candidates:
            canon_target = aid_to_canon.get(aid)
            if canon_target is None:
                continue
            stmt = pg_insert(PaperCitation.__table__).values(
                source_paper_id=paper.canonical_id,
                target_paper_id=canon_target,
                target_arxiv_id=aid,
                target_doi=None,
                context_text=raw[:4000],
            ).on_conflict_do_update(
                constraint="uq_paper_citations_source_target_arxiv",
                set_={
                    "target_paper_id": canon_target,
                    "context_text": raw[:4000],
                },
            )
            session.execute(stmt)
            n_added += 1
        session.commit()
        return n_added
    finally:
        session.close()


def _load_ids(args) -> list[str]:
    if args.arxiv_ids:
        return [x.strip() for x in args.arxiv_ids.split(",") if x.strip()]
    if args.arxiv_ids_file:
        lines = Path(args.arxiv_ids_file).read_text().splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    raise SystemExit("must provide --arxiv-ids or --arxiv-ids-file")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arxiv-ids", help="comma-separated arxiv_ids")
    p.add_argument("--arxiv-ids-file", help="file with one arxiv_id per line")
    p.add_argument("--timeout", type=int, default=180, help="per-paper timeout seconds")
    p.add_argument("--workers", type=int, default=4, help="parallel ingestions")
    p.add_argument("--report-out", help="write per-paper JSON report to this path")
    p.add_argument("--force-retry", action="store_true", help="reset parse_status to pending and re-dispatch even if prior parse failed")
    p.add_argument("--grobid-only", action="store_true", help="bypass MinerU; run parse_pdf_grobid in PRIMARY mode + normalize")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ids = _load_ids(args)
    logger.info("ingesting %d papers (workers=%d, timeout=%ds)", len(ids), args.workers, args.timeout)

    results: list[dict] = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_ingest_one, aid, args.timeout, args.force_retry, args.grobid_only): aid
            for aid in ids
        }
        for i, fut in enumerate(as_completed(futures), 1):
            aid = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                import traceback
                r = {
                    "arxiv_id": aid,
                    "status": "exception",
                    "error": str(exc),
                    "trace": traceback.format_exc().splitlines()[-5:],
                }
            results.append(r)
            logger.info(
                "[%d/%d] %s -> %s (sections=%d refs=%d in_corpus=%d)%s",
                i, len(ids), aid, r.get("status"),
                r.get("n_sections", 0), r.get("n_refs", 0),
                r.get("in_corpus_added", 0),
                f" err={r.get('error')}" if r.get("error") else "",
            )
            if r.get("trace"):
                for line in r["trace"]:
                    logger.info("   %s", line)

    elapsed = time.time() - start
    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    logger.info("done in %.1fs: %s", elapsed, status_counts)

    if args.report_out:
        Path(args.report_out).write_text(json.dumps(results, indent=2))
        logger.info("report written to %s", args.report_out)

    ok = sum(1 for r in results if r["status"] in ("ok", "already_parsed"))
    return 0 if ok == len(results) else 2


if __name__ == "__main__":
    sys.exit(main())
