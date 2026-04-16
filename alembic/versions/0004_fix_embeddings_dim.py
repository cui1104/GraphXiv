"""Change embeddings column from Vector(768) to Vector(384) and add HNSW index.

Revision ID: 0004_fix_embeddings_dim
Revises: 0003a4f8c21b
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "0004_fix_embeddings_dim"
down_revision = "0003a4f8c21b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("papers", "embeddings")
    op.add_column("papers", sa.Column("embeddings", Vector(384), nullable=True))
    try:
        op.execute(
            "CREATE INDEX idx_papers_embeddings ON papers "
            "USING hnsw (embeddings vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    except Exception:
        op.execute(
            "CREATE INDEX idx_papers_embeddings ON papers "
            "USING ivfflat (embeddings vector_cosine_ops) "
            "WITH (lists = 100)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_papers_embeddings")
    op.drop_column("papers", "embeddings")
    op.add_column("papers", sa.Column("embeddings", Vector(768), nullable=True))
