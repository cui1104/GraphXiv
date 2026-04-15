import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.models import Base


@pytest.fixture(scope="session")
def db_engine():
    """SQLAlchemy engine connected to test database.
    Reads DATABASE_URL from environment (set in .env or CI).
    """
    url = os.environ.get("DATABASE_URL", "postgresql://app:changeme@localhost:5432/papers")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def db_session(db_engine):
    """SQLAlchemy session for test queries."""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture(scope="session")
def redis_client():
    """Redis client for cache and broker tests."""
    import redis as redis_lib
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis_lib.from_url(url)
    yield client
    client.close()


@pytest.fixture
def mock_db_session():
    """SQLAlchemy session backed by SQLite in-memory for unit tests that don't need PostgreSQL.

    Uses raw DDL to create minimal versions of the tables needed for unit tests,
    avoiding PostgreSQL-specific types (JSONB, Vector) that SQLite can't compile.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE papers (
                canonical_id TEXT PRIMARY KEY,
                arxiv_id TEXT UNIQUE,
                pmc_id TEXT UNIQUE,
                doi TEXT,
                title TEXT,
                abstract TEXT,
                year INTEGER,
                venue TEXT,
                parse_source TEXT,
                parse_quality TEXT,
                token_count INTEGER,
                tldr TEXT,
                content TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """))
        conn.execute(text("""
            CREATE TABLE crawl_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL UNIQUE,
                resumption_token TEXT,
                last_harvested_at TEXT,
                record_count INTEGER DEFAULT 0
            )
        """))
        conn.commit()
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
