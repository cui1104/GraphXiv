"""Add UNIQUE constraint on paper_citations(source_paper_id, target_arxiv_id) for upsert support.

Revision ID: 0003a4f8c21b
Revises: 0002
Create Date: 2026-04-15
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003a4f8c21b"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paper_citations_source_target_arxiv",
        "paper_citations",
        ["source_paper_id", "target_arxiv_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_paper_citations_source_target_arxiv",
        "paper_citations",
    )
