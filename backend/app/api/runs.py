from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db import repositories as repo

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RunDetail(BaseModel):
    id: UUID
    incident_id: UUID
    status: str
    agent_model: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    likely_root_cause: str | None = None
    confidence_score: float | None = None
    final_summary: str | None = None
    report_json: dict | None = None   # full InvestigationReport once completed
    error_message: str | None = None

    model_config = {"from_attributes": True}


class ToolCallRecord(BaseModel):
    id: UUID
    run_id: UUID
    tool_name: str
    input_json: dict
    output_json: dict | None = None
    latency_ms: int | None = None
    cache_hit: bool
    status: str
    error_message: str | None = None
    sequence_num: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    """
    Get the current state of an investigation run.

    Poll this endpoint after POST /incidents to track progress:
      - status=pending   → queued, not started yet
      - status=running   → agent loop in progress
      - status=completed → report_json is populated with the full report
      - status=failed    → error_message explains what went wrong

    Example:
        curl http://localhost:8000/runs/{run_id}
    """
    run = repo.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunDetail.model_validate(run)


@router.get("/{run_id}/tool-calls", response_model=list[ToolCallRecord])
def get_tool_calls(run_id: UUID, db: Session = Depends(get_db)):
    """
    List all infra tool calls made during an investigation run, in order.

    Useful for understanding the agent's reasoning chain:
    which tools it called, in what order, with what inputs/outputs,
    and whether results were served from the Redis cache.

    Note: generate_report is never included here — only infra tool calls
    (get_recent_deploys, get_service_logs, get_k8s_pod_status, etc.) are logged.

    Example:
        curl http://localhost:8000/runs/{run_id}/tool-calls
    """
    run = repo.get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    tool_calls = repo.get_tool_calls_for_run(db, run_id)
    return [ToolCallRecord.model_validate(tc) for tc in tool_calls]
