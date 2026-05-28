"""
conftest.py — shared fixtures for unit and integration tests.

Uses an in-memory SQLite DB so tests never touch the real Postgres instance.
Redis is patched to a MagicMock that always returns None (cache miss) so tool
logic is exercised without a real Redis connection.
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.seed.seed_data import seed_with_db


# ---------------------------------------------------------------------------
# In-memory SQLite engine + session
#
# StaticPool ensures all connections reuse the same underlying SQLite connection,
# which is required for in-memory DBs — without it each new connection/session
# gets a fresh empty database.
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture(scope="session")
def seeded_engine(engine):
    """Engine with all 3 seed scenarios loaded once for the whole test session."""
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        seed_with_db(db)
    finally:
        db.close()
    return engine


@pytest.fixture
def db(seeded_engine):
    """Per-test DB session. Rolls back after each test to keep tests isolated."""
    Session = sessionmaker(bind=seeded_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Redis mock — always cache miss, never raises
#
# Patches redis_get/redis_set in app.tools.base (where they are imported and
# used) so no test accidentally hits real Redis.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_redis():
    """Patch redis_get to return None (cache miss) and redis_set to no-op."""
    with patch("app.tools.base.redis_get", return_value=None) as mock_get, \
         patch("app.tools.base.redis_set", return_value=None) as mock_set:
        yield {"get": mock_get, "set": mock_set}
