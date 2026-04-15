"""Smart parser router and batch dispatcher.

Routes papers to the correct parser Celery chain based on paper_sources.source_type.
Implements dispatch_pending_batch() for 10k-scale fan-out via celery.group (D-12).

D-03 NOTE: The router dispatches arxiv_tar/arxiv papers to parse_latex. If the
archive has no .tex file with \\documentclass, parse_latex itself handles the D-03
branching (counts PDF tables -> routes to pdf_grobid or pdf_mineru). The router
does NOT need a separate D-03 branch -- it is handled inside parse_latex.
"""

import logging
from celery import chain, group, shared_task

logger = logging.getLogger(__name__)


def _build_parse_chain(paper_id: str, source_type: str):
    """Build the correct Celery chain for a paper based on its source_type.

    Chain pattern: parse_X.si(paper_id) | parse_pdf_grobid.si(paper_id)
    Uses .si() immutable signatures to avoid passing large dicts through Redis (Pitfall 7).

    Args:
        paper_id: String UUID of the paper's canonical_id.
        source_type: From paper_sources.source_type -- one of:
            "arxiv_tar", "arxiv" -> parse_latex chain (D-01/D-02 .tex detection;
                                    D-03 no-documentclass routing handled inside parse_latex)
            "pmc_jats", "pmc"   -> parse_jats chain
            "arxiv_pdf", "pdf"  -> parse_pdf_mineru chain

    Returns:
        Celery chain (or single task signature if no GROBID step).
    """
    from app.tasks.parse import parse_latex, parse_jats, parse_pdf_mineru, parse_pdf_grobid

    if source_type in ("arxiv_tar", "arxiv"):
        # parse_latex handles D-01 (arXiv ID filename match), D-02 (largest .tex),
        # D-03 (no documentclass -> table count -> pdf_grobid/pdf_mineru), and
        # D-04 (cascade on TEX2JSON failure) internally.
        return chain(
            parse_latex.si(paper_id),
            parse_pdf_grobid.si(paper_id),
        )
    elif source_type in ("pmc_jats", "pmc"):
        return chain(
            parse_jats.si(paper_id),
            parse_pdf_grobid.si(paper_id),
        )
    elif source_type in ("arxiv_pdf", "pmc_pdf", "pdf"):
        return chain(
            parse_pdf_mineru.si(paper_id),
            parse_pdf_grobid.si(paper_id),
        )
    else:
        logger.warning("Unknown source_type %s for paper %s", source_type, paper_id)
        return None


@shared_task(bind=True, name="app.tasks.router.route_paper", max_retries=0, time_limit=30)
def route_paper(self, paper_id: str) -> dict:
    """Route a single paper to the correct parser chain.

    Reads paper_sources to determine asset type, builds chain, dispatches.
    Per PARSE-05: priority order is TEX2JSON > JATS2JSON > MinerU.
    """
    from app.db import SessionLocal
    from app.models import PaperSource

    session = SessionLocal()
    try:
        # Get all sources for this paper, ordered by priority
        sources = session.query(PaperSource).filter(
            PaperSource.canonical_id == paper_id,
            PaperSource.parse_status == "pending",
        ).all()

        if not sources:
            return {"status": "no_pending_sources", "paper_id": paper_id}

        # Priority: arxiv_tar/arxiv > pmc_jats/pmc > arxiv_pdf/pdf (per PARSE-05)
        priority_order = ["arxiv_tar", "arxiv", "pmc_jats", "pmc", "arxiv_pdf", "pmc_pdf", "pdf"]
        selected = None
        for ptype in priority_order:
            for src in sources:
                if src.source_type == ptype and src.asset_path:
                    selected = src
                    break
            if selected:
                break

        if not selected:
            return {"status": "no_asset", "paper_id": paper_id}

        c = _build_parse_chain(str(paper_id), selected.source_type)
        if c is None:
            return {"status": "unknown_source_type", "source_type": selected.source_type, "paper_id": paper_id}

        c.apply_async()
        return {"status": "dispatched", "source_type": selected.source_type, "paper_id": paper_id}
    except Exception as exc:
        logger.error("Router failed for %s: %s", paper_id, exc)
        return {"status": "router_error", "error": str(exc), "paper_id": paper_id}
    finally:
        session.close()


@shared_task(bind=True, name="app.tasks.router.dispatch_pending_batch", max_retries=0, time_limit=120)
def dispatch_pending_batch(self) -> dict:
    """Fan-out all pending papers in parallel via celery.group (D-12).

    Reads all paper_sources with parse_status=pending, groups by source_type,
    builds chains, dispatches as a single celery.group.
    Uses .si() immutable signatures throughout (Pitfall 7).
    """
    from app.db import SessionLocal
    from app.models import PaperSource

    session = SessionLocal()
    try:
        pending = session.query(PaperSource).filter(
            PaperSource.parse_status == "pending",
            PaperSource.asset_path.isnot(None),
        ).all()

        if not pending:
            return {"status": "no_pending", "count": 0}

        # Group by source_type for logging; build chains
        chains = []
        counts = {"latex": 0, "jats": 0, "pdf": 0, "skipped": 0}

        for ps in pending:
            c = _build_parse_chain(str(ps.canonical_id), ps.source_type)
            if c is not None:
                chains.append(c)
                if ps.source_type in ("arxiv_tar", "arxiv"):
                    counts["latex"] += 1
                elif ps.source_type in ("pmc_jats", "pmc"):
                    counts["jats"] += 1
                else:
                    counts["pdf"] += 1
            else:
                counts["skipped"] += 1

        logger.info(
            "Dispatching %d parse chains: %d latex, %d jats, %d pdf, %d skipped",
            len(chains), counts["latex"], counts["jats"], counts["pdf"], counts["skipped"],
        )

        if chains:
            group(chains).apply_async()

        return {"status": "dispatched", "total": len(chains), **counts}
    except Exception as exc:
        logger.error("Batch dispatch failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        session.close()
