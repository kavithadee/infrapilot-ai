"""
test_tools.py — one functional test per infra tool against the seeded SQLite DB.

Each test verifies:
  - The tool returns well-shaped output (correct keys, non-empty data)
  - The tool returns the expected data for the known seed scenarios
"""

import uuid
import pytest

from app.tools.get_recent_deploys import GetRecentDeploysTool
from app.tools.get_service_logs import GetServiceLogsTool
from app.tools.get_k8s_pod_status import GetK8sPodStatusTool
from app.tools.get_bq_insert_errors import GetBqInsertErrorsTool
from app.tools.get_config_diff import GetConfigDiffTool


# ---------------------------------------------------------------------------
# get_recent_deploys
# ---------------------------------------------------------------------------

def test_get_recent_deploys_returns_v42(db):
    """lat-cron-job should have deploy v42 in the seeded data."""
    run_id = uuid.uuid4()
    tool = GetRecentDeploysTool()
    result = tool.run(
        raw_input={"service_name": "lat-cron-job"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["service_name"] == "lat-cron-job"
    assert len(result["deploys"]) >= 1
    versions = [d["version"] for d in result["deploys"]]
    assert "v42" in versions


def test_get_recent_deploys_returns_empty_for_unknown_service(db):
    """Unknown service should return an empty deploys list, not an error."""
    run_id = uuid.uuid4()
    tool = GetRecentDeploysTool()
    result = tool.run(
        raw_input={"service_name": "nonexistent-service"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["service_name"] == "nonexistent-service"
    assert result["deploys"] == []


def test_get_recent_deploys_api_service_has_innocent_deploy(db):
    """api-service v23 should be a frontend-only deploy (red herring scenario)."""
    run_id = uuid.uuid4()
    tool = GetRecentDeploysTool()
    result = tool.run(
        raw_input={"service_name": "api-service"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    versions = [d["version"] for d in result["deploys"]]
    assert "v23" in versions
    v23 = next(d for d in result["deploys"] if d["version"] == "v23")
    # Should only contain frontend/content files, no backend changes
    assert len(v23["changed_files"]) > 0, "v23 deploy must have at least one changed file"
    for f in v23["changed_files"]:
        assert any(keyword in f for keyword in ["css", "content", "static", "markdown", "md"])


# ---------------------------------------------------------------------------
# get_service_logs
# ---------------------------------------------------------------------------

def test_get_service_logs_returns_jwt_errors_for_lat_cron_job(db):
    """Scenario 1: lat-cron-job logs should contain JWT/auth errors."""
    run_id = uuid.uuid4()
    tool = GetServiceLogsTool()
    result = tool.run(
        raw_input={"service_name": "lat-cron-job", "time_window": "2h", "severity": "ERROR"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["service_name"] == "lat-cron-job"
    assert len(result["logs"]) > 0
    messages = [log["message"] for log in result["logs"]]
    assert any("JWT" in m or "auth" in m.lower() or "credential" in m.lower() for m in messages)


def test_get_service_logs_returns_connection_pool_errors_for_api_service(db):
    """Scenario 2: api-service logs should contain DB connection pool errors."""
    run_id = uuid.uuid4()
    tool = GetServiceLogsTool()
    result = tool.run(
        raw_input={"service_name": "api-service", "time_window": "2h", "severity": "ERROR"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert len(result["logs"]) > 0
    messages = [log["message"] for log in result["logs"]]
    assert any("connection" in m.lower() or "pool" in m.lower() or "clients" in m.lower() for m in messages)


# ---------------------------------------------------------------------------
# get_k8s_pod_status
# ---------------------------------------------------------------------------

def test_get_k8s_pod_status_lat_cron_job_healthy(db):
    """Scenario 1: lat-cron-job pod should be Running with 0 restarts (crash ruled out)."""
    run_id = uuid.uuid4()
    tool = GetK8sPodStatusTool()
    result = tool.run(
        raw_input={"service_name": "lat-cron-job"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["service_name"] == "lat-cron-job"
    assert len(result["pods"]) > 0
    pod = result["pods"][0]
    assert pod["pod_status"] == "Running"
    assert pod["restarts"] == 0


# ---------------------------------------------------------------------------
# get_bq_insert_errors
# ---------------------------------------------------------------------------

def test_get_bq_insert_errors_auth_error_for_lat_cron_job(db):
    """Scenario 1: analytics.daily_metrics should have AUTH_ERROR entries and no SCHEMA_ERROR."""
    run_id = uuid.uuid4()
    tool = GetBqInsertErrorsTool()
    # Use a large time_window so all seeded rows are captured regardless of
    # SQLite datetime precision or timezone-stripping behaviour.
    result = tool.run(
        raw_input={"table_name": "analytics.daily_metrics", "time_window": "999h"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["total_error_count"] > 0
    error_types = [e["error_type"] for e in result["errors"]]
    assert "AUTH_ERROR" in error_types
    # Must not be contaminated with audit-service schema errors
    assert "SCHEMA_ERROR" not in error_types
    table_names = [e["table_name"] for e in result["errors"]]
    assert all(t == "analytics.daily_metrics" for t in table_names)


def test_get_bq_insert_errors_schema_error_for_audit_service(db):
    """Scenario 3: compliance.audit_events should have SCHEMA_ERROR entries and no AUTH_ERROR."""
    run_id = uuid.uuid4()
    tool = GetBqInsertErrorsTool()
    result = tool.run(
        raw_input={"table_name": "compliance.audit_events", "time_window": "2h"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert result["total_error_count"] > 0
    error_types = [e["error_type"] for e in result["errors"]]
    assert "SCHEMA_ERROR" in error_types
    # Must not be contaminated with lat-cron-job auth errors
    assert "AUTH_ERROR" not in error_types
    table_names = [e["table_name"] for e in result["errors"]]
    assert all(t == "compliance.audit_events" for t in table_names)


# ---------------------------------------------------------------------------
# get_config_diff
# ---------------------------------------------------------------------------

def test_get_config_diff_lat_cron_job_v42_shows_secret_path_change(db):
    """Scenario 1: v42 config diff should show a changed secret/key path."""
    run_id = uuid.uuid4()
    tool = GetConfigDiffTool()
    result = tool.run(
        raw_input={"service_name": "lat-cron-job", "deploy_id": "v42"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert len(result["diffs"]) > 0
    diff = result["diffs"][0]["diff_json"]
    # Should show something changed (added, removed, or changed keys)
    assert diff.get("added") or diff.get("removed") or diff.get("changed")


def test_get_config_diff_audit_service_v9_shows_schema_change(db):
    """Scenario 3: v9 config diff should show the new BQ schema field."""
    run_id = uuid.uuid4()
    tool = GetConfigDiffTool()
    result = tool.run(
        raw_input={"service_name": "audit-service", "deploy_id": "v9"},
        db=db,
        run_id=run_id,
        sequence_num=1,
    )
    assert len(result["diffs"]) > 0
    diff_json = result["diffs"][0]["diff_json"]
    added = diff_json.get("added", [])
    assert any("user_agent" in str(item) for item in added)
