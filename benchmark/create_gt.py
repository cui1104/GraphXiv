"""Ground-truth extraction via Gemini vision — Phase 7 (GT schema v2).

For each paper in benchmark/sample.json, render up to 10 PDF pages as PNG (120 DPI),
send to gemini-2.5-flash with a structured prompt, and cache the response to
benchmark/gt/{paper_id}.json.

GT schema v2 (plan 07-02.5):
    {
      "paper_id": "...",
      "arxiv_id": "...",
      "model": "gemini-2.5-flash",
      "headings": [
        {"text": "Introduction",       "sec_num": "1"},
        {"text": "Related Work",       "sec_num": "2"},
        {"text": "Proposed Method",    "sec_num": "3"},
        {"text": "Architecture",       "sec_num": "3.1"},
        ...
      ],
      "figure_count": 5,
      "formula_count": 12,
      "reference_count": 42,
      "page_count": 10
    }

Idempotent:
  - skips papers with v2 schema already on disk (headings is list of dicts with
    both "text" and "sec_num", AND figure_count/formula_count/reference_count top-
    level ints present).
  - FORCES re-extraction of v1 flat-list files (headings = [str, ...]) so the
    cache is upgraded in place when this script is re-run after plan 07-02.5.
  - Use --force to re-extract regardless of on-disk schema.
  - Files with an "error" key are always retried.
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
GT_DIR = os.path.join(os.path.dirname(__file__), "gt")
MODEL_ID = "gemini-2.5-flash"
MAX_PAGES = 10
DPI = 120
MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 10

logger = logging.getLogger("create_gt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROMPT = (
    "You are reading an academic paper (rendered page-by-page as images). "
    "Extract the paper's structural inventory and return it as a single JSON object.\n\n"
    "Required JSON keys (exact spelling, no extra top-level keys):\n"
    "  - \"headings\": a JSON array of section-heading objects, in the order the "
    "headings appear in the paper. Each object has keys:\n"
    "      \"text\"    : the heading text WITHOUT leading numbering/punctuation "
    "(so '3.1. Architecture' -> 'Architecture').\n"
    "      \"sec_num\" : the numeric/dotted section number as a STRING exactly as "
    "printed (so 'Introduction' in section 1 -> \"1\"; 'Architecture' in 3.1 -> "
    "\"3.1\"). If the paper prints NO explicit number for that heading, use the "
    "empty string \"\".\n"
    "  - \"figure_count\": INTEGER count of distinct figures (including sub-figures "
    "labelled 1a, 1b, ... count each label once). Do not include tables.\n"
    "  - \"formula_count\": INTEGER count of displayed (numbered or centered) equations. "
    "Do not count inline math.\n"
    "  - \"reference_count\": INTEGER count of entries in the References / Bibliography "
    "list. Count each numbered or bulleted entry once.\n\n"
    "Rules:\n"
    "  - Do NOT include the paper title in headings.\n"
    "  - Do NOT include figure/table captions in headings.\n"
    "  - Do NOT include commentary, prose, or markdown fences.\n"
    "  - Your entire response MUST be valid JSON, beginning with '{' and ending with '}'.\n"
    "  - Numbers must be JSON numbers (no quotes around integers).\n"
    "  - If the paper is truncated (only first ~10 pages are visible), still do your "
    "best with what's visible.\n\n"
    "Example response:\n"
    "{\"headings\": [{\"text\": \"Introduction\", \"sec_num\": \"1\"}, "
    "{\"text\": \"Related Work\", \"sec_num\": \"2\"}, "
    "{\"text\": \"Our Approach\", \"sec_num\": \"3\"}, "
    "{\"text\": \"Network Architecture\", \"sec_num\": \"3.1\"}], "
    "\"figure_count\": 4, \"formula_count\": 8, \"reference_count\": 27}"
)


def _load_sample() -> list:
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_v2_schema(data: dict) -> bool:
    """True iff data matches GT schema v2.

    Required: headings is a list of dicts with "text" (non-empty) AND "sec_num"
    keys, AND figure_count/formula_count/reference_count top-level ints present.
    A v1 flat-list file (headings = [str, str, ...]) returns False — forces
    re-extraction under the new schema.
    """
    if not isinstance(data, dict):
        return False
    if "error" in data:
        return False
    headings = data.get("headings")
    if not isinstance(headings, list):
        return False
    for h in headings:
        if not isinstance(h, dict):
            return False
        if "text" not in h or "sec_num" not in h:
            return False
    for key in ("figure_count", "formula_count", "reference_count"):
        if not isinstance(data.get(key), int):
            return False
    return True


def _cached_ok(paper_id: str) -> bool:
    """True iff the cache file exists AND is schema v2 (plan 07-02.5).

    Old v1 caches (headings = [str, ...]) return False so a re-run of this
    script re-extracts them with the v2 prompt.
    """
    path = os.path.join(GT_DIR, f"{paper_id}.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        return _is_v2_schema(data)
    except Exception:
        return False


def _write_cache(paper_id: str, data: dict) -> None:
    os.makedirs(GT_DIR, exist_ok=True)
    path = os.path.join(GT_DIR, f"{paper_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _render_pdf_pages(pdf_path: str, max_pages: int = MAX_PAGES, dpi: int = DPI) -> list:
    """Render first max_pages pages of PDF as PNG byte strings."""
    import pymupdf  # type: ignore[import-untyped]
    doc = pymupdf.open(pdf_path)
    try:
        out = []
        n = min(max_pages, len(doc))
        for i in range(n):
            pix = doc[i].get_pixmap(dpi=dpi)
            out.append(pix.tobytes("png"))
        return out
    finally:
        doc.close()


def _parse_response_text(text: str) -> dict:
    """Strip markdown fences and parse Gemini response into v2 GT payload.

    Returns dict with keys:
        headings:         list of {"text": str, "sec_num": str}, both present, text non-empty
        figure_count:     int (>= 0)
        formula_count:    int (>= 0)
        reference_count:  int (>= 0)

    Raises ValueError if the response is not a JSON object with the expected
    shape (caller retries or records as error).
    """
    text = text.strip()
    # Strip markdown fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.lower().startswith("json\n"):
            text = text[5:]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")

    raw_headings = parsed.get("headings")
    if not isinstance(raw_headings, list):
        raise ValueError("response 'headings' is not a list")

    headings = []
    for h in raw_headings:
        if isinstance(h, dict):
            t = str(h.get("text") or "").strip()
            sn = str(h.get("sec_num") if h.get("sec_num") is not None else "").strip()
        elif isinstance(h, str):
            # Defensive: model occasionally returns bare strings despite the prompt.
            # Treat as text with empty sec_num so we don't lose the heading entirely.
            t = h.strip()
            sn = ""
        else:
            continue
        if not t:
            continue
        headings.append({"text": t, "sec_num": sn})

    def _as_int(v, key):
        if isinstance(v, bool):  # bool is a subclass of int; reject explicitly
            raise ValueError(f"'{key}' must be an integer, got bool")
        if isinstance(v, int):
            return max(0, v)
        if isinstance(v, float) and v.is_integer():
            return max(0, int(v))
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            return max(0, int(v.strip()))
        raise ValueError(f"'{key}' must be an integer, got {type(v).__name__}: {v!r}")

    figure_count = _as_int(parsed.get("figure_count"), "figure_count")
    formula_count = _as_int(parsed.get("formula_count"), "formula_count")
    reference_count = _as_int(parsed.get("reference_count"), "reference_count")

    return {
        "headings": headings,
        "figure_count": figure_count,
        "formula_count": formula_count,
        "reference_count": reference_count,
    }


def extract_gt_payload(pdf_path: str, client) -> tuple:
    """Send rendered pages to Gemini, return (payload_dict, pages_sent).

    payload_dict has keys {headings, figure_count, formula_count, reference_count}
    per the GT v2 schema (Plan 07-02.5).

    Retries on transient API errors (up to MAX_RETRIES). Raises on final failure.
    """
    from google.genai import types  # type: ignore[import-untyped]

    pngs = _render_pdf_pages(pdf_path)
    parts = [types.Part.from_bytes(data=png, mime_type="image/png") for png in pngs]
    parts.append(PROMPT)

    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(model=MODEL_ID, contents=parts)
            text = response.text
            return _parse_response_text(text), len(pngs)
        except Exception as exc:
            last_exc = exc
            logger.warning("Gemini API attempt %d failed: %s", attempt + 1, exc)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_SLEEP_SECONDS * (attempt + 1))
    raise RuntimeError(f"Gemini API failed after {MAX_RETRIES} attempts: {last_exc}")


# Backward compatibility alias — some callers still import the old name.
extract_gt_headings = extract_gt_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract every paper regardless of cache (ignores v2-shape check).",
    )
    args = parser.parse_args()

    sample = _load_sample()
    if args.limit:
        sample = sample[: args.limit]

    def _already_cached(paper_id: str) -> bool:
        if args.force:
            return False
        return _cached_ok(paper_id)

    if args.dry_run:
        pending = [e for e in sample if not _already_cached(e["paper_id"])]
        print(
            f"[create_gt] dry-run — would process {len(pending)} papers "
            f"(of {len(sample)}; {len(sample) - len(pending)} cached) "
            f"{'[--force enabled, ignores cache]' if args.force else ''}"
        )
        return 0

    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY env var not set. See https://console.cloud.google.com", file=sys.stderr)
        return 2

    from google import genai  # type: ignore[import-untyped]
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    os.makedirs(GT_DIR, exist_ok=True)
    done, skipped, errored, upgraded = 0, 0, 0, 0
    for i, entry in enumerate(sample, 1):
        paper_id = entry["paper_id"]
        if _already_cached(paper_id):
            skipped += 1
            logger.info("[%d/%d] %s — v2 cached, skip", i, len(sample), paper_id)
            continue
        # Detect v1→v2 upgrade for nicer logging (doesn't change behavior —
        # _already_cached already returned False for v1-shape files).
        cache_path = os.path.join(GT_DIR, f"{paper_id}.json")
        was_v1 = False
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as _f:
                    _prev = json.load(_f)
                if (
                    isinstance(_prev, dict)
                    and "error" not in _prev
                    and isinstance(_prev.get("headings"), list)
                    and _prev["headings"]
                    and isinstance(_prev["headings"][0], str)
                ):
                    was_v1 = True
            except Exception:
                pass
        pdf_path = entry["pdf_path"]
        if not os.path.exists(pdf_path):
            logger.warning("[%d/%d] %s — pdf missing: %s", i, len(sample), paper_id, pdf_path)
            _write_cache(paper_id, {"paper_id": paper_id, "arxiv_id": entry.get("arxiv_id"), "error": f"pdf_missing: {pdf_path}"})
            errored += 1
            continue
        try:
            payload, pages_sent = extract_gt_payload(pdf_path, client)
            _write_cache(paper_id, {
                "paper_id": paper_id,
                "arxiv_id": entry.get("arxiv_id"),
                "model": MODEL_ID,
                "schema_version": 2,
                "headings": payload["headings"],
                "figure_count": payload["figure_count"],
                "formula_count": payload["formula_count"],
                "reference_count": payload["reference_count"],
                "page_count": pages_sent,
            })
            done += 1
            if was_v1:
                upgraded += 1
            logger.info(
                "[%d/%d] %s — %d headings, fig=%d form=%d ref=%d%s",
                i, len(sample), paper_id,
                len(payload["headings"]),
                payload["figure_count"],
                payload["formula_count"],
                payload["reference_count"],
                " (v1→v2 upgrade)" if was_v1 else "",
            )
        except Exception as exc:
            errored += 1
            _write_cache(paper_id, {
                "paper_id": paper_id,
                "arxiv_id": entry.get("arxiv_id"),
                "error": str(exc),
            })
            logger.exception("[%d/%d] %s — failed", i, len(sample), paper_id)

    print(
        f"[create_gt] done={done} (of which v1->v2 upgraded={upgraded}) "
        f"v2_cached={skipped} errored={errored} total={len(sample)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
