from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateIncidentRequest(BaseModel):
    title: str = Field(description="Short title for the incident (e.g. 'BQ writes stopped')")
    description: str = Field(
        description="Full description of the symptoms and context — passed verbatim to the agent"
    )
    service_name: str = Field(description="Name of the affected service (e.g. 'lat-cron-job')")
    severity: str = Field(default="high", description="Incident severity: critical | high | medium | low")
    time_window: str = Field(
        default="2h",
        description=(
            "How far back to look when querying logs and errors. "
            "The agent will use this value for all temporal tool calls, "
            "making cache keys deterministic across re-investigations of the same incident. "
            "Examples: '1h', '2h', '6h', '24h'."
        ),
    )


class CreateIncidentResponse(BaseModel):
    incident_id: UUID
    run_id: UUID
    status: str  # always "pending" at creation time


class IncidentDetail(BaseModel):
    id: UUID
    title: str
    description: str
    service_name: str
    severity: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}  # enables .model_validate(orm_row)


class RunSummary(BaseModel):
    """Embedded in IncidentDetail when the caller wants run info alongside the incident."""

    id: UUID
    status: str
    agent_model: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    likely_root_cause: str | None = None
    confidence_score: float | None = None
    final_summary: str | None = None

    model_config = {"from_attributes": True}
