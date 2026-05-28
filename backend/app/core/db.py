from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # reconnect silently after postgres restarts
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def create_all() -> None:
    """Create all tables. Called once on app startup (no Alembic in V1)."""
    # Import models here so Base.metadata is populated before create_all runs.
    import app.db.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — yields a SQLAlchemy session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
