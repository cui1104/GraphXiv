"""Ground-truth heading extraction via Gemini vision — Phase 7.

For each paper in benchmark/sample.json, render up to 10 PDF pages as PNG (120 DPI),
send to gemini-2.0-flash with a structured prompt, parse the JSON list of headings,
and cache to benchmark/gt/{paper_id}.json.

Idempotent: skips papers where the cache file already exists and contains "headings" key
(a cache file with "error" key is NOT skipped — it will be retried).
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
MODEL_ID = "gemini-2.0-flash"
MAX_PAGES = 10
DPI = 120
MAX_RETRIES = 3
RETRY_SLEEP_SECONDS = 10

logger = logging.getLogger("create_gt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PROMPT = (
    "Extract all section headings from this academic paper in the order they appear. "
    "Return ONLY a JSON array of strings, e.g. [\"Introduction\", \"Related Work\", \"Methods\"]. "
    "Include numbered headings WITHOUT the leading numbers (so '3. Methods' -> 'Methods'). "
    "Do not include the paper title. Do not include figure/table captions. "
    "Do not include commentary. Your response must begin with '[' and end with ']'."
)


def _load_sample() -> list:
    with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _cached_ok(paper_id: str) -> bool:
    path = os.path.join(GT_DIR, f"{paper_id}.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            data = json.load(f)
        return "headings" in data and isinstance(data["headings"], list)
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


def _parse_response_text(text: str) -> list:
    """Strip markdown fences and parse JSON array."""
    text = text.strip()
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
    if not isinstance(parsed, list):
        raise ValueError(f"expected JSON array, got {type(parsed)}")
    return [str(h).strip() for h in parsed if str(h).strip()]


def extract_gt_headings(pdf_path: str, client) -> tuple:
    """Send rendered pages to Gemini, return (headings, pages_sent).

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    sample = _load_sample()
    if args.limit:
        sample = sample[: args.limit]

    if args.dry_run:
        pending = [e for e in sample if not _cached_ok(e["paper_id"])]
        print(f"[create_gt] dry-run — would process {len(pending)} papers (of {len(sample)}; {len(sample) - len(pending)} cached)")
        return 0

    if not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY env var not set. See https://console.cloud.google.com", file=sys.stderr)
        return 2

    from google import genai  # type: ignore[import-untyped]
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    os.makedirs(GT_DIR, exist_ok=True)
    done, skipped, errored = 0, 0, 0
    for i, entry in enumerate(sample, 1):
        paper_id = entry["paper_id"]
        if _cached_ok(paper_id):
            skipped += 1
            logger.info("[%d/%d] %s — cached, skip", i, len(sample), paper_id)
            continue
        pdf_path = entry["pdf_path"]
        if not os.path.exists(pdf_path):
            logger.warning("[%d/%d] %s — pdf missing: %s", i, len(sample), paper_id, pdf_path)
            _write_cache(paper_id, {"paper_id": paper_id, "arxiv_id": entry.get("arxiv_id"), "error": f"pdf_missing: {pdf_path}"})
            errored += 1
            continue
        try:
            headings, pages_sent = extract_gt_headings(pdf_path, client)
            _write_cache(paper_id, {
                "paper_id": paper_id,
                "arxiv_id": entry.get("arxiv_id"),
                "model": MODEL_ID,
                "headings": headings,
                "page_count": pages_sent,
            })
            done += 1
            logger.info("[%d/%d] %s — extracted %d headings", i, len(sample), paper_id, len(headings))
        except Exception as exc:
            errored += 1
            _write_cache(paper_id, {
                "paper_id": paper_id,
                "arxiv_id": entry.get("arxiv_id"),
                "error": str(exc),
            })
            logger.exception("[%d/%d] %s — failed", i, len(sample), paper_id)

    print(f"[create_gt] done={done} cached={skipped} errored={errored} total={len(sample)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
