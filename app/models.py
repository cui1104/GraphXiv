import uuid
from datetime import datetime
from sqlalchemy import Integer, Text, Index, ForeignKey, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

# TIMESTAMPTZ = TIMESTAMP with timezone=True (SQLAlchemy 2.0.49 removed TIMESTAMPTZ alias)
TIMESTAMPTZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    arxiv_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    pmc_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_quality: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tldr: Mapped[str | None] = mapped_column(Text, nullable=True)
    embeddings: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now(), onupdate=func.now()
    )

    sources = relationship("PaperSource", back_populates="paper")
    outgoing_citations = relationship(
        "PaperCitation",
        foreign_keys="PaperCitation.source_paper_id",
        back_populates="source_paper",
    )

    __table_args__ = (
        Index("idx_papers_year", "year"),
    )


class PaperSource(Base):
    __tablename__ = "paper_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.canonical_id"), nullable=False
    )
    source_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str | None] = mapped_column(Text, nullable=True, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMPTZ, server_default=func.now()
    )

    paper = relationship("Paper", back_populates="sources")


class IdMap(Base):
    __tablename__ = "id_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    arxiv_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    pmc_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.canonical_id"), nullable=False
    )


class CrawlState(Base):
    __tablename__ = "crawl_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    resumption_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_harvested_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    __table_args__ = (
        UniqueConstraint("source", name="uq_crawl_state_source"),
    )


class PaperCitation(Base):
    __tablename__ = "paper_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.canonical_id"), nullable=False, index=True
    )
    target_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.canonical_id"), nullable=True, index=True
    )
    target_arxiv_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_doi: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_paper = relationship(
        "Paper",
        foreign_keys=[source_paper_id],
        back_populates="outgoing_citations",
    )
