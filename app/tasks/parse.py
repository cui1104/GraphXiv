from celery import shared_task

from app.tasks.parse_helpers import (
    _backslash_ratio_degraded,
    _count_pdf_tables,
    _has_text_layer,
    _sentence_length_degraded,
    _strip_jats_doctype,
)


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_latex",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_latex(self, paper_id: str) -> dict:
    """Parse arXiv .tar.gz via s2orc-doc2json TEX2JSON. Per PARSE-01."""
    import os
    import re
    import shutil
    import tarfile
    import tempfile

    from app.db import SessionLocal
    from app.models import Paper, PaperSource

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        if not paper:
            return {"status": "failed", "reason": "paper_not_found", "paper_id": paper_id}

        ps = session.query(PaperSource).filter(
            PaperSource.canonical_id == paper_id,
            PaperSource.source_type.in_(["arxiv_tar", "arxiv"]),
        ).first()
        if not ps or not ps.asset_path:
            return {"status": "failed", "reason": "no_tar_asset", "paper_id": paper_id}

        asset_path = ps.asset_path
        if not os.path.isabs(asset_path):
            asset_path = os.path.join("/data", asset_path)

        temp_dir = tempfile.mkdtemp(prefix="tex2json_")
        try:
            # --- D-01 / D-02 / D-03: Explicit .tex file detection ---
            # Extract tar to inspect .tex files before calling process_tex_stream
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(asset_path, "r:gz") as tar:
                tar.extractall(extract_dir)

            # Find all .tex files
            tex_files = []
            for root, dirs, files in os.walk(extract_dir):
                for fname in files:
                    if fname.endswith(".tex"):
                        tex_files.append(os.path.join(root, fname))

            # D-01: Primary heuristic -- filename stem matches arXiv ID pattern
            # arXiv IDs: YYMM.NNNNN or YYMM.NNNNNvN (new style), or category/NNNNNNN (old style)
            arxiv_id = paper.arxiv_id  # e.g. "2401.12345" or "2401.12345v2"
            main_tex = None
            if arxiv_id:
                # Strip version suffix for matching: "2401.12345v2" -> "2401.12345"
                arxiv_stem = re.sub(r'v\d+$', '', arxiv_id)
                for tf in tex_files:
                    file_stem = os.path.splitext(os.path.basename(tf))[0]
                    if file_stem == arxiv_stem or file_stem == arxiv_id:
                        # Verify it contains \documentclass
                        with open(tf, "r", errors="ignore") as fh:
                            content = fh.read()
                        if r"\documentclass" in content:
                            main_tex = tf
                            break

            # D-02: Secondary heuristic -- largest .tex with \documentclass
            if main_tex is None:
                candidates = []
                for tf in tex_files:
                    with open(tf, "r", errors="ignore") as fh:
                        content = fh.read()
                    if r"\documentclass" in content:
                        candidates.append((os.path.getsize(tf), tf))
                if candidates:
                    candidates.sort(reverse=True)  # largest first
                    main_tex = candidates[0][1]

            # D-03: No .tex has \documentclass -- route to PDF parser by table count
            if main_tex is None:
                pdf_ps = session.query(PaperSource).filter(
                    PaperSource.canonical_id == paper_id,
                    PaperSource.source_type.in_(["arxiv_pdf", "pdf"]),
                ).first()
                if pdf_ps and pdf_ps.asset_path:
                    pdf_path = pdf_ps.asset_path
                    if not os.path.isabs(pdf_path):
                        pdf_path = os.path.join("/data", pdf_path)
                    table_count = _count_pdf_tables(pdf_path)
                    if table_count <= 3:
                        # Few tables: route to GROBID (lighter, better for text-heavy papers)
                        ps.parse_status = "cascade_to_pdf_grobid"
                        session.commit()
                        from app.tasks.parse import parse_pdf_grobid
                        parse_pdf_grobid.si(paper_id).apply_async()
                        return {
                            "status": "cascade",
                            "reason": "no_documentclass_few_tables",
                            "table_count": table_count,
                            "target": "pdf_grobid",
                            "paper_id": paper_id,
                        }
                    else:
                        # Many tables: route to MinerU (better layout extraction)
                        ps.parse_status = "cascade_to_pdf_mineru"
                        session.commit()
                        from app.tasks.parse import parse_pdf_mineru
                        parse_pdf_mineru.si(paper_id).apply_async()
                        return {
                            "status": "cascade",
                            "reason": "no_documentclass_many_tables",
                            "table_count": table_count,
                            "target": "pdf_mineru",
                            "paper_id": paper_id,
                        }
                # No PDF either -- truly failed
                ps.parse_status = "failed"
                session.commit()
                return {"status": "failed", "reason": "no_documentclass_no_pdf", "paper_id": paper_id}

            # --- Run TEX2JSON on identified main .tex ---
            from doc2json.tex2json.process_tex import process_tex_stream

            with open(asset_path, "rb") as f:
                raw = f.read()
            fname = os.path.basename(asset_path)
            result = process_tex_stream(fname, raw, temp_dir=temp_dir)

            if not isinstance(result, dict) or not result:
                # TEX2JSON failed -- cascade to MinerU if PDF exists (per D-04)
                pdf_ps = session.query(PaperSource).filter(
                    PaperSource.canonical_id == paper_id,
                    PaperSource.source_type.in_(["arxiv_pdf", "pdf"]),
                ).first()
                if pdf_ps:
                    ps.parse_status = "cascade_to_pdf"
                    session.commit()
                    return {"status": "cascade", "reason": "tex2json_empty_result", "paper_id": paper_id}
                ps.parse_status = "failed"
                session.commit()
                return {"status": "failed", "reason": "tex2json_empty_result", "paper_id": paper_id}

            # Backslash quality check (per PARSE-01)
            body_texts = result.get("body_text", [])
            full_text = " ".join(bt.get("text", "") for bt in body_texts)
            quality = "ok"
            if _backslash_ratio_degraded(full_text):
                quality = "degraded"

            # Update DB
            paper.parse_source = "latex"
            paper.parse_quality = quality
            paper.content = result
            ps.parse_status = "success"
            session.commit()

            return {
                "status": "success",
                "parse_source": "latex",
                "parse_quality": quality,
                "paper_id": paper_id,
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as exc:
        session.rollback()
        try:
            ps_row = session.query(PaperSource).filter(
                PaperSource.canonical_id == paper_id
            ).first()
            if ps_row:
                ps_row.parse_status = "failed"
                session.commit()
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        session.close()


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_jats",
    max_retries=3,
    time_limit=60,
    soft_time_limit=50,
    default_retry_delay=10,
)
def parse_jats(self, paper_id: str) -> dict:
    """Parse PMC JATS XML via s2orc-doc2json JATS2JSON. Per PARSE-02."""
    import os
    import shutil
    import tempfile

    from doc2json.jats2json.process_jats import process_jats_stream

    from app.db import SessionLocal
    from app.models import Paper, PaperSource

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        if not paper:
            return {"status": "failed", "reason": "paper_not_found", "paper_id": paper_id}

        ps = session.query(PaperSource).filter(
            PaperSource.canonical_id == paper_id,
            PaperSource.source_type.in_(["pmc_jats", "pmc"]),
        ).first()
        if not ps or not ps.asset_path:
            return {"status": "failed", "reason": "no_jats_asset", "paper_id": paper_id}

        asset_path = ps.asset_path
        if not os.path.isabs(asset_path):
            asset_path = os.path.join("/data", asset_path)

        temp_dir = tempfile.mkdtemp(prefix="jats2json_")
        try:
            with open(asset_path, "rb") as f:
                raw = f.read()

            # MANDATORY: Strip DOCTYPE to prevent lxml DTD fetch hangs (Pitfall 6)
            raw = _strip_jats_doctype(raw)

            fname = os.path.basename(asset_path)
            result = process_jats_stream(fname, raw, temp_dir=temp_dir)

            if not isinstance(result, dict) or not result:
                # JATS2JSON failed -- cascade to MinerU if PDF exists (per D-04)
                pdf_ps = session.query(PaperSource).filter(
                    PaperSource.canonical_id == paper_id,
                    PaperSource.source_type.in_(["arxiv_pdf", "pmc_pdf", "pdf"]),
                ).first()
                if pdf_ps:
                    ps.parse_status = "cascade_to_pdf"
                    session.commit()
                    return {"status": "cascade", "reason": "jats2json_empty_result", "paper_id": paper_id}
                ps.parse_status = "failed"
                session.commit()
                return {"status": "failed", "reason": "jats2json_empty_result", "paper_id": paper_id}

            # Update DB
            paper.parse_source = "jats"
            paper.parse_quality = "ok"
            paper.content = result
            ps.parse_status = "success"
            session.commit()

            return {"status": "success", "parse_source": "jats", "parse_quality": "ok", "paper_id": paper_id}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception as exc:
        session.rollback()
        try:
            ps_row = session.query(PaperSource).filter(
                PaperSource.canonical_id == paper_id
            ).first()
            if ps_row:
                ps_row.parse_status = "failed"
                session.commit()
        except Exception:
            pass
        self.retry(exc=exc)
    finally:
        session.close()


@shared_task(
    bind=True,
    name="app.tasks.parse.parse_pdf_mineru",
    max_retries=3,
    time_limit=300,
    soft_time_limit=270,
    default_retry_delay=30,
)
def parse_pdf_mineru(self, paper_id: str) -> dict:
    """Parse PDF via MinerU (magic-pdf) on slow/GPU queue. Per PARSE-03."""
    import json
    import os
    import shutil
    import tempfile

    from app.db import SessionLocal
    from app.models import Paper, PaperSource

    session = SessionLocal()
    try:
        paper = session.query(Paper).filter(Paper.canonical_id == paper_id).first()
        if not paper:
            return {"status": "failed", "reason": "paper_not_found", "paper_id": paper_id}

        ps = session.query(PaperSource).filter(
            PaperSource.canonical_id == paper_id,
            PaperSource.source_type.in_(["arxiv_pdf", "pmc_pdf", "pdf"]),
        ).first()
        if not ps or not ps.asset_path:
            return {"status": "failed", "reason": "no_pdf_asset", "paper_id": paper_id}

        asset_path = ps.asset_path
        if not os.path.isabs(asset_path):
            asset_path = os.path.join("/data", asset_path)

        # Step 1: pymupdf text-layer pre-check (per PARSE-03)
        if not _has_text_layer(asset_path, threshold=100):
            ps.parse_status = "scanned_skip"
            paper.parse_quality = "scanned"
            session.commit()
            return {"status": "scanned_skip", "reason": "text_layer_below_100_chars", "paper_id": paper_id}

        # Step 2: Run MinerU -- LAZY IMPORTS (Pitfall 3: prevent ImportError on fast workers)
        from magic_pdf.config.enums import SupportedPdfParseMethod
        from magic_pdf.data.data_reader_writer import FileBasedDataWriter
        from magic_pdf.data.dataset import PymuDocDataset
        from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

        output_dir = tempfile.mkdtemp(prefix="mineru_")
        try:
            image_dir = os.path.join(output_dir, "images")
            os.makedirs(image_dir, exist_ok=True)

            image_writer = FileBasedDataWriter(image_dir)
            output_writer = FileBasedDataWriter(output_dir)

            with open(asset_path, "rb") as f:
                pdf_bytes = f.read()

            ds = PymuDocDataset(pdf_bytes)
            if ds.classify() == SupportedPdfParseMethod.OCR:
                infer_result = ds.apply(doc_analyze, ocr=True)
                pipe_result = infer_result.pipe_ocr_mode(image_writer)
            else:
                infer_result = ds.apply(doc_analyze, ocr=False)
                pipe_result = infer_result.pipe_txt_mode(image_writer)

            pipe_result.dump_content_list(output_writer, "content_list.json", "images")
            content_list_path = os.path.join(output_dir, "content_list.json")

            with open(content_list_path) as f:
                content_list = json.load(f)

            if not content_list:
                ps.parse_status = "failed"
                session.commit()
                return {"status": "failed", "reason": "mineru_empty_result", "paper_id": paper_id}

            # Step 3: Post-parse sentence-length degradation check (per PARSE-05)
            all_text = " ".join(
                item.get("text", "") for item in content_list if item.get("type") == "text"
            )
            quality = "ok"
            if _sentence_length_degraded(all_text, threshold=80):
                quality = "degraded"

            # Step 4: Update DB -- store raw content_list (Phase 4 normalizes)
            # NOTE: text_level is always 1 in OSS MinerU (Pitfall 5) -- Phase 4 must handle this
            paper.parse_source = "pdf_mineru"
            paper.parse_quality = quality
            paper.content = {"content_list": content_list, "parser": "mineru", "text_level_broken": True}
            ps.parse_status = "success"
            session.commit()

            return {
                "status": "success",
                "parse_source": "pdf_mineru",
                "parse_quality": quality,
                "paper_id": paper_id,
            }
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)
    except Exception as exc:
        session.rollback()
        try:
            ps_row = session.query(PaperSource).filter(
                PaperSource.canonical_id == paper_id
            ).first()
            if ps_row:
                ps_row.parse_status = "failed"
                session.commit()
        except Exception:
            pass
        self.retry(exc=exc)
    finally:
        session.close()


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
