"""Add UNIQUE constraint on crawl_state.source for upsert support.

Revision ID: 0002
Revises: 0001abcdef01
Create Date: 2026-04-15
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001abcdef01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_crawl_state_source", "crawl_state", ["source"])


def downgrade() -> None:
    op.drop_constraint("uq_crawl_state_source", "crawl_state", type_="unique")
