"""Initial schema: all 5 tables, pgvector extension, GIN FTS index, citation indexes.

Revision ID: 0001abcdef01
Revises:
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "0001abcdef01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Enable pgvector extension FIRST (must precede any table using vector type)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Create papers table
    op.create_table(
        "papers",
        sa.Column("canonical_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("arxiv_id", sa.Text, unique=True, nullable=True),
        sa.Column("pmc_id", sa.Text, unique=True, nullable=True),
        sa.Column("doi", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("abstract", sa.Text, nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("venue", sa.Text, nullable=True),
        sa.Column("parse_source", sa.Text, nullable=True),
        sa.Column("parse_quality", sa.Text, nullable=True),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("tldr", sa.Text, nullable=True),
        sa.Column("embeddings", Vector(768), nullable=True),
        sa.Column("content", JSONB, nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 3. Create paper_sources table
    op.create_table(
        "paper_sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "canonical_id",
            UUID(as_uuid=True),
            sa.ForeignKey("papers.canonical_id"),
            nullable=False,
        ),
        sa.Column("source_type", sa.Text, nullable=True),
        sa.Column("asset_path", sa.Text, nullable=True),
        sa.Column("parse_status", sa.Text, nullable=True, server_default="pending"),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 4. Create id_map table
    op.create_table(
        "id_map",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("arxiv_id", sa.Text, nullable=True),
        sa.Column("pmc_id", sa.Text, nullable=True),
        sa.Column("doi", sa.Text, nullable=True),
        sa.Column(
            "canonical_id",
            UUID(as_uuid=True),
            sa.ForeignKey("papers.canonical_id"),
            nullable=False,
        ),
    )

    # 5. Create crawl_state table
    op.create_table(
        "crawl_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("resumption_token", sa.Text, nullable=True),
        sa.Column("last_harvested_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("record_count", sa.Integer, nullable=True, server_default="0"),
    )

    # 6. Create paper_citations table (INFRA-06)
    op.create_table(
        "paper_citations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "source_paper_id",
            UUID(as_uuid=True),
            sa.ForeignKey("papers.canonical_id"),
            nullable=False,
        ),
        sa.Column(
            "target_paper_id",
            UUID(as_uuid=True),
            sa.ForeignKey("papers.canonical_id"),
            nullable=True,
        ),
        sa.Column("target_arxiv_id", sa.Text, nullable=True),
        sa.Column("target_doi", sa.Text, nullable=True),
        sa.Column("context_text", sa.Text, nullable=True),
    )

    # 7. Create indexes (after all tables exist)
    op.create_index("idx_paper_citations_source", "paper_citations", ["source_paper_id"])
    op.create_index("idx_paper_citations_target", "paper_citations", ["target_paper_id"])
    op.create_index("idx_papers_year", "papers", ["year"])

    # 8. GIN FTS index as raw SQL (avoids Alembic autogenerate false-positive bug #1390)
    op.execute("""
        CREATE INDEX idx_papers_fts
        ON papers
        USING GIN (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, '')))
    """)


def downgrade() -> None:
    op.drop_table("paper_citations")
    op.drop_table("crawl_state")
    op.drop_table("id_map")
    op.drop_table("paper_sources")
    op.drop_table("papers")
    op.execute("DROP EXTENSION IF EXISTS vector")
