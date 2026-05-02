"""One-shot notebook builder. Run from repo root: python3 benchmark/notebook/_generate_notebook.py.
Safe to delete after committing analysis.ipynb."""
import json
import os

NOTEBOOK_PATH = os.path.join(os.path.dirname(__file__), "analysis.ipynb")


def cell_md(src: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": src.splitlines(keepends=True) or [src],
    }


def cell_code(src: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": src.splitlines(keepends=True) or [src],
    }


cells = [
    cell_md(
        "# Phase 7 Benchmark — Analysis Notebook (v2)\n\n"
        "Visualizations of `benchmark/results/benchmark.csv` across four parser "
        "conditions (MinerU, GROBID, Docling, Router) under the recall-aware v2 "
        "schema from plan 07-02.5.\n\n"
        "See `benchmark/FINDINGS.md` for the formal report."
    ),
    cell_code(
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "import os\n"
        "\n"
        "# Run from project root or from benchmark/notebook/\n"
        "HERE = os.getcwd()\n"
        "CSV_PATH = os.path.join('..', 'results', 'benchmark.csv') \\\n"
        "    if os.path.basename(HERE) == 'notebook' \\\n"
        "    else os.path.join('benchmark', 'results', 'benchmark.csv')\n"
        "\n"
        "df = pd.read_csv(CSV_PATH)\n"
        "METRIC_COLS = ['heading_precision', 'heading_recall', 'heading_f1',\n"
        "               'hierarchy_f1', 'coherent_section_pct', 'table_presence',\n"
        "               'table_structural_completeness', 'body_token_count',\n"
        "               'sec_per_doc', 'figure_count_parser', 'formula_count_parser',\n"
        "               'reference_count_parser']\n"
        "for c in METRIC_COLS:\n"
        "    df[c] = pd.to_numeric(df[c], errors='coerce')\n"
        "df['error'] = df['error'].fillna('').astype(str)\n"
        "ok = df[df['error'] == '']\n"
        "COND = ['mineru', 'grobid', 'docling', 'router']\n"
        "COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728']\n"
        "print(f'Total rows: {len(df)}; non-errored: {len(ok)}; '\n"
        "      f'conditions: {sorted(df.condition.unique())}')\n"
        "df.head(3)"
    ),
    cell_md("## 1. Heading F1 by Condition (bar chart)"),
    cell_code(
        "fig, ax = plt.subplots(figsize=(7, 4))\n"
        "means = ok.groupby('condition')['heading_f1'].mean().reindex(COND)\n"
        "means.plot(kind='bar', ax=ax, color=COLORS)\n"
        "ax.set_ylabel('Heading F1 (mean)')\n"
        "ax.set_title('Heading F1 by Parser Condition (recall-aware v2)')\n"
        "ax.set_ylim(0, 1)\n"
        "plt.xticks(rotation=0)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 2. Heading Precision vs Recall (grouped bar)"),
    cell_code(
        "pr = ok.groupby('condition')[['heading_precision', 'heading_recall']].mean().reindex(COND)\n"
        "ax = pr.plot(kind='bar', figsize=(8, 4))\n"
        "ax.set_ylabel('Mean')\n"
        "ax.set_title('Heading Precision vs Recall by Condition')\n"
        "ax.set_ylim(0, 1)\n"
        "plt.xticks(rotation=0)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md(
        "## 3. Hierarchy F1 by Condition (router differentiator)\n\n"
        "Per plan 07-02.5, only the router applies `_apply_dot_count_hierarchy`. "
        "Standalone parsers return 0.0 by construction."
    ),
    cell_code(
        "fig, ax = plt.subplots(figsize=(7, 4))\n"
        "h = ok.groupby('condition')['hierarchy_f1'].mean().reindex(COND)\n"
        "h.plot(kind='bar', ax=ax, color=COLORS)\n"
        "ax.set_ylabel('Hierarchy F1 (mean)')\n"
        "ax.set_title('Hierarchy F1 by Condition (router-only builder)')\n"
        "ax.set_ylim(0, max(0.1, h.max() * 1.2))\n"
        "plt.xticks(rotation=0)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 4. Table Quality — Presence vs Structural Completeness (scatter)"),
    cell_code(
        "fig, ax = plt.subplots(figsize=(7, 5))\n"
        "for cond, color in zip(COND, COLORS):\n"
        "    sub = ok[ok['condition'] == cond]\n"
        "    jitter = 0.02 * (hash(cond) % 5 - 2)\n"
        "    ax.scatter(sub['table_presence'] + jitter,\n"
        "               sub['table_structural_completeness'],\n"
        "               alpha=0.4, label=cond, color=color, s=25)\n"
        "ax.set_xlabel('Table Presence (0 or 1, jittered)')\n"
        "ax.set_ylabel('Table Structural Completeness (0.0–1.0)')\n"
        "ax.set_title('Table Extraction Quality')\n"
        "ax.legend()\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 5. Heading F1 Distribution by Condition (box plot)"),
    cell_code(
        "fig, ax = plt.subplots(figsize=(7, 4))\n"
        "data = [ok[ok['condition'] == c]['heading_f1'].dropna().values for c in COND]\n"
        "ax.boxplot(data, labels=['MinerU', 'GROBID', 'Docling', 'Router'])\n"
        "ax.set_ylabel('Heading F1')\n"
        "ax.set_title('Heading F1 Distribution by Parser Condition')\n"
        "ax.set_ylim(0, 1)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 6. Content Richness — Body Token Count per Condition"),
    cell_code(
        "fig, ax = plt.subplots(figsize=(7, 4))\n"
        "data = [ok[ok['condition'] == c]['body_token_count'].dropna().values for c in COND]\n"
        "ax.boxplot(data, labels=['MinerU', 'GROBID', 'Docling', 'Router'])\n"
        "ax.set_ylabel('Body token count')\n"
        "ax.set_title('Body Token Count Distribution by Condition (tiktoken cl100k)')\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 7. Reference Count — Parser vs Ground Truth (bar)"),
    cell_code(
        "fig, ax = plt.subplots(figsize=(8, 4))\n"
        "parser_med = ok.groupby('condition')['reference_count_parser'].median().reindex(COND)\n"
        "gt_med = ok.groupby('condition')['reference_count_gt'].median().reindex(COND)\n"
        "x = range(len(COND))\n"
        "ax.bar([i - 0.2 for i in x], parser_med.values, width=0.4, label='parser', color='#1f77b4')\n"
        "ax.bar([i + 0.2 for i in x], gt_med.values, width=0.4, label='GT', color='#d62728')\n"
        "ax.set_xticks(list(x))\n"
        "ax.set_xticklabels(['MinerU', 'GROBID', 'Docling', 'Router'])\n"
        "ax.set_ylabel('Reference count (median)')\n"
        "ax.set_title('Reference Extraction — Parser vs GT (median per paper)')\n"
        "ax.legend()\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md(
        "## 8. Single- vs Two-Column Breakdown\n\n"
        "The 07-02 corpus contains 0 two-column papers, so the two-column bars "
        "will be empty. This limitation is documented in FINDINGS.md."
    ),
    cell_code(
        "fig, axes = plt.subplots(1, 2, figsize=(12, 4))\n"
        "for ax, metric, title in zip(axes,\n"
        "                             ['heading_f1', 'coherent_section_pct'],\n"
        "                             ['Heading F1', 'Coherent Section %']):\n"
        "    pivot = ok.groupby(['condition', 'column_layout'])[metric].mean().unstack('column_layout')\n"
        "    pivot = pivot.reindex(COND)\n"
        "    pivot.plot(kind='bar', ax=ax)\n"
        "    ax.set_ylabel(metric)\n"
        "    ax.set_title(title)\n"
        "    ax.set_ylim(0, 1)\n"
        "plt.xticks(rotation=0)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
    cell_md("## 9. Per-Condition Error Rate"),
    cell_code(
        "error_rates = df.assign(is_error=(df['error'] != '')).groupby('condition')['is_error'].mean()\n"
        "error_rates = error_rates.reindex(COND)\n"
        "error_rates.plot(kind='bar', figsize=(7, 4), color='#d62728')\n"
        "plt.ylabel('Error rate (fraction)')\n"
        "plt.title('Per-Condition Error Rate')\n"
        "plt.xticks(rotation=0)\n"
        "plt.tight_layout()\n"
        "plt.show()"
    ),
]

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python", "version": "3.11"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

with open(NOTEBOOK_PATH, "w", encoding="utf-8") as f:
    json.dump(notebook, f, indent=1)
print(f"Wrote {NOTEBOOK_PATH} ({len(cells)} cells)")
