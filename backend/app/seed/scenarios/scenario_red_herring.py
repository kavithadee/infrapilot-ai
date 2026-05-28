"""
Scenario 2: Latency Spike — api-service (Red Herring Deploy)

The agent must practice elimination reasoning, not just correlation.

Timeline:
  T-2h   deploy v23 lands (frontend CSS + marketing copy only — innocent)
  T-2h   misleading signal: one slow query warning logged right after deploy
  T-10m  p99 latency spikes to 8s — unrelated to the deploy
  T-10m  DB connection timeout errors begin flooding logs
  T-now  pod Running, restarts=0 (healthy)

Key signals for agent:
  1. Deploy was 2 hours ago; spike started 10 minutes ago — timeline mismatch rules it out
  2. Config diff for v23 shows only marketing copy change — no backend config touched
  3. Logs show "FATAL: sorry, too many clients already" — connection pool exhausted
  4. K8s pod is healthy — not a crash, not an OOM

Root cause: DB connection pool exhaustion from a traffic spike (3× normal).
The deploy is a red herring. Fix: increase DB_POOL_SIZE or add a connection pooler (PgBouncer).
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    SimulatedConfigDiff,
    SimulatedDeploy,
    SimulatedK8sStatus,
    SimulatedLog,
)

SERVICE = "api-service"

# "Now" is when the incident is reported
_NOW = datetime(2024, 1, 17, 14, 0, 0, tzinfo=timezone.utc)
_DEPLOY_TIME = _NOW - timedelta(hours=2)    # 12:00 — innocent deploy
_SPIKE_START = _NOW - timedelta(minutes=10) # 13:50 — actual problem starts


def seed(db: Session) -> None:
    """Insert all Scenario 2 rows. Called by seed_data.py (idempotency handled there)."""

    # ------------------------------------------------------------------
    # Deploy v23 — frontend/copy only, no backend changes
    # ------------------------------------------------------------------
    db.add(SimulatedDeploy(
        service_name=SERVICE,
        version="v23",
        deployed_at=_DEPLOY_TIME,
        author="carol@example.com",
        commit_sha="b1d3e7f2",
        changed_files=[
            "static/css/landing.css",
            "static/css/dashboard.css",
            "content/homepage_copy.md",
        ],
        config_changes={
            "HOMEPAGE_HERO_TEXT": "Updated marketing copy for Q1 campaign",
        },
        status="success",
    ))

    # ------------------------------------------------------------------
    # Logs — normal around deploy, misleading slow query, then DB errors
    # ------------------------------------------------------------------

    # Normal INFO logs before and around the deploy
    for i in range(5):
        db.add(SimulatedLog(
            service_name=SERVICE,
            timestamp=_DEPLOY_TIME - timedelta(minutes=10) + timedelta(minutes=i * 3),
            severity="INFO",
            message="api-service healthy — serving requests on :8080",
            meta={"version": "v22", "p99_ms": 120},
        ))

    # Misleading signal: slow query warning right after deploy
    # Looks suspicious at first, but it's a coincidence — predates the spike by 2 hours
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_DEPLOY_TIME + timedelta(minutes=2),
        severity="WARN",
        message="Slow query detected (2.3s): SELECT * FROM audit_events WHERE user_id = $1",
        meta={"version": "v23", "query_ms": 2300, "table": "audit_events"},
    ))

    # More normal logs after deploy — service is fine for nearly 2 hours
    for i in range(4):
        db.add(SimulatedLog(
            service_name=SERVICE,
            timestamp=_DEPLOY_TIME + timedelta(minutes=10 + i * 20),
            severity="INFO",
            message="api-service healthy — serving requests on :8080",
            meta={"version": "v23", "p99_ms": 130 + i * 5},
        ))

    # Latency spike begins at T-10min — DB connection errors flood in
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START,
        severity="ERROR",
        message="FATAL: sorry, too many clients already (max_connections=20)",
        meta={"version": "v23", "active_connections": 20, "waiting": 47},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START + timedelta(seconds=5),
        severity="ERROR",
        message="Request failed: could not obtain connection from pool within 5000ms",
        meta={"version": "v23", "pool_size": 10, "pool_timeout_ms": 5000},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START + timedelta(seconds=10),
        severity="ERROR",
        message="FATAL: sorry, too many clients already (max_connections=20)",
        meta={"version": "v23", "active_connections": 20, "waiting": 63},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START + timedelta(seconds=15),
        severity="WARN",
        message="p99 latency degraded: 8240ms (threshold: 500ms) — DB connection wait dominating",
        meta={"version": "v23", "p99_ms": 8240, "p50_ms": 6100},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START + timedelta(seconds=20),
        severity="ERROR",
        message="FATAL: sorry, too many clients already (max_connections=20)",
        meta={"version": "v23", "active_connections": 20, "waiting": 81},
    ))
    db.add(SimulatedLog(
        service_name=SERVICE,
        timestamp=_SPIKE_START + timedelta(seconds=30),
        severity="ERROR",
        message="Incoming request rate: 3.1× baseline — connection pool not sized for current traffic",
        meta={"version": "v23", "rps": 620, "baseline_rps": 200},
    ))

    # ------------------------------------------------------------------
    # K8s status — pod Running, healthy, not the problem
    # ------------------------------------------------------------------
    db.add(SimulatedK8sStatus(
        service_name=SERVICE,
        pod_name="api-service-5f7c8d-mnp4q",
        pod_status="Running",
        restarts=0,
        last_event="Liveness probe succeeded",
        recorded_at=_SPIKE_START + timedelta(minutes=5),
    ))

    # ------------------------------------------------------------------
    # Config diff for v23 — only marketing copy, no backend config
    # ------------------------------------------------------------------
    db.add(SimulatedConfigDiff(
        service_name=SERVICE,
        deploy_id="v23",
        diff_json={
            "removed": [],
            "added":   [],
            "changed": {
                "HOMEPAGE_HERO_TEXT": {
                    "old": "The platform that scales with you.",
                    "new": "Reliability starts here. Ship faster, break less.",
                    "note": "Marketing copy update for Q1 campaign — no backend impact",
                },
            },
        },
        recorded_at=_DEPLOY_TIME,
    ))

    db.commit()
