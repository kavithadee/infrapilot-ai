"""
Idempotent seed runner. Safe to call multiple times — checks for existing rows
before inserting. Called automatically on app startup from main.py.

Manual run:
    docker compose exec api python -m app.seed.seed_data
"""

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.db.models import SimulatedDeploy
from app.seed.scenarios import scenario_bq_auth, scenario_bq_schema, scenario_red_herring

logger = get_logger(__name__)

# Each scenario is identified by a (service_name, version) pair that must exist
# if seeding has already run. If absent, seed the whole scenario.
_SCENARIO_SENTINELS = [
    ("lat-cron-job",  "v42",  scenario_bq_auth,     "bq_auth"),
    ("api-service",   "v23",  scenario_red_herring,  "red_herring"),
    ("audit-service", "v9",   scenario_bq_schema,    "bq_schema"),
]


def _already_seeded(db, service_name: str, version: str) -> bool:
    return (
        db.query(SimulatedDeploy)
        .filter(
            SimulatedDeploy.service_name == service_name,
            SimulatedDeploy.version == version,
        )
        .first()
        is not None
    )


def run_seed() -> None:
    db = SessionLocal()
    try:
        for service_name, version, module, label in _SCENARIO_SENTINELS:
            if _already_seeded(db, service_name, version):
                logger.info("seed_skipped", scenario=label, reason="already seeded")
            else:
                module.seed(db)
                logger.info("seed_complete", scenario=label)
    except Exception as e:
        logger.error("seed_failed", error=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
