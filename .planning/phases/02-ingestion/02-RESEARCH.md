# Phase 2: Ingestion - Research

**Researched:** 2026-04-14
**Domain:** OAI-PMH harvesting, async HTTP crawling, arXiv/PMC APIs, Celery task integration
**Confidence:** HIGH (primary claims verified against official docs; see sources)

---

## Summary

Phase 2 builds two independent OAI-PMH crawlers (arXiv and PMC) that harvest metadata and download assets for ~10,000 deep learning papers. Both crawlers write resumptionTokens to the `crawl_state` table after each page so they can survive restarts. The arXiv crawler uses httpx + tenacity for async requests and enforces a 3 req/sec token-bucket via `aiolimiter`. The PMC crawler uses the synchronous `sickle` library, which already handles resumptionToken iteration internally, but the harvester must persist the token manually at each page boundary to survive premature stops.

The biggest operational surprise is the **arXiv OAI-PMH endpoint change** (March 2025): the canonical base URL is now `https://oaipmh.arxiv.org/oai`, not `http://export.arxiv.org/oai2`. The set-name format also changed to hierarchical `group:archive:CATEGORY` (e.g. `cs:cs:LG`). Tokens now expire daily and no longer carry `completeListSize` or `cursor` attributes. The PMC endpoint also changed (October 2024) to `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/`; it returns only **10 records per ListRecords page**, meaning a 10,000-paper harvest requires ~1,000+ pages.

For the "deep learning subset" in PMC, there is no dedicated subject set — the correct approach is to harvest `set=pmc-open` with a date range (`from`/`until`) and filter by MeSH terms or title keywords post-harvest, or accept the full open-access corpus and discard non-DL papers during normalization.

**Primary recommendation:** Use `aiolimiter.AsyncLimiter(3, 1)` for arXiv (async), sickle with manual token checkpoint for PMC (sync, wrapped in a thread executor if needed), and `httpx` for e-print asset download with Content-Type routing to distinguish `.tar.gz` from `.pdf`.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INGEST-01 | arXiv OAI-PMH crawler: cs.LG/AI/CV/CL/stat.ML, 3 req/sec token-bucket, User-Agent | arXiv endpoint, set names, rate limit policy confirmed; aiolimiter pattern documented |
| INGEST-02 | arXiv asset downloader: fetch e-print, Content-Type routing (tar.gz vs PDF), save to disk | Exact URL, Content-Type values, routing logic confirmed from official docs |
| INGEST-03 | PMC OAI-PMH crawler: JATS XML harvest, resumptionToken persisted after every page | PMC endpoint, metadataPrefix=pmc, sickle API, page-size (10) confirmed |
| INGEST-04 | Crawl resumability: stop/restart without re-harvesting already-processed IDs | crawl_state table schema confirmed; dedup check pattern documented |
| INGEST-05 | arXiv ID normalization: version suffix stripped, v2 update existing record | ID format confirmed; regex pattern documented |
| INGEST-06 | Corpus reaches ~10,000 papers (parse_status=pending) | PMC has 10/page; arXiv has batches ~1000+; volume targets confirmed feasible |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | Async HTTP client for arXiv OAI-PMH + e-print download | Native asyncio support, timeout/redirect control, no monkey-patching |
| tenacity | 9.1.4 | Retry decorator with exponential backoff | Handles 429/503; async-native `@retry` decorator; standard pattern for resilient scrapers |
| aiolimiter | 1.2.1 | Asyncio-native token-bucket rate limiter | `AsyncLimiter(3, 1)` — exactly 3 tokens per 1 second window; leaky-bucket semantics prevent burst |
| sickle | 0.7.0 | OAI-PMH Python client for PMC harvest | Handles resumptionToken iteration; simplest correct approach; synchronous (wrap in executor) |
| lxml | 6.0.4 | XML parsing for arXiv arXivRaw / PMC JATS payloads | Fastest Python XML parser; already available; sickle depends on it |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy | 2.0.49 | Async DB writes to `papers`, `paper_sources`, `crawl_state` | Already in project; use `postgresql+psycopg2` for sync, or async session for async paths |
| xmltodict | 1.0.4 | Convert arXivRaw XML to dict for metadata extraction | Optional; simpler than lxml ElementTree for small metadata records |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiolimiter | hand-rolled token bucket | aiolimiter is 10 lines vs 50; less risk of off-by-one in sleep math |
| sickle (sync) | httpx async OAI-PMH from scratch | sickle eliminates resumptionToken parsing boilerplate; sync is fine for a one-shot crawler process |
| httpx for arXiv OAI | requests | requests is sync-only; httpx allows async crawl loop natively |

**Installation:**
```bash
pip install httpx==0.28.1 tenacity==9.1.4 aiolimiter==1.2.1 sickle==0.7.0 lxml==6.0.4
```

---

## Architecture Patterns

### Recommended Project Structure
```
app/
├── crawler/
│   ├── __init__.py
│   ├── arxiv_oai.py        # async arXiv OAI-PMH harvester
│   ├── arxiv_assets.py     # async arXiv e-print downloader
│   ├── pmc_oai.py          # sync PMC OAI-PMH harvester (sickle)
│   └── utils.py            # token-bucket, ID normalization, dedup helpers
data/
├── assets/
│   ├── arxiv/              # {arxiv_id}.tar.gz or {arxiv_id}.pdf
│   └── pmc/                # {pmc_id}.xml (JATS inline payload)
```

### Pattern 1: Async arXiv OAI-PMH Harvest with Rate Limiter

**What:** Use httpx `AsyncClient` + `aiolimiter.AsyncLimiter` to page through `ListRecords` for each target set. Persist `resumptionToken` to `crawl_state` after every page.

**When to use:** All arXiv OAI-PMH requests (02-01).

```python
# Source: aiolimiter docs (https://aiolimiter.readthedocs.io/) + httpx docs
import httpx
from aiolimiter import AsyncLimiter

ARXIV_OAI_BASE = "https://oaipmh.arxiv.org/oai"
ARXIV_SETS = ["cs:cs:LG", "cs:cs:AI", "cs:cs:CV", "cs:cs:CL", "stat:stat:ML"]
USER_AGENT = "DATS5990-ResearchKG/1.0 (mailto:your@email.edu)"

limiter = AsyncLimiter(3, 1)  # 3 tokens per 1 second

async def fetch_page(client: httpx.AsyncClient, params: dict) -> httpx.Response:
    async with limiter:
        return await client.get(
            ARXIV_OAI_BASE,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

async def harvest_set(set_name: str, from_date: str | None = None):
    params = {"verb": "ListRecords", "set": set_name, "metadataPrefix": "arXivRaw"}
    if from_date:
        params["from"] = from_date
    async with httpx.AsyncClient() as client:
        while True:
            resp = await fetch_page(client, params)
            # parse XML, extract records, upsert to DB
            token = extract_resumption_token(resp.text)
            persist_token_to_crawl_state(set_name, token)  # after every page
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}
```

### Pattern 2: tenacity Retry on arXiv Requests

**What:** Wrap the HTTP call with tenacity to handle transient 429/503 from arXiv.

**When to use:** All OAI-PMH and e-print requests (02-01, 02-02).

```python
# Source: tenacity docs (https://tenacity.readthedocs.io/)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    reraise=True,
)
async def fetch_with_retry(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    resp = await client.get(url, **kwargs)
    resp.raise_for_status()  # triggers HTTPStatusError on 4xx/5xx
    return resp
```

### Pattern 3: arXiv e-Print Asset Download with Content-Type Routing

**What:** Fetch `https://export.arxiv.org/e-print/{id}`, inspect `Content-Type` header to route to `.tar.gz` (LaTeX source) or `.pdf` path.

**When to use:** 02-02 asset downloader.

```python
# Source: https://info.arxiv.org/help/mimetypes.html (official arXiv docs)
EPRINT_URL = "https://export.arxiv.org/e-print/{arxiv_id}"
DATA_DIR = "/data/assets/arxiv"

CONTENT_TYPE_TO_EXT = {
    "application/x-eprint-tar": ".tar.gz",   # multi-file LaTeX (most common)
    "application/x-eprint": ".tar.gz",        # single-file TeX (also gzipped)
    "application/pdf": ".pdf",
    "application/postscript": ".ps.gz",       # rare; treat as fallback
}

async def download_asset(arxiv_id: str, client: httpx.AsyncClient) -> tuple[str, str]:
    """Returns (asset_path, source_type). source_type is 'latex' or 'pdf'."""
    url = EPRINT_URL.format(arxiv_id=arxiv_id)
    async with limiter:
        resp = await client.get(url, follow_redirects=True, timeout=60.0)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "").split(";")[0].strip()
    ext = CONTENT_TYPE_TO_EXT.get(ct, ".bin")
    source_type = "latex" if "eprint" in ct else "pdf"
    path = f"{DATA_DIR}/{arxiv_id}{ext}"
    with open(path, "wb") as f:
        f.write(resp.content)
    return path, source_type
```

### Pattern 4: PMC Harvest with sickle + Manual Token Checkpoint

**What:** Use `sickle.Sickle` to iterate over PMC records. After each batch (sickle makes one HTTP call per resumptionToken), manually persist the current token to `crawl_state`. Separate harvest (write all PMC IDs) from processing (download/enqueue) to prevent token expiry during slow processing.

**When to use:** 02-03 PMC OAI-PMH crawler.

```python
# Source: sickle docs (https://sickle.readthedocs.io/en/latest/tutorial.html)
from sickle import Sickle
from sickle.iterator import OAIItemIterator

PMC_OAI_BASE = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"

def harvest_pmc_ids(from_date: str | None = None, resumption_token: str | None = None):
    """Phase 1: page all PMC IDs, checkpointing token after every page."""
    sickle = Sickle(PMC_OAI_BASE, timeout=30)
    kwargs = {"metadataPrefix": "pmc_fm", "set": "pmc-open"}
    if from_date:
        kwargs["from"] = from_date
    if resumption_token:
        # Resume from checkpoint: pass token directly as first request
        kwargs = {"resumptionToken": resumption_token}

    records = sickle.ListRecords(**kwargs)
    # sickle auto-handles resumptionToken between pages, but we need token BEFORE
    # iterating to next page — access internal iterator state
    for record in records:
        pmc_id = record.header.identifier  # "oai:pubmedcentral.nih.gov:PMCNNNNN"
        yield pmc_id
        # After each page boundary (sickle fetches next page internally),
        # persist token from records.resumption_token
        token = getattr(records, "resumption_token", None)
        if token:
            save_crawl_state("pmc", token.token if hasattr(token, "token") else str(token))
```

**Critical detail:** PMC `ListRecords` with `metadataPrefix=pmc` returns only **10 records per page**. For ~10,000 papers this means ~1,000 HTTP requests. At 3 req/sec, this takes ~5-6 minutes minimum. Use `metadataPrefix=pmc_fm` for the harvest phase (IDs only, faster), then fetch full records in the processing phase.

### Pattern 5: arXiv ID Normalization

**What:** Strip version suffixes from arXiv IDs before inserting. Both old (`hep-th/9901001`) and new (`2401.00001`) formats must be handled.

**When to use:** Every arXiv ID ingested (INGEST-05).

```python
# Source: https://info.arxiv.org/help/arxiv_identifier_for_services.html
import re

# New format (post April 2007): YYMM.NNNNN[vN]
# Old format (pre April 2007): archive/YYMMNNNvN
_NEW_ID = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$", re.IGNORECASE)
_OLD_ID = re.compile(r"^([a-z\-]+/\d{7})(v\d+)?$", re.IGNORECASE)

def normalize_arxiv_id(raw_id: str) -> str:
    """Strip version suffix. Returns canonical ID without 'v' suffix."""
    raw_id = raw_id.strip()
    # Strip common prefixes like "arXiv:"
    if raw_id.lower().startswith("arxiv:"):
        raw_id = raw_id[6:]
    m = _NEW_ID.match(raw_id) or _OLD_ID.match(raw_id)
    if m:
        return m.group(1)
    return raw_id  # Unknown format — return as-is, log warning
```

### Pattern 6: crawl_state Upsert

**What:** Use PostgreSQL `ON CONFLICT DO UPDATE` to upsert one row per source into `crawl_state`, keyed on `source`. This is idempotent and safe to call after every page.

**When to use:** After every OAI-PMH page in both crawlers.

```python
# Source: SQLAlchemy 2.0 docs — dialects/postgresql insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models import CrawlState

def save_crawl_state(session, source: str, token: str | None, count: int = 0):
    stmt = pg_insert(CrawlState).values(
        source=source,
        resumption_token=token,
        record_count=count,
        last_harvested_at=func.now(),
    ).on_conflict_do_update(
        index_elements=["source"],
        set_={
            "resumption_token": token,
            "record_count": CrawlState.record_count + count,
            "last_harvested_at": func.now(),
        }
    )
    session.execute(stmt)
    session.commit()
```

**Note:** `crawl_state` table currently has no UNIQUE constraint on `source` — the migration must add one (or use `id` + a query). The planner should add a `UniqueConstraint("source")` in a Phase 2 migration if it is not present.

### Anti-Patterns to Avoid

- **Iterating OAI-PMH without checkpointing:** If you call `for record in sickle.ListRecords(...)` and crash on page 37, you restart from page 1. Always persist the token *before* processing the batch.
- **Using `export.arxiv.org/oai2` as the base URL:** This was deprecated in April 2007 and has a new canonical at `https://oaipmh.arxiv.org/oai` (March 2025). The old URL still redirects but may break.
- **Fetching full `metadataPrefix=pmc` for PMC IDs during harvest:** At 10 records/page, pulling full JATS XML during harvest burns time and increases timeout risk. Harvest IDs with `pmc_fm`, then batch-process.
- **Blocking the event loop with sickle:** sickle is synchronous (uses `requests` under the hood). Run it in `asyncio.get_event_loop().run_in_executor(None, harvest_fn)` or in a separate thread/process if the rest of the pipeline is async.
- **Storing arXiv versioned IDs (`2401.00001v2`) as canonical:** INGEST-05 requires version suffix stripped; the `papers.arxiv_id` UNIQUE constraint will fail on re-ingestion of the same paper at a new version if you store `v1`/`v2`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OAI-PMH resumptionToken pagination | Custom pagination loop | sickle | sickle handles empty tokens, deleted records, HTTP retry; edge cases in token spec are subtle |
| Async rate limiting | `asyncio.sleep` loop | aiolimiter.AsyncLimiter | Token-bucket math is error-prone; aiolimiter is battle-tested, handles burst correctly |
| HTTP retry with backoff | `for attempt in range(N)` | tenacity | Exception routing, jitter, reraise semantics; hard to get right manually |
| XML namespace stripping | Custom regex | lxml.etree with namespace-aware xpath | OAI-PMH XML uses default namespaces that trip up naive string search |

**Key insight:** OAI-PMH resumptionTokens are opaque strings — their internal format is server-defined and can change. Never parse them; only store and re-send.

---

## Common Pitfalls

### Pitfall 1: arXiv OAI-PMH Endpoint and Set Name Format Changed (March 2025)
**What goes wrong:** Code using `http://export.arxiv.org/oai2` and set names like `cs.LG` (dot-separated) will fail or get empty results.
**Why it happens:** arXiv rewrote their OAI service in March 2025. New base URL is `https://oaipmh.arxiv.org/oai`. New set format is `cs:cs:LG` (colon-separated, `group:archive:CATEGORY`).
**How to avoid:** Use the new base URL. Verify set names by calling `verb=ListSets` first.
**Warning signs:** Empty `ListRecords` responses or HTTP 400 "badArgument" errors with category-style set names.

### Pitfall 2: arXiv resumptionToken Has No completeListSize (Post March 2025)
**What goes wrong:** Code checking `token.completeListSize` to calculate progress will get `None` or AttributeError.
**Why it happens:** arXiv explicitly removed `completeListSize` and `cursor` from resumptionTokens in March 2025.
**How to avoid:** Track progress by counting records inserted; don't rely on `completeListSize`. Token still expires daily — must complete harvest within one calendar day or restart from last checkpoint.
**Warning signs:** `AttributeError` on token.completeListSize; or progress bar showing 0%.

### Pitfall 3: PMC ListRecords Returns Only 10 Records Per Page
**What goes wrong:** Harvest loop appears to hang or takes orders of magnitude longer than expected; estimated completion time is wildly off.
**Why it happens:** PMC reduced page size from 50 to 10 in the new API (`/api/oai/v1/mh/`). 10,000 papers = 1,000+ HTTP requests at 3 req/sec = ~6 minutes minimum just for page fetches.
**How to avoid:** Use `metadataPrefix=pmc_fm` (front matter only) for the initial ID harvest; only pull full `metadataPrefix=pmc` (JATS XML) for papers you actually need.
**Warning signs:** Harvest taking >10 minutes for 1,000 records; each response body only has 10 `<record>` elements.

### Pitfall 4: sickle's Internal Token Inaccessible Mid-Iteration
**What goes wrong:** You iterate with `for record in records:` but can't checkpoint the token before the next page is fetched automatically.
**Why it happens:** sickle fetches the next page transparently when the current page's records are exhausted. By the time you process record 10, it has already fetched page 2.
**How to avoid:** Access `records.resumption_token` (an `OAIResponse` attribute on the iterator) *after each record* from the last position in a page. Alternatively, use `sickle.iterate_by="record"` and check `records.resumption_token.token` after each 10th record. Or: harvest all IDs into a local list first (store in `crawl_state` JSON blob), then process independently.
**Warning signs:** Checkpoint restarts duplicate the last 10 records.

### Pitfall 5: arXiv e-Print Content-Type is `application/x-eprint-tar`, Not `application/x-tar`
**What goes wrong:** Routing logic checking for `application/x-tar` or `application/gzip` misclassifies all LaTeX sources as unknown.
**Why it happens:** arXiv uses a non-standard MIME type `application/x-eprint-tar` for multi-file LaTeX archives.
**How to avoid:** Route on `application/x-eprint-tar` and `application/x-eprint` (single file TeX) → LaTeX path. Only `application/pdf` → PDF path. Log unexpected content types.
**Warning signs:** `source_type` is always `None` or `"unknown"` in `paper_sources`.

### Pitfall 6: crawl_state Table Has No UNIQUE Constraint on `source`
**What goes wrong:** `ON CONFLICT DO UPDATE` upsert on `source` fails with `no unique constraint` error.
**Why it happens:** The Phase 1 schema created `crawl_state` with no unique constraint on `source` (only an autoincrement `id` PK).
**How to avoid:** Add a `UniqueConstraint("source")` to `crawl_state` in a Phase 2 Alembic migration, or use a SELECT-then-INSERT/UPDATE pattern.
**Warning signs:** `sqlalchemy.exc.IntegrityError: no unique constraint` when trying to upsert crawl state.

---

## Code Examples

### arXiv arXivRaw Metadata Fields Available

From `metadataPrefix=arXivRaw`, the XML payload includes:
- `<id>` — arXiv ID without version (e.g. `2401.00001`)
- `<created>` — first submission date
- `<updated>` — last replacement date
- `<authors>` — author names as a single text string
- `<title>` — paper title
- `<abstract>` — paper abstract
- `<categories>` — space-separated list (e.g. `cs.LG cs.AI`)
- `<doi>` — DOI if present
- `<version>` elements — version history with dates
- `<license>` — license URL

Use `metadataPrefix=arXivRaw` (not `arXiv`) to get version history, which is needed to detect when a paper was submitted vs replaced.

### Celery Task Enqueue from Crawler

The existing stub task `download_asset` in `app/tasks/ingest.py` takes `(paper_id, source_type)`. Crawlers should enqueue it after inserting the `PaperSource` record:

```python
# Source: Celery 5.4 docs — Calling Tasks
from app.tasks.ingest import download_asset

# After inserting paper record and getting canonical_id:
download_asset.apply_async(
    args=[str(canonical_id), "arxiv"],
    queue="fast",
)
```

**Important:** Import the task function (not `celery_app.send_task`) so Celery's task routing in `celery_app.conf.task_routes` applies. The task already routes to `fast` queue.

### PMC JATS XML Record Structure

When using `metadataPrefix=pmc`, each record's metadata contains inline NISO JATS XML. Key fields accessible via sickle's `record.metadata`:
- PMC ID: `record.header.identifier` → `oai:pubmedcentral.nih.gov:PMCNNNNN`
- Full JATS XML: available in `record.metadata` as an lxml `Element`
- Strip PMC prefix: `pmc_id = identifier.split(":")[-1]`

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `export.arxiv.org/oai2` base URL | `oaipmh.arxiv.org/oai` | March 2025 | Must update base URL |
| Set names `cs.LG`, `stat.ML` (dot-separated) | `cs:cs:LG`, `stat:stat:ML` (colon-separated) | March 2025 | All category set names changed |
| `resumptionToken` includes `completeListSize` | Token has no cursor or size; expires daily | March 2025 | Can't calculate harvest progress from token |
| `ncbi.nlm.nih.gov/pmc/oai/oai.cgi` | `pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/` | October 2024 | New PMC URL (old redirects) |
| PMC `ListRecords` 50 records/page | 10 records/page | October 2024 | 5x more HTTP requests for same harvest |

**Deprecated/outdated:**
- `export.arxiv.org/oai2`: still redirects but deprecated; new code must use `oaipmh.arxiv.org/oai`
- PMC OAI set names from old documentation: verify current set names with `verb=ListSets` on new endpoint

---

## Open Questions

1. **arXiv "deep learning" category completeness**
   - What we know: 5 target sets (`cs:cs:LG`, `cs:cs:AI`, `cs:cs:CV`, `cs:cs:CL`, `stat:stat:ML`) should yield well over 10,000 papers for recent years
   - What's unclear: whether a date range (`from=2020-01-01`) is needed to cap at ~10,000 or if harvesting all-time will be too large
   - Recommendation: Use `from=2020-01-01` as the start date; this covers most relevant DL literature without harvesting the entire arXiv history

2. **PMC "deep learning" subset identification**
   - What we know: No dedicated DL set exists in PMC OAI; `pmc-open` is the broadest usable set
   - What's unclear: Whether filtering by MeSH terms ("Deep Learning", "Neural Networks, Computer") via OAI is possible, or must be done post-harvest
   - Recommendation: Harvest `pmc-open` with a date range and keyword filter on title/abstract during normalization. MeSH filtering is not directly available via OAI verb parameters.

3. **sickle resumption checkpoint granularity**
   - What we know: sickle fetches the next page transparently; accessing `records.resumption_token` gives the token for the *next* unfetched page
   - What's unclear: Exact attribute path to the token string in sickle 0.7.0 (`records.resumption_token` is an `OAIResponse` or just a string)
   - Recommendation: Verify with `print(type(records.resumption_token))` on first run; fall back to parsing the raw XML response if needed

4. **crawl_state UNIQUE constraint on `source`**
   - What we know: Phase 1 schema has `id` PK autoincrement; no UNIQUE on `source`
   - What's unclear: Whether the planner should add this in a migration or use a SELECT+UPDATE pattern
   - Recommendation: Add `UniqueConstraint("source")` in a Phase 2 Alembic migration (e.g. `02-CRAWL-STATE-UNIQUE.py`) before any crawler code runs

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already in pyproject.toml dev dependencies) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths = ["tests"]) |
| Quick run command | `pytest tests/test_ingest.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INGEST-01 | arXiv OAI-PMH harvests records for cs:cs:LG set | integration (live network) | `pytest tests/test_ingest.py::test_arxiv_oai_harvest_smoke -x` | Wave 0 |
| INGEST-01 | Rate limiter enforces 3 req/sec (unit) | unit | `pytest tests/test_ingest.py::test_rate_limiter -x` | Wave 0 |
| INGEST-01 | User-Agent header present on request | unit (httpx mock) | `pytest tests/test_ingest.py::test_user_agent_header -x` | Wave 0 |
| INGEST-02 | Content-Type routing: tar.gz → latex, pdf → pdf | unit | `pytest tests/test_ingest.py::test_content_type_routing -x` | Wave 0 |
| INGEST-02 | Asset written to disk at correct path | integration | `pytest tests/test_ingest.py::test_asset_download -x` | Wave 0 |
| INGEST-03 | PMC OAI-PMH returns records with PMC identifiers | integration | `pytest tests/test_ingest.py::test_pmc_harvest_smoke -x` | Wave 0 |
| INGEST-04 | Restarting harvest skips already-ingested IDs | unit (DB) | `pytest tests/test_ingest.py::test_dedup_skip -x` | Wave 0 |
| INGEST-05 | arxiv_id normalization strips v1/v2 suffixes | unit | `pytest tests/test_ingest.py::test_normalize_arxiv_id -x` | Wave 0 |
| INGEST-05 | Re-ingesting v2 paper updates existing record | unit (DB) | `pytest tests/test_ingest.py::test_upsert_on_version_update -x` | Wave 0 |
| INGEST-06 | paper_sources row count ≥ 100 after 100-paper test run | integration | `pytest tests/test_ingest.py::test_100_paper_smoke -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_ingest.py -x -q -k "not integration"`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_ingest.py` — all INGEST-* test cases listed above
- [ ] `tests/conftest.py` — add `mock_db_session` and `httpx_mock` fixtures (use `pytest-httpx` for HTTP mocking)
- [ ] Additional dependency: `pytest-httpx` for mocking httpx requests in unit tests

---

## Sources

### Primary (HIGH confidence)
- `https://info.arxiv.org/help/oa/index.html` — arXiv OAI-PMH base URL, set names, resumptionToken changes (March 2025), metadataPrefix options
- `https://info.arxiv.org/help/mimetypes.html` — exact Content-Type values for `/e-print/` endpoint
- `https://info.arxiv.org/help/api/tou.html` — arXiv API rate limit (1 req/3 sec), Terms of Use
- `https://info.arxiv.org/help/arxiv_identifier_for_services.html` — arXiv ID format, version suffix handling
- `https://pmc.ncbi.nlm.nih.gov/tools/oai/` — PMC OAI-PMH new endpoint, page sizes (10/page), rate limit (3 req/sec), set names including `pmc-open`, metadataPrefix options
- `https://aiolimiter.readthedocs.io/` — AsyncLimiter API (verified version 1.2.1 on PyPI)
- `https://tenacity.readthedocs.io/` — retry decorator API (verified version 9.1.4 on PyPI)
- `https://sickle.readthedocs.io/en/latest/` — sickle API (version 0.7.0 on PyPI, latest available)

### Secondary (MEDIUM confidence)
- `https://pypi.org/project/aiolimiter/` — version 1.2.1 confirmed latest
- `https://pypi.org/project/Sickle/` — version 0.7.0 confirmed latest
- WebSearch results confirming arXiv new set format `cs:cs:LG` (March 2025)

### Tertiary (LOW confidence)
- WebSearch result describing sickle's `iterate_by` parameter — needs code verification for exact attribute path to resumption_token string in 0.7.0

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions confirmed on PyPI registry
- Architecture: HIGH — patterns derived from official docs
- arXiv OAI endpoint/set names: HIGH — from official arXiv docs, confirmed March 2025 change
- PMC endpoint/page size: HIGH — from official PMC docs, confirmed October 2024 change
- sickle resumption token attribute path: LOW — needs empirical verification in 0.7.0
- crawl_state UNIQUE constraint gap: HIGH — confirmed by reading app/models.py

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable APIs; arXiv OAI format unlikely to change again soon)
