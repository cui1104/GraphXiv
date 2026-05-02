# Phase 3: Parser Layer - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

All three parsing paths (TEX2JSON, JATS2JSON, MinerU + GROBID) produce structured JSON output
from real papers, with quality flags and `parse_source` recorded. The output of each path is raw
parser JSON — normalization to the unified PaperJSON schema happens in Phase 4.

Delivers: `parse_latex`, `parse_jats`, `parse_pdf_mineru` Celery tasks (replacing stubs), GROBID
client task, and a smart router that builds the correct Celery chain per paper based on available
`paper_sources` asset type.

</domain>

<decisions>
## Implementation Decisions

### TEX file detection (multi-file `.tar.gz` archives)
- **D-01:** Primary heuristic — filename matches arXiv ID (e.g., `2401.12345.tex`). If found with `\documentclass`, use it.
- **D-02:** Secondary heuristic — largest `.tex` file containing `\documentclass` wins when no filename-match exists.
- **D-03:** No `.tex` file has `\documentclass` at all → inspect the associated PDF:
  - Count detected tables in PDF (via pymupdf or heuristic on page layout)
  - **Few tables (≤3):** route to GROBID path (`parse_source=pdf_grobid`)
  - **Many tables (>3):** route to MinerU path (`parse_source=pdf_mineru`)
  - Record `parse_source` accordingly; do NOT mark as `failed` — these papers still get parsed.

### Fallback cascading (parse failure behavior)
- **D-04 (Claude's discretion):** Cascade on failure to maximize corpus coverage for the 10k batch.
  - TEX2JSON fails → if a PDF asset exists for the same paper, cascade to MinerU automatically.
  - JATS2JSON fails → if a PDF asset exists, cascade to MinerU automatically.
  - MinerU fails → mark `parse_status=failed`, no further fallback (already the last resort).
  - Cascading is logged with original failure reason so degradation is visible in `parse_quality`.

### MinerU environment and parallelization
- **D-05 (Claude's discretion):** MinerU runs on the existing Celery slow/GPU queue (already has `runtime: nvidia` in Docker Compose). No separate container needed.
- **D-06 (Claude's discretion):** For the 10k batch execution, experiment with Celery worker concurrency on the slow queue:
  - Start with `concurrency=1` (GPU exclusive) to measure throughput baseline.
  - Try `concurrency=2` if GPU VRAM allows — MinerU holds ~4–6GB; 24GB GPU can likely run 2 in parallel.
  - Use `celery group` to dispatch all MinerU tasks in parallel batches rather than sequential dispatch.
  - If GPU throughput is insufficient, evaluate PySpark as a batch alternative for the MinerU path only (PySpark can distribute across multiple VM nodes if available). Document findings.

### GROBID coupling
- **D-07 (Claude's discretion):** GROBID runs synchronously inside each Celery chain (parse → GROBID refs → store) but is **non-blocking on failure**.
  - If GROBID times out or returns an error: store the paper with `citations=[]`, do NOT retry the whole chain.
  - GROBID timeout is set to 30s per paper (well within the 300s slow-queue time limit).
  - This keeps citation data co-located with the parse result without serializing the entire 10k batch through GROBID.

### Raw parser output format — CRITICAL note for Phase 4
- **D-08:** MinerU JSON and GROBID TEI XML output **flat section lists** — section 3 and section 3.1 appear as siblings, not parent/child. The section hierarchy is NOT represented in raw output.
- **D-09:** Phase 4 normalizer MUST implement hierarchy reconstruction before writing to PostgreSQL:
  - Parse `sec_num` strings (e.g., "3", "3.1", "3.1.2") to build the tree.
  - Assign `parent_sec_num` or nest sections inside their parent's `paragraphs`.
  - This applies to MinerU and GROBID paths; s2orc-doc2json (TEX2JSON/JATS2JSON) may already preserve hierarchy — verify before assuming.
- **D-10:** All three parser outputs (s2orc S2ORC JSON, MinerU JSON, GROBID TEI XML) normalize to the **same PaperJSON schema** in Phase 4. Phase 3 tasks return raw parser output — do NOT attempt normalization inside Phase 3 tasks.

### s2orc-doc2json installation
- **D-11:** Install from GitHub HEAD (`git+https://github.com/allenai/s2orc-doc2json`) — no stable PyPI release exists. Pin to a specific commit SHA in `pyproject.toml` for reproducibility.

### Parallelization for 10k batch
- **D-12:** Use `celery group` to fan out all `pending` papers in parallel rather than dispatching tasks one-by-one.
  - Router reads all `paper_sources` rows with `parse_status=pending`, groups them by asset type, and dispatches a `celery.group` per parser type.
  - This saturates all available Celery workers (fast queue for LaTeX/JATS, slow queue for MinerU) concurrently.
  - PySpark is a fallback option if Celery throughput on the VM proves insufficient — document the comparison.

### Claude's Discretion
- Exact pymupdf table-count heuristic threshold calibration
- MinerU concurrency tuning (start at 1, tune up)
- GROBID HTTP client implementation details (httpx with 30s timeout)
- Temp directory cleanup strategy for `.tar.gz` extraction

</decisions>

<specifics>
## Specific Ideas

- "If no LaTeX source, check table count in the PDF to decide GROBID vs MinerU" — this avoids running the heavy MinerU model on simple text-heavy papers that GROBID handles well.
- For 10k batch: use parallelization (Celery group) or PySpark — experiment and document which is faster on the VM.
- s2orc-doc2json S2ORC output format is already reasonably structured for hierarchy; MinerU/GROBID are the ones that need hierarchy reconstruction in Phase 4.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs committed to this repo — requirements are fully captured in decisions above and referenced docs.

### Parsing requirements
- `.planning/REQUIREMENTS.md` §Parsing — PARSE-01 through PARSE-05
- `.planning/ROADMAP.md` §Phase 3 — success criteria and 4-plan breakdown with exact task specs

### Prior phase context (locked decisions)
- `.planning/phases/01-foundation/01-CONTEXT.md` — Celery queue config (fast/slow), `parse_source` values, `parse_quality` values, DB schema for `papers` and `paper_sources`
- `.planning/STATE.md` — all prior implementation decisions (shared_task pattern, queue routing, etc.)

### Phase 4 dependency (read before finalizing Phase 3 output schema)
- `.planning/ROADMAP.md` §Phase 4 — normalizer takes Phase 3 raw output; Phase 3 tasks must return dicts that Phase 4 can consume without re-reading files from disk.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/tasks/parse.py` — 4 Celery stubs already exist with correct queue assignments, time limits, and `shared_task` decorator. Phase 3 fills in the bodies only.
- `app/tasks/ingest.py` — Pattern for DB session usage (`SessionLocal`, query → update → commit → close) and lazy imports — reuse this pattern in parse tasks.
- `app/models.py` — `PaperSource.asset_path` and `PaperSource.source_type` are the fields the router reads to determine which parser to invoke. `PaperSource.parse_status` is updated to `success/failed` after parsing.
- `app/db.py` — `SessionLocal` factory for synchronous DB access from Celery tasks.

### Established Patterns
- `shared_task` decorator (not `celery_app.task`) for all tasks — avoids circular imports.
- Lazy imports inside function bodies for tasks developed in parallel (see `ingest.py` lazy PMC import).
- `self.retry(exc=exc)` pattern for task-level retries on unexpected exceptions.
- Asset files stored under `./data/` bind mount — all file paths in `paper_sources.asset_path` are relative to this mount point.

### Integration Points
- Router (03-04) reads `paper_sources` to find asset type per paper → dispatches correct parser chain.
- Parser tasks update `paper_sources.parse_status` and write raw parsed JSON (returned as task result or stored to a temp path for Phase 4 to consume).
- GROBID service is already `always-on` in `docker-compose.yml` at `http://grobid:8070` (internal Docker network hostname).

</code_context>

<deferred>
## Deferred Ideas

- PySpark batch runner — evaluate if Celery group throughput on VM is insufficient; full PySpark integration is a separate decision, not Phase 3 scope.
- GPU concurrency tuning beyond `concurrency=2` — tune in Phase 3 execution, not planning.
- Phase 4 hierarchy reconstruction implementation — explicitly Phase 4 (normalizer). Captured in D-08/D-09 above as a mandatory requirement for the Phase 4 planner.
- Nougat parser — out of scope per REQUIREMENTS.md (no CPU fallback, .mmd format).
- Table HTML rendering — v2 requirement (EXT-03).

</deferred>

---

*Phase: 03-parser-layer*
*Context gathered: 2026-04-15*
