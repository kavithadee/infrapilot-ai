"""
Scenario 3: BigQuery Schema Mismatch — audit-service (Silent Data Loss)

A developer added a `user_agent` column to the audit events schema in code but
did not run `bq update` to add the column to the production BigQuery table.
Inserts are rejected silently — no crash, no pod restart, no loud ERROR.
The only observable signal is that audit data stops flowing.

Timeline:
  T-45m  deploy v8 (routine — unrelated minor fix, wrote fine afterwards)
  T-30m  deploy v9 lands (added user_agent field to schema/audit_events.json)
  T-30m  BQ inserts begin failing with SCHEMA_ERROR silently
  T-30m  logs show WARN "0 rows written" — no exception raised, no crash
  T-now  pod Running, restarts=0 — nothing looks broken from infra side

Key signals for agent:
  1. BQ SCHEMA_ERROR: "no such field: user_agent" — the exact missing column
  2. Config diff for v9: schema/audit_events.json gained field `user_agent STRING`
  3. Logs: 0 rows written warnings, not errors — app swallowed the rejection
  4. Pod healthy, restarts=0 — purely a data-layer issue

Root cause: schema migration not run. Fix: `bq update --schema schema/audit_events.json
  project:dataset.audit_events` — requires human approval before running in production.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    SimulatedBqError,
    SimulatedConfigDiff,
    SimulatedDeploy,
    SimulatedK8sStatus,
    SimulatedLog,
)

SERVICE = "audit-service"
BQ_TABLE = "compliance.audit_events"

_NOW = datetime(2024, 1, 18, 11, 0, 0, tzinfo=timezone.utc)
_DEPLOY_V8_TIME = _NOW - timedelta(minutes=45)  # routine deploy, fine
_DEPLOY_V9_TIME = _NOW - timedelta(minutes=30)  # schema change — breaks BQ inserts
_ERROR_START = _DEPLOY_V9_TIME                  # failures begin immediately on deploy


def seed(db: Session) -> None:
    """Insert all Scenario 3 rows. Called by seed_data.py (idempotency handled there)."""

    # ------------------------------------------------------------------
    # Deploy v8 — routine fix, unrelated to the incident
    # Exists so the agent sees multiple deploys and picks the right one
    # ------------------------------------------------------------------
    db.add(SimulatedDeploy(
        service_name=SERVICE,
        version="v8",
        deployed_at=_DEPLOY_V8_TIME,
        author="diana@example.com",
        commit_sha="c4a1b3e9",
        changed_files=["handlers/auth_handler.py"],
        config_changes={},
        status="success",
    ))

    # ------------------------------------------------------------------
    # Deploy v9 — added user_agent field to schema file, forgot migration
    # ------------------------------------------------------------------
    db.add(SimulatedDeploy(
        service_name=SERVICE,
        version="v9",
        deployed_at=_DEPLOY_V9_TIME,
        author="diana@example.com",
        commit_sha="e6f2d8a1",
        changed_files=[
            "schema/audit_events.json",
            "models/audit_event.py",
        ],
        config_changes={},
        status="success",
    ))

    # ------------------------------------------------------------------
    # Logs — healthy writes before v9, silent 0-row warnings after
    # ------------------------------------------------------------------

    # Healthy writes before and during v8 deploy — shows the table was fine
    for i in range(5):
        db.add(SimulatedLog(
            service_name=SERVICE,
            timestamp=_DEPLOY_V8_TIME - timedelta(minutes=5) + timedelta(minutes=i * 2),
            severity="INFO",
            message="Audit batch written successfully to BigQuery",
            meta={"rows_written": 42 + i * 3, "table": BQ_TABLE, "version": "v8"},
        ))

    # Normal writes briefly after v8 — service healthy
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_DEPLOY_V8_TIME + timedelta(minutes=5),
        severity="INFO",
        message="Audit batch written successfully to BigQuery",
        meta={"rows_written": 38, "table": BQ_TABLE, "version": "v8"},
    ))

    # v9 deploys — inserts immediately start failing silently
    # App logs WARN not ERROR because it catches the BQ exception and continues
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(seconds=15),
        severity="WARN",
        message="BigQuery insert rejected — 0 rows written (batch dropped)",
        meta={"rows_attempted": 51, "rows_written": 0, "table": BQ_TABLE, "version": "v9"},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(seconds=30),
        severity="INFO",
        message="audit-service healthy — processing events on :9090",
        meta={"version": "v9"},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(minutes=1),
        severity="WARN",
        message="BigQuery insert rejected — 0 rows written (batch dropped)",
        meta={"rows_attempted": 47, "rows_written": 0, "table": BQ_TABLE, "version": "v9"},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(minutes=2),
        severity="WARN",
        message="BigQuery insert rejected — 0 rows written (batch dropped)",
        meta={"rows_attempted": 55, "rows_written": 0, "table": BQ_TABLE, "version": "v9"},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(minutes=5),
        severity="WARN",
        message="BigQuery insert rejected — 0 rows written (batch dropped)",
        meta={"rows_attempted": 49, "rows_written": 0, "table": BQ_TABLE, "version": "v9"},
    ))
    # Cumulative data-loss warning after 10 min of silence
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_ERROR_START + timedelta(minutes=10),
        severity="WARN",
        message="No audit rows written to BigQuery in last 10 minutes — possible schema or auth issue",
        meta={"table": BQ_TABLE, "version": "v9", "minutes_since_last_write": 10},
    ))

    # ------------------------------------------------------------------
    # BigQuery errors — SCHEMA_ERROR naming the exact missing field
    # ------------------------------------------------------------------
    db.add(SimulatedBqError(
        table_name=BQ_TABLE,
        timestamp=_ERROR_START + timedelta(seconds=15),
        error_type="SCHEMA_ERROR",
        message=(
            "Invalid schema update. Field user_agent is not present in the destination table. "
            "To add a new field to an existing table, the field must be nullable or repeated."
        ),
        count=1,
    ))
    db.add(SimulatedBqError(
        table_name=BQ_TABLE,
        timestamp=_ERROR_START + timedelta(minutes=1),
        error_type="SCHEMA_ERROR",
        message="no such field: user_agent in table compliance.audit_events",
        count=18,
    ))
    db.add(SimulatedBqError(
        table_name=BQ_TABLE,
        timestamp=_ERROR_START + timedelta(minutes=5),
        error_type="SCHEMA_ERROR",
        message="no such field: user_agent in table compliance.audit_events",
        count=34,
    ))

    # ------------------------------------------------------------------
    # K8s status — pod Running, healthy, zero restarts
    # ------------------------------------------------------------------
    db.add(SimulatedK8sStatus(
        service_name=SERVICE,
        pod_name="audit-service-9b4f2c-stu8v",
        pod_status="Running",
        restarts=0,
        last_event="Liveness probe succeeded",
        recorded_at=_ERROR_START + timedelta(minutes=15),
    ))

    # ------------------------------------------------------------------
    # Config diff for v9 — schema file shows the new user_agent field
    # ------------------------------------------------------------------
    db.add(SimulatedConfigDiff(
        service_name=SERVICE,
        deploy_id="v9",
        diff_json={
            "removed": [],
            "added": [
                {
                    "file": "schema/audit_events.json",
                    "field": "user_agent",
                    "type": "STRING",
                    "mode": "NULLABLE",
                    "note": "Added for compliance tracking — production BQ table not yet updated",
                }
            ],
            "changed": {
                "models/audit_event.py": {
                    "note": "AuditEvent dataclass gained user_agent: str | None field",
                },
            },
        },
        recorded_at=_DEPLOY_V9_TIME,
    ))

    # Config diff for v8 — clean, nothing relevant
    db.add(SimulatedConfigDiff(
        service_name=SERVICE,
        deploy_id="v8",
        diff_json={
            "removed": [],
            "added":   [],
            "changed": {
                "handlers/auth_handler.py": {
                    "note": "Fixed edge case in token refresh — no config changes",
                },
            },
        },
        recorded_at=_DEPLOY_V8_TIME,
    ))

    db.commit()
