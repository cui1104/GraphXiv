"""Re-extract figure_count for every GT file from the FULL PDF text.

Mirrors reextract_gt_refs.py. The original GT (create_gt.py) caps at 10 pages,
so long papers under-count figures/formulas that appear past page 10. On smoke
test paper 2 (37 pages), GT said fig=1/form=13 but all three parsers agreed on
fig=16-21/form=26-27 — three independent parsers converging is a strong signal
the GT undercounts.

Figures: scan full PDF text for "Figure N" / "Fig. N" / "Fig N" caption anchors,
take MAX figure number seen. Papers number figures sequentially 1..N, so max(N)
is a tight lower bound. On paper 2e7b7c80, this fixed 1 -> 17 (parsers: 16-21).

Formulas: NOT rewritten. Max-equation-number heuristic was tried and rejected —
it zeroed out papers with unnumbered display math, papers that use "(1.1)" style
labels, or papers that number citations like equations. On paper 2e7b7c80 the
heuristic produced 0 when parsers counted 26-27. Formula_count stays at Gemini's
10-page estimate (known lower bound); document as a caveat in FINDINGS.

Applied uniformly to GT only — parsers keep their existing extractors (which
read parser-native output: MinerU content_list, TEI <figure>, Docling doc.pictures).
GT is the only side with the 10-page cap bug.
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
BACKUP_SUFFIX = ".pre_figform_fix.bak"
_DATA_DIR = os.environ.get("DATA_DIR", "")


def _remap_pdf_path(path: str) -> str:
    """Same as run_benchmark._remap_pdf_path — sample.json stores host paths."""
    if not _DATA_DIR or os.path.exists(path):
        return path
    marker = os.sep + "data" + os.sep
    idx = path.find(marker)
    if idx != -1:
        rel = path[idx + len(marker):]
        return os.path.join(_DATA_DIR, rel)
    return path

_FIGURE_CAPTION_RE = re.compile(
    r"(?:^|\n)\s*(?:Figure|Fig\.?)\s+(\d+)[:.\s]",
    re.IGNORECASE,
)


def count_figures_in_text(text: str) -> int:
    """Return max figure number seen in caption positions, 0 if none found."""
    if not text:
        return 0
    nums = [int(m.group(1)) for m in _FIGURE_CAPTION_RE.finditer(text)]
    nums = [n for n in nums if 1 <= n <= 100]
    return max(nums) if nums else 0


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

    total = 0
    fig_changed = 0
    fig_before_zero = 0
    fig_after_zero = 0
    fig_deltas: list[tuple[str, int, int]] = []

    for fn in gt_files:
        paper_id = fn.replace(".json", "")
        gt_path = os.path.join(GT_DIR, fn)
        with open(gt_path) as f:
            data = json.load(f)
        if "error" in data:
            continue
        total += 1
        old_fig = int(data.get("figure_count") or 0)
        if old_fig == 0:
            fig_before_zero += 1

        raw_pdf = id_to_pdf.get(paper_id) or ""
        pdf_path = _remap_pdf_path(raw_pdf)
        if not pdf_path or not os.path.exists(pdf_path):
            continue

        try:
            text = extract_pdf_text(pdf_path)
        except Exception as exc:
            print(f"  [warn] {paper_id[:8]}: pdf read failed: {exc}")
            continue

        new_fig = count_figures_in_text(text)

        if new_fig != old_fig:
            backup = gt_path + BACKUP_SUFFIX
            if not os.path.exists(backup):
                shutil.copy2(gt_path, backup)
            data["figure_count"] = new_fig
            data["figure_count_source"] = "full_pdf_regex"
            fig_changed += 1
            fig_deltas.append((paper_id[:8], old_fig, new_fig))
            with open(gt_path, "w") as f:
                json.dump(data, f, indent=2)

        if new_fig == 0:
            fig_after_zero += 1

    print()
    print(f"total GT files:             {total}")
    print(f"figure_count==0 before:     {fig_before_zero} ({100*fig_before_zero/total:.0f}%)")
    print(f"figure_count==0 after:      {fig_after_zero} ({100*fig_after_zero/total:.0f}%)")
    print(f"figure rows changed:        {fig_changed}")
    print()
    print("Sample fig deltas (first 10):")
    for pid, o, n in fig_deltas[:10]:
        print(f"  {pid}: fig {o} -> {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
