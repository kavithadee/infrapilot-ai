"""
Scenario 1: BigQuery Auth Failure — lat-cron-job

Timeline:
  T+0    deploy v42 lands (changed service account config)
  T+3min JWT errors begin appearing in logs
  T+3min BigQuery AUTH_ERRORs start accumulating
  T+now  K8s pod still Running, restarts=0 (pod is healthy — auth is the issue)

Key signal for agent: config diff shows SERVICE_ACCOUNT_JSON_B64 was removed and
replaced with SERVICE_ACCOUNT_KEY_FILE, breaking the GCP auth chain.
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

SERVICE = "lat-cron-job"
BQ_TABLE = "analytics.daily_metrics"

# Anchor the scenario relative to a fixed point so seed is deterministic
_BASE_TIME = datetime(2024, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
_DEPLOY_TIME = _BASE_TIME
_ERROR_START = _BASE_TIME + timedelta(minutes=3)


def seed(db: Session) -> None:
    """Insert all Scenario 1 rows. Called by seed_data.py (idempotency handled there)."""

    # ------------------------------------------------------------------
    # Deploy v42
    # ------------------------------------------------------------------
    db.add(SimulatedDeploy(
        service_name=SERVICE,
        version="v42",
        deployed_at=_DEPLOY_TIME,
        author="alice@example.com",
        commit_sha="a3f9c12d",
        changed_files=[
            "auth/service_account.json",
            "k8s/secret-mount.yaml",
        ],
        config_changes={
            "SERVICE_ACCOUNT_KEY_PATH": "changed from /secrets/sa.json to /run/secrets/sa_key_file",
        },
        status="success",
    ))

    # ------------------------------------------------------------------
    # Logs — 12 JWT error occurrences starting at T+3min
    # ------------------------------------------------------------------
    log_messages = [
        "Invalid JWT Signature when calling BigQuery API",
        "Invalid JWT Signature when calling BigQuery API",
        "BigQuery request failed: invalid_grant — Invalid JWT Signature",
        "Invalid JWT Signature when calling BigQuery API",
        "Retrying BigQuery insert after auth failure (attempt 1/3)",
        "Invalid JWT Signature when calling BigQuery API",
        "Retrying BigQuery insert after auth failure (attempt 2/3)",
        "Invalid JWT Signature when calling BigQuery API",
        "Retrying BigQuery insert after auth failure (attempt 3/3) — giving up",
        "Invalid JWT Signature when calling BigQuery API",
        "BigQuery insert job failed permanently for table analytics.daily_metrics",
        "Invalid JWT Signature when calling BigQuery API",
    ]
    for i, msg in enumerate(log_messages):
        db.add(SimulatedLog(
            service_name=SERVICE,
            timestamp=_ERROR_START + timedelta(seconds=i * 15),
            severity="ERROR",
            message=msg,
            meta={"job": "daily_bq_export", "attempt": i + 1},
        ))

    # A few INFO logs before the error to show normal startup
    for i in range(3):
        db.add(SimulatedLog(
            service_name=SERVICE,
            timestamp=_DEPLOY_TIME + timedelta(seconds=30 + i * 30),
            severity="INFO",
            message=f"lat-cron-job started successfully (run #{i + 1})",
            meta={"job": "daily_bq_export"},
        ))

    # ------------------------------------------------------------------
    # BigQuery errors — 47 AUTH_ERRORs at T+3min
    # ------------------------------------------------------------------
    db.add(SimulatedBqError(
        table_name=BQ_TABLE,
        timestamp=_ERROR_START,
        error_type="AUTH_ERROR",
        message="Request had invalid authentication credentials. "
                "Expected OAuth 2 access token, login cookie or other valid authentication credential. "
                "See https://developers.google.com/identity/sign-in/web/devconsole-project.",
        count=47,
    ))
    db.add(SimulatedBqError(
        table_name=BQ_TABLE,
        timestamp=_ERROR_START + timedelta(minutes=1),
        error_type="AUTH_ERROR",
        message="invalid_grant: Invalid JWT Signature.",
        count=12,
    ))

    # ------------------------------------------------------------------
    # K8s status — pod is Running, restarts=0 (key signal: not a crash)
    # ------------------------------------------------------------------
    db.add(SimulatedK8sStatus(
        service_name=SERVICE,
        pod_name="lat-cron-job-7d9f8b-xkq2p",
        pod_status="Running",
        restarts=0,
        last_event="Started container lat-cron-job",
        recorded_at=_ERROR_START + timedelta(minutes=5),
    ))

    # ------------------------------------------------------------------
    # Config diff for v42 — shows the breaking change
    # ------------------------------------------------------------------
    db.add(SimulatedConfigDiff(
        service_name=SERVICE,
        deploy_id="v42",
        diff_json={
            "removed": ["SERVICE_ACCOUNT_JSON_B64"],
            "added":   ["SERVICE_ACCOUNT_KEY_FILE"],
            "changed": {
                "SERVICE_ACCOUNT_KEY_PATH": {
                    "old": "/secrets/sa.json",
                    "new": "/run/secrets/sa_key_file",
                },
            },
        },
        recorded_at=_DEPLOY_TIME,
    ))

    db.commit()
