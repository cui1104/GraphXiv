import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


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
