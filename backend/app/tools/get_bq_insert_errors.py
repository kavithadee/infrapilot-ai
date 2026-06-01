from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import SimulatedBqError
from app.schemas.tool_schemas import (
    BqErrorEntry,
    GetBqInsertErrorsInput,
    GetBqInsertErrorsOutput,
    parse_time_window,
)
from app.tools.base import BaseTool


class GetBqInsertErrorsTool(BaseTool):
    name = "get_bq_insert_errors"
    description = (
        "Retrieve recent BigQuery insert errors for a specific destination table. "
        "You MUST supply table_name — infer it from service logs or deploy config before calling. "
        "Returns error type (AUTH_ERROR, SCHEMA_ERROR, PERMISSION_DENIED), "
        "error message, and occurrence count. "
        "AUTH_ERROR indicates a credentials or service account problem. "
        "SCHEMA_ERROR indicates a mismatch between the insert payload and the table schema — "
        "check whether a recent deploy changed the schema file without running a table migration."
    )
    input_schema = GetBqInsertErrorsInput
    output_schema = GetBqInsertErrorsOutput
    cache_ttl = 120  # 2 minutes

    def _build_cache_key(self, raw_input: dict) -> str:
        table = raw_input.get("table_name", "unknown")
        window = raw_input.get("time_window", "1h")
        return f"bq:errors:{table}:{window}"

    def execute(
        self, input: GetBqInsertErrorsInput, db: Session
    ) -> GetBqInsertErrorsOutput:
        # table_name is required — always filter to the specific table so
        # errors from different seed scenarios never bleed into each other.
        # Anchor to the most recent error for that table so time_window is
        # meaningful against fixed seed data.
        table_filter = SimulatedBqError.table_name == input.table_name
        anchor_query = db.query(func.max(SimulatedBqError.timestamp)).filter(table_filter)
        query = db.query(SimulatedBqError).filter(table_filter)

        anchor = anchor_query.scalar()

        if anchor is not None:
            cutoff = anchor - parse_time_window(input.time_window)
            query = query.filter(SimulatedBqError.timestamp >= cutoff)

        rows = query.order_by(SimulatedBqError.timestamp.asc()).all()

        errors = [
            BqErrorEntry(
                table_name=row.table_name,
                timestamp=row.timestamp.isoformat(),
                error_type=row.error_type or "UNKNOWN",
                message=row.message or "",
                count=row.count or 1,
            )
            for row in rows
        ]

        total = sum(e.count for e in errors)

        return GetBqInsertErrorsOutput(
            time_window=input.time_window,
            errors=errors,
            total_error_count=total,
        )
