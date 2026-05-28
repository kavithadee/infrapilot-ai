"""
Input and output Pydantic models for all 5 infrastructure tools.

Input schemas are passed to build_openai_tools_spec() — their field descriptions
appear verbatim in the OpenAI function spec, so they should be agent-readable.

Output schemas are returned by each tool's execute() method and serialised to
JSON for Redis caching and Postgres storage.
"""

from datetime import timedelta

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared time-window helper
# ---------------------------------------------------------------------------

def parse_time_window(window: str) -> timedelta:
    """
    Parse a human-readable time window string into a timedelta.

    Supported formats: "30m", "1h", "2h", "24h", "7d"
    Defaults to 1 hour on unrecognised input.
    """
    window = window.strip().lower()
    if window.endswith("m"):
        return timedelta(minutes=int(window[:-1]))
    if window.endswith("h"):
        return timedelta(hours=int(window[:-1]))
    if window.endswith("d"):
        return timedelta(days=int(window[:-1]))
    return timedelta(hours=1)


# ---------------------------------------------------------------------------
# Shared output sub-models
# ---------------------------------------------------------------------------

class DeployInfo(BaseModel):
    version: str
    deployed_at: str            # ISO 8601 datetime string
    author: str | None = None
    commit_sha: str | None = None
    changed_files: list[str] = []
    config_changes: dict = {}
    status: str


class LogEntry(BaseModel):
    timestamp: str              # ISO 8601 datetime string
    severity: str               # INFO / WARN / ERROR / CRITICAL
    message: str
    meta: dict = {}             # renamed from 'metadata' for consistency with DB column


class PodStatus(BaseModel):
    pod_name: str | None = None
    pod_status: str             # Running / CrashLoopBackOff / Pending
    restarts: int = 0
    last_event: str | None = None
    recorded_at: str            # ISO 8601 datetime string


class BqErrorEntry(BaseModel):
    table_name: str
    timestamp: str              # ISO 8601 datetime string
    error_type: str             # AUTH_ERROR / SCHEMA_ERROR / PERMISSION_DENIED
    message: str
    count: int = 1


class ConfigDiffEntry(BaseModel):
    deploy_id: str              # version string e.g. "v42"
    diff_json: dict             # { added: [...], removed: [...], changed: {...} }
    recorded_at: str            # ISO 8601 datetime string


# ---------------------------------------------------------------------------
# Tool 1: get_recent_deploys
# ---------------------------------------------------------------------------

class GetRecentDeploysInput(BaseModel):
    service_name: str = Field(
        description="The name of the service to look up recent deployments for."
    )
    limit: int = Field(
        default=5,
        description="Maximum number of recent deployments to return (default 5).",
    )


class GetRecentDeploysOutput(BaseModel):
    service_name: str
    deploys: list[DeployInfo]


# ---------------------------------------------------------------------------
# Tool 2: get_service_logs
# ---------------------------------------------------------------------------

class GetServiceLogsInput(BaseModel):
    service_name: str = Field(
        description="The name of the service to retrieve logs for."
    )
    time_window: str = Field(
        default="1h",
        description=(
            "How far back to look for logs. Examples: '30m', '1h', '2h', '24h'. "
            "Defaults to '1h'."
        ),
    )
    severity: str | None = Field(
        default=None,
        description=(
            "Optional severity filter. One of: INFO, WARN, ERROR, CRITICAL. "
            "If omitted, all severities are returned."
        ),
    )
    limit: int = Field(
        default=50,
        description="Maximum number of log entries to return (default 50).",
    )


class GetServiceLogsOutput(BaseModel):
    service_name: str
    time_window: str
    logs: list[LogEntry]
    # v1.5: when log_backend="loki", this field will indicate the query backend
    backend: str = "postgres"


# ---------------------------------------------------------------------------
# Tool 3: get_k8s_pod_status
# ---------------------------------------------------------------------------

class GetK8sPodStatusInput(BaseModel):
    service_name: str = Field(
        description=(
            "The name of the service to retrieve Kubernetes pod status for. "
            "Returns the most recent status snapshot for each pod."
        )
    )


class GetK8sPodStatusOutput(BaseModel):
    service_name: str
    pods: list[PodStatus]


# ---------------------------------------------------------------------------
# Tool 4: get_bq_insert_errors
# ---------------------------------------------------------------------------

class GetBqInsertErrorsInput(BaseModel):
    table_name: str | None = Field(
        default=None,
        description=(
            "BigQuery table name to filter errors for (e.g. 'analytics.daily_metrics'). "
            "If omitted, returns all recent BQ insert errors across all tables."
        ),
    )
    time_window: str = Field(
        default="1h",
        description="How far back to look for errors. Examples: '30m', '1h', '2h'.",
    )


class GetBqInsertErrorsOutput(BaseModel):
    time_window: str
    errors: list[BqErrorEntry]
    total_error_count: int


# ---------------------------------------------------------------------------
# Tool 5: get_config_diff
# ---------------------------------------------------------------------------

class GetConfigDiffInput(BaseModel):
    service_name: str = Field(
        description="The name of the service to retrieve configuration diffs for."
    )
    deploy_id: str | None = Field(
        default=None,
        description=(
            "Specific deployment version to retrieve the config diff for "
            "(e.g. 'v42'). If omitted, returns diffs for all recent deployments."
        ),
    )


class GetConfigDiffOutput(BaseModel):
    service_name: str
    diffs: list[ConfigDiffEntry]
