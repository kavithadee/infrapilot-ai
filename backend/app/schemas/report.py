from typing import Literal

from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    timestamp: str = Field(
        description="ISO 8601 timestamp of the event"
    )
    event: str = Field(
        description="One-sentence description of what happened at this time"
    )
    source: str = Field(
        description=(
            "Tool or signal that surfaced this event "
            "(e.g. get_service_logs, get_recent_deploys, get_bq_insert_errors)"
        )
    )


class EvidenceItem(BaseModel):
    tool: str = Field(
        description="Infra tool that returned this evidence (e.g. get_bq_insert_errors)"
    )
    finding: str = Field(
        description="Specific finding from the tool output that supports the root cause"
    )
    significance: str = Field(
        description="Why this evidence matters — how it connects to the root cause"
    )


class RecommendedAction(BaseModel):
    action: str = Field(
        description="Concrete, actionable step to take"
    )
    priority: Literal["immediate", "short_term", "long_term"] = Field(
        description=(
            "immediate = fix right now to stop the bleeding; "
            "short_term = fix within 24 hours; "
            "long_term = prevent recurrence"
        )
    )
    rationale: str = Field(
        description="Why this action will resolve or prevent the issue"
    )


class InvestigationReport(BaseModel):
    """
    Structured output produced by the agent at the end of each investigation run.

    Validated by report_builder.py before being stored in investigation_runs.report_json.
    The `likely_root_cause`, `confidence_score`, and `final_summary` fields are also
    promoted to top-level columns on the investigation_runs table for fast API reads.
    """

    incident_summary: str = Field(
        description="One paragraph summarising the incident, symptoms observed, and business impact"
    )
    likely_root_cause: str = Field(
        description="Concise root cause statement (1-2 sentences)"
    )
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the root cause analysis: "
            "0.0 = no corroborating evidence, 1.0 = definitive proof from multiple tools"
        ),
    )
    evidence: list[EvidenceItem] = Field(
        description=(
            "Evidence items supporting the root cause, one per key finding. "
            "Must include at least one item per infra tool called."
        )
    )
    timeline: list[TimelineItem] = Field(
        description="Ordered sequence of events from earliest to latest, covering the full incident arc"
    )
    recommended_actions: list[RecommendedAction] = Field(
        description="Remediation steps ordered by urgency — most urgent (immediate) first"
    )
    tools_used: list[str] = Field(
        description="Names of all infra tools called during this investigation (e.g. ['get_recent_deploys', 'get_service_logs'])"
    )
    final_summary: str = Field(
        description="One-sentence summary suitable for an incident ticket title or on-call alert"
    )
