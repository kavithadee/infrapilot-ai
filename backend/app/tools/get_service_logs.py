from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import SimulatedLog
from app.schemas.tool_schemas import (
    GetServiceLogsInput,
    GetServiceLogsOutput,
    LogEntry,
    parse_time_window,
)
from app.tools.base import BaseTool


class GetServiceLogsTool(BaseTool):
    name = "get_service_logs"
    description = (
        "Retrieve recent log entries for a service. "
        "Returns timestamped log lines with severity and metadata. "
        "Use this to identify error patterns, crash messages, or anomalies "
        "that correlate with the incident timeline. "
        "Filter by severity (ERROR, CRITICAL) to focus on actionable signals."
    )
    input_schema = GetServiceLogsInput
    output_schema = GetServiceLogsOutput
    cache_ttl = 120  # 2 minutes — logs are more time-sensitive than deploys

    def _build_cache_key(self, raw_input: dict) -> str:
        service = raw_input.get("service_name", "")
        window = raw_input.get("time_window", "1h")
        severity = raw_input.get("severity") or "all"
        limit = raw_input.get("limit", 50)
        return f"logs:{service}:{window}:{severity}:{limit}"

    def execute(
        self, input: GetServiceLogsInput, db: Session
    ) -> GetServiceLogsOutput:
        # ------------------------------------------------------------------
        # v1.5 swap point: when settings.log_backend == "loki", replace the
        # block below with a Loki HTTP query using LogQL:
        #   {service="{input.service_name}"} | severity="{input.severity}"
        # and set backend="loki" on the output.
        # ------------------------------------------------------------------

        # Find the most recent log timestamp for this service and treat it as
        # "now" — this makes time_window meaningful against fixed seed data.
        anchor = (
            db.query(func.max(SimulatedLog.timestamp))
            .filter(SimulatedLog.service_name == input.service_name)
            .scalar()
        )

        query = db.query(SimulatedLog).filter(
            SimulatedLog.service_name == input.service_name
        )

        if anchor is not None:
            cutoff = anchor - parse_time_window(input.time_window)
            query = query.filter(SimulatedLog.timestamp >= cutoff)

        if input.severity:
            query = query.filter(
                SimulatedLog.severity == input.severity.upper()
            )

        rows = (
            query
            .order_by(SimulatedLog.timestamp.desc())
            .limit(input.limit)
            .all()
        )

        # Return in chronological order so the agent reads them naturally
        rows = list(reversed(rows))

        logs = [
            LogEntry(
                timestamp=row.timestamp.isoformat(),
                severity=row.severity or "INFO",
                message=row.message,
                meta=row.meta or {},
            )
            for row in rows
        ]

        return GetServiceLogsOutput(
            service_name=input.service_name,
            time_window=input.time_window,
            logs=logs,
            backend=settings.log_backend,
        )
