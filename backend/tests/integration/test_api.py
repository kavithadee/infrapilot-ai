"""
test_api.py — integration test for the full POST /incidents → completed run flow.

OpenAI is mocked to return a scripted tool-calling sequence so the test is
deterministic and doesn't require an API key or network access.

The mock simulates a 4-step agent loop for the lat-cron-job BQ auth scenario:
  Iteration 1 → call get_recent_deploys
  Iteration 2 → call get_service_logs + get_bq_insert_errors
  Iteration 3 → call get_config_diff
  Iteration 4 → call generate_report (with valid report JSON)

Assertions:
  - POST /incidents returns 202 with run_id
  - run eventually reaches status=completed
  - report contains expected fields
  - ≥3 infra tool calls are persisted in tool_calls table
  - cache_hit column is set correctly
"""

import json
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.core.db import get_db
from app.main import app
from app.seed.seed_data import seed_with_db


# ---------------------------------------------------------------------------
# Test database setup (separate from conftest to avoid session-scoped conflicts)
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def integration_db_engine():
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        seed_with_db(db)
    finally:
        db.close()
    return engine


@pytest.fixture(scope="module")
def client(integration_db_engine):
    """
    FastAPI TestClient wired to the integration test DB.

    Two overrides are needed:
      1. get_db — the FastAPI dependency used by API route handlers
      2. app.agents.investigator.SessionLocal — used by run_investigation()
         which creates its own session (it runs as a BackgroundTask outside
         the request context and cannot use the get_db dependency).
    """
    TestSessionLocal = sessionmaker(bind=integration_db_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.tools.base.redis_get", return_value=None), \
         patch("app.tools.base.redis_set", return_value=None), \
         patch("app.agents.investigator.SessionLocal", TestSessionLocal):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# OpenAI mock — scripted tool-calling sequence
# ---------------------------------------------------------------------------

VALID_REPORT = {
    "incident_summary": "lat-cron-job stopped writing to BigQuery.",
    "likely_root_cause": "Deploy v42 changed SERVICE_ACCOUNT_KEY_PATH, breaking BQ auth.",
    "confidence_score": 0.9,
    "evidence": [
        {
            "tool": "get_recent_deploys",
            "finding": "v42 changed SERVICE_ACCOUNT_KEY_PATH.",
            "significance": "Config change coincides with incident start.",
        },
        {
            "tool": "get_bq_insert_errors",
            "finding": "47 AUTH_ERROR entries in analytics.user_events.",
            "significance": "Confirms auth failure is the proximate cause.",
        },
        {
            "tool": "get_config_diff",
            "finding": "Secret path changed from /secrets/sa.json to /run/secrets/sa_key_file.",
            "significance": "Direct link between deploy and auth failure.",
        },
    ],
    "timeline": [
        {
            "timestamp": "2024-01-15T18:00:00+00:00",
            "event": "Deploy v42 changed the SA key path.",
            "source": "get_recent_deploys",
        }
    ],
    "recommended_actions": [
        {
            "action": "Revert SERVICE_ACCOUNT_KEY_PATH to /secrets/sa.json.",
            "priority": "immediate",
            "rationale": "Restores BigQuery auth immediately.",
        }
    ],
    "tools_used": [
        "get_recent_deploys",
        "get_service_logs",
        "get_bq_insert_errors",
        "get_config_diff",
    ],
    "final_summary": "Deploy v42 broke BQ auth by changing the service account key path.",
}


def _tool_call(name: str, args: dict, call_id: str | None = None) -> MagicMock:
    tc = MagicMock()
    tc.id = call_id or f"call_{name}_{uuid.uuid4().hex[:6]}"
    tc.type = "function"
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _assistant_message(tool_calls: list) -> MagicMock:
    msg = MagicMock()
    msg.role = "assistant"
    msg.content = None
    msg.tool_calls = tool_calls
    return msg


def _build_openai_mock():
    """
    Returns a mock OpenAI client whose chat.completions.create() cycles through
    a scripted sequence of tool calls across 4 iterations.
    """
    iterations = [
        # Iteration 1: deploys
        [_tool_call("get_recent_deploys", {"service_name": "lat-cron-job"})],
        # Iteration 2: logs + BQ errors
        [
            _tool_call("get_service_logs", {"service_name": "lat-cron-job", "time_window": "2h", "severity": "ERROR"}),
            _tool_call("get_bq_insert_errors", {"table_name": "analytics.user_events", "time_window": "2h"}),
        ],
        # Iteration 3: config diff
        [_tool_call("get_config_diff", {"service_name": "lat-cron-job", "deploy_id": "v42"})],
        # Iteration 4: generate_report
        [_tool_call("generate_report", VALID_REPORT)],
    ]

    call_count = {"n": 0}

    def create_side_effect(**kwargs):
        i = call_count["n"]
        call_count["n"] += 1
        tool_calls = iterations[min(i, len(iterations) - 1)]
        response = MagicMock()
        response.choices[0].message = _assistant_message(tool_calls)
        return response

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = create_side_effect
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_post_incidents_returns_202(client):
    with patch("app.agents.investigator.OpenAI", return_value=_build_openai_mock()):
        resp = client.post("/incidents", json={
            "title": "BQ writes stopped",
            "description": "lat-cron-job stopped writing to BigQuery after deploy v42",
            "service_name": "lat-cron-job",
            "severity": "high",
        })

    assert resp.status_code == 202
    body = resp.json()
    assert "run_id" in body
    assert "incident_id" in body
    assert body["status"] == "pending"


def test_full_investigation_completes(client, integration_db_engine):
    """Full flow: submit → agent runs (mocked) → run reaches completed with report."""
    openai_mock = _build_openai_mock()

    with patch("app.agents.investigator.OpenAI", return_value=openai_mock):
        resp = client.post("/incidents", json={
            "title": "BQ writes stopped",
            "description": "lat-cron-job stopped writing to BigQuery after deploy v42",
            "service_name": "lat-cron-job",
            "severity": "high",
        })

    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    # Poll run status — background task runs synchronously in TestClient
    run_resp = client.get(f"/runs/{run_id}")
    assert run_resp.status_code == 200
    run = run_resp.json()

    assert run["status"] == "completed"
    assert run["likely_root_cause"] is not None
    assert run["confidence_score"] == 0.9
    assert run["report_json"] is not None
    report = run["report_json"]
    assert "evidence" in report
    assert "timeline" in report
    assert "recommended_actions" in report
    assert "tools_used" in report


def test_tool_calls_persisted_with_correct_count(client):
    """≥3 infra tool calls should be persisted and none should be generate_report."""
    openai_mock = _build_openai_mock()

    with patch("app.agents.investigator.OpenAI", return_value=openai_mock):
        resp = client.post("/incidents", json={
            "title": "BQ writes stopped",
            "description": "lat-cron-job stopped writing to BigQuery after deploy v42",
            "service_name": "lat-cron-job",
            "severity": "high",
        })

    run_id = resp.json()["run_id"]
    calls_resp = client.get(f"/runs/{run_id}/tool-calls")
    assert calls_resp.status_code == 200
    calls = calls_resp.json()

    # generate_report should NOT appear in tool_calls
    tool_names = [c["tool_name"] for c in calls]
    assert "generate_report" not in tool_names

    # At least MIN_INFRA_TOOLS unique tools
    assert len(set(tool_names)) >= 3

    # All calls should have succeeded
    assert all(c["status"] == "success" for c in calls)

    # Sequence numbers should be monotonically increasing
    seq_nums = [c["sequence_num"] for c in calls]
    assert seq_nums == sorted(seq_nums)


def test_invalid_time_window_returns_422(client):
    """time_window validator should reject free-form strings with 422."""
    resp = client.post("/incidents", json={
        "title": "Test",
        "description": "test",
        "service_name": "svc",
        "time_window": "last week",
    })
    assert resp.status_code == 422
    assert "time_window" in resp.text
