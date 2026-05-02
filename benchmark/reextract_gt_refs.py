"""Re-extract reference_count for every GT file from the FULL PDF text.

The original GT (create_gt.py) caps at 10 pages, so papers >10 pages get
reference_count=0 (references live at the end of the paper, past the cap).
78% of our sample exceeds 10 pages; 63% of GT files had reference_count=0 —
all 94 of them were long papers. This rewrites just the reference_count field
using a full-PDF regex scan; every other GT field is preserved as-is.

Heuristic:
  1. Extract text from ALL pages via pymupdf.
  2. Find the LAST "References" / "Bibliography" / "Works Cited" heading.
  3. In the tail text, count numbered reference entries — three formats:
     - `[N]` bracketed:   `[1] Smith, J. ...`
     - `N.` numeric:      `1. Smith, J. ...`
     - `(N)` parenthesized: `(1) Smith, J. ...`
  4. Pick the format with the most matches (papers stick to one style).
  5. If no References heading is found, fall back to scanning tail 30%.

This is a lower bound on the true count (author-year style papers without
numbered refs still score 0). Applied uniformly to GT + every parser's
extractor, so relative comparisons stay fair.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

import pymupdf  # type: ignore[import-untyped]

GT_DIR = os.path.join(os.path.dirname(__file__), "gt")
SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "sample.json")
BACKUP_SUFFIX = ".pre_ref_fix.bak"

_REF_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+\.?\s+)?(references?|bibliography|works\s+cited)\s*\n",
    re.IGNORECASE,
)
_BRACKET_RE = re.compile(r"(?:^|\n)\s*\[\s*\d+\s*\]\s+[A-Z]")
_NUMBERED_RE = re.compile(r"(?:^|\n)\s*\d+\.\s+[A-Z]")
_PAREN_RE = re.compile(r"(?:^|\n)\s*\(\s*\d+\s*\)\s+[A-Z]")
# Author-year entry: line starts with "Lastname, I." or "Lastname-Hyphen, I.A."
# optionally followed by ", YYYY" or ", Year." — covers APA/Harvard/Chicago styles.
_AUTHOR_YEAR_RE = re.compile(
    r"(?:^|\n)\s*[A-Z][a-zA-Z\-]{1,}(?:\s*,\s*[A-Z]\.(?:[A-Z]\.)?(?:,|\s+and|\s+&)?)+"
)


def count_refs_in_text(text: str) -> tuple[int, str]:
    """Return (count, format_tag) where format_tag is bracket/number/paren/authoryear/none."""
    if not text:
        return 0, "none"
    # Locate the last References heading; scan forward from there.
    matches = list(_REF_HEADING_RE.finditer(text))
    tail = text[matches[-1].end():] if matches else text[int(len(text) * 0.7):]
    candidates = {
        "bracket": len(_BRACKET_RE.findall(tail)),
        "number": len(_NUMBERED_RE.findall(tail)),
        "paren": len(_PAREN_RE.findall(tail)),
        "authoryear": len(_AUTHOR_YEAR_RE.findall(tail)),
    }
    tag, count = max(candidates.items(), key=lambda kv: kv[1])
    return count, (tag if count > 0 else "none")


def extract_pdf_text(pdf_path: str) -> str:
    doc = pymupdf.open(pdf_path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def main() -> int:
    with open(SAMPLE_PATH) as f:
        sample = json.load(f)
    id_to_pdf = {e["paper_id"]: e["pdf_path"] for e in sample}

    gt_files = [fn for fn in sorted(os.listdir(GT_DIR)) if fn.endswith(".json")]
    print(f"Scanning {len(gt_files)} GT files against full PDFs...")

    before_zero = 0
    after_zero = 0
    changed = 0
    total = 0
    fmt_counts: dict[str, int] = {"bracket": 0, "number": 0, "paren": 0, "none": 0}

    for fn in gt_files:
        paper_id = fn.replace(".json", "")
        gt_path = os.path.join(GT_DIR, fn)
        with open(gt_path) as f:
            data = json.load(f)
        if "error" in data:
            continue
        total += 1
        old = int(data.get("reference_count") or 0)
        if old == 0:
            before_zero += 1

        pdf_path = id_to_pdf.get(paper_id)
        if not pdf_path or not os.path.exists(pdf_path):
            continue

        try:
            text = extract_pdf_text(pdf_path)
        except Exception as exc:
            print(f"  [warn] {paper_id[:8]}: pdf read failed: {exc}")
            continue

        new, tag = count_refs_in_text(text)
        fmt_counts[tag] = fmt_counts.get(tag, 0) + 1

        if new != old:
            # Back up once, then overwrite.
            backup = gt_path + BACKUP_SUFFIX
            if not os.path.exists(backup):
                shutil.copy2(gt_path, backup)
            data["reference_count"] = new
            data["reference_count_source"] = "full_pdf_regex"
            data["reference_count_format"] = tag
            with open(gt_path, "w") as f:
                json.dump(data, f, indent=2)
            changed += 1

        if new == 0:
            after_zero += 1

        if changed <= 5 and new != old:
            print(f"  {paper_id[:8]}: {old} -> {new} ({tag})")

    print()
    print(f"total GT files:        {total}")
    print(f"reference_count==0 before: {before_zero} ({100*before_zero/total:.0f}%)")
    print(f"reference_count==0 after:  {after_zero} ({100*after_zero/total:.0f}%)")
    print(f"rows changed:          {changed}")
    print(f"format distribution:   {fmt_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
