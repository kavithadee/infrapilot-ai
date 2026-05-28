import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.core.db import create_all
from app.core.logging import configure_logging, get_logger
from app.seed.seed_data import run_seed

# Routers — Day 1
from app.api import health, tools

# Routers — Day 2 (uncomment as implemented)
# from app.api import incidents, runs

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic using the modern FastAPI lifespan pattern."""
    # --- Startup ---
    configure_logging(level="DEBUG" if settings.is_development else "INFO")
    logger.info("startup_begin", version=settings.app_version, env=settings.environment)

    # Create all DB tables (no Alembic in V1).
    # Run in a thread pool so sync SQLAlchemy calls don't block the event loop.
    await asyncio.to_thread(create_all)
    logger.info("db_tables_created")

    # Seed simulation data (idempotent — skips if already seeded).
    await asyncio.to_thread(run_seed)
    logger.info("startup_complete")

    yield

    # --- Shutdown ---
    logger.info("shutdown")


app = FastAPI(
    title="InfraPilot AI",
    description="Agentic on-call debugging copilot.",
    version=settings.app_version,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health.router, tags=["health"])
app.include_router(tools.router, tags=["dev"])

# Day 2 — uncomment as implemented:
# app.include_router(incidents.router, prefix="/incidents", tags=["incidents"])
# app.include_router(runs.router, prefix="/runs", tags=["runs"])
