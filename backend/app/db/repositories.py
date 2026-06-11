from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Incident, InvestigationRun, RemediationDraft, ToolCall


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def create_incident(
    db: Session,
    *,
    title: str,
    description: str,
    service_name: str,
    severity: str = "high",
) -> Incident:
    incident = Incident(
        title=title,
        description=description,
        service_name=service_name,
        severity=severity,
        status="open",
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def create_incident_and_run(
    db: Session,
    *,
    title: str,
    description: str,
    service_name: str,
    severity: str = "high",
    agent_model: str,
) -> tuple[Incident, InvestigationRun]:
    """
    Create an Incident and its first InvestigationRun atomically.

    Both rows are committed in a single transaction so the DB is never
    left with an incident that has no associated run (or vice-versa).
    """
    incident = Incident(
        title=title,
        description=description,
        service_name=service_name,
        severity=severity,
        status="open",
    )
    db.add(incident)
    db.flush()  # obtain incident.id without committing yet

    run = InvestigationRun(
        incident_id=incident.id,
        agent_model=agent_model,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(incident)
    db.refresh(run)
    return incident, run


def get_incident(db: Session, incident_id: UUID) -> Incident | None:
    return db.query(Incident).filter(Incident.id == incident_id).first()


def list_incidents(db: Session) -> list[Incident]:
    return db.query(Incident).order_by(Incident.created_at.desc()).all()


def update_incident_status(db: Session, incident_id: UUID, status: str) -> None:
    db.query(Incident).filter(Incident.id == incident_id).update({"status": status})
    db.commit()


# ---------------------------------------------------------------------------
# Investigation Runs
# ---------------------------------------------------------------------------

def create_run(
    db: Session,
    *,
    incident_id: UUID,
    agent_model: str,
) -> InvestigationRun:
    run = InvestigationRun(
        incident_id=incident_id,
        agent_model=agent_model,
        status="pending",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: UUID) -> InvestigationRun | None:
    return db.query(InvestigationRun).filter(InvestigationRun.id == run_id).first()


def update_run_started(db: Session, run_id: UUID) -> None:
    db.query(InvestigationRun).filter(InvestigationRun.id == run_id).update({
        "status": "running",
        "started_at": datetime.now(timezone.utc),
    })
    db.commit()


def update_run_completed(
    db: Session,
    run_id: UUID,
    *,
    report_json: dict,
    final_summary: str,
    likely_root_cause: str,
    confidence_score: float,
) -> None:
    db.query(InvestigationRun).filter(InvestigationRun.id == run_id).update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc),
        "report_json": report_json,
        "final_summary": final_summary,
        "likely_root_cause": likely_root_cause,
        "confidence_score": confidence_score,
    })
    db.commit()


def update_run_failed(db: Session, run_id: UUID, *, error_message: str) -> None:
    db.query(InvestigationRun).filter(InvestigationRun.id == run_id).update({
        "status": "failed",
        "completed_at": datetime.now(timezone.utc),
        "error_message": error_message,
    })
    db.commit()


def update_run_status(db: Session, run_id: UUID, *, status: str) -> None:
    """Lightweight status-only update — used by dev endpoints to close throwaway runs."""
    db.query(InvestigationRun).filter(InvestigationRun.id == run_id).update({
        "status": status,
        "completed_at": datetime.now(timezone.utc),
    })
    db.commit()


# ---------------------------------------------------------------------------
# Tool Calls
# ---------------------------------------------------------------------------

def log_tool_call(
    db: Session,
    *,
    run_id: UUID,
    tool_name: str,
    input_json: dict,
    output_json: dict | None,
    latency_ms: int,
    cache_hit: bool,
    sequence_num: int,
    status: str = "success",
    error_message: str | None = None,
) -> ToolCall:
    tool_call = ToolCall(
        run_id=run_id,
        tool_name=tool_name,
        input_json=input_json,
        output_json=output_json,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
        sequence_num=sequence_num,
        status=status,
        error_message=error_message,
    )
    db.add(tool_call)
    db.commit()
    db.refresh(tool_call)
    return tool_call


def get_tool_calls_for_run(db: Session, run_id: UUID) -> list[ToolCall]:
    return (
        db.query(ToolCall)
        .filter(ToolCall.run_id == run_id)
        .order_by(ToolCall.sequence_num.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Remediation Drafts (v1.6)
# ---------------------------------------------------------------------------


def create_remediation_draft(
    db: Session,
    *,
    run_id: UUID,
    selected_recommendation: str,
    target_repo: str,
    base_branch: str,
) -> RemediationDraft:
    draft = RemediationDraft(
        run_id=run_id,
        status="drafting",
        selected_recommendation=selected_recommendation,
        target_repo=target_repo,
        base_branch=base_branch,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def update_remediation_draft(
    db: Session,
    *,
    draft_id: UUID,
    **kwargs,
) -> RemediationDraft:
    """
    Partial update — pass only the fields to change as keyword arguments.
    Accepted keys: status, branch_name, fix_spec_json, github_pr_url, error_message.
    """
    db.query(RemediationDraft).filter(RemediationDraft.id == draft_id).update(kwargs)
    db.commit()
    draft = db.query(RemediationDraft).filter(RemediationDraft.id == draft_id).first()
    return draft


def get_remediation_draft(db: Session, draft_id: UUID) -> RemediationDraft | None:
    return db.query(RemediationDraft).filter(RemediationDraft.id == draft_id).first()


def list_remediation_drafts_for_run(db: Session, run_id: UUID) -> list[RemediationDraft]:
    return (
        db.query(RemediationDraft)
        .filter(RemediationDraft.run_id == run_id)
        .order_by(RemediationDraft.created_at.desc())
        .all()
    )


def find_demo_pr_created_draft(db: Session) -> RemediationDraft | None:
    """
    Return the most recent pr_created draft for the demo audit-service
    schema_validation remediation, across ALL runs.

    Used for idempotency: repeated "Create GitHub Draft PR" clicks on a
    public demo return the existing PR rather than creating a new one.
    Matches on service_name=audit-service + schema/validation keyword in
    the recommendation — mirrors RemediationClassifier logic without importing it.
    """
    _SCHEMA_KEYWORDS = (
        "schema", "validation", "validate", "compatibility",
        "pre-deploy", "predeploy", "pre_deploy", "mismatch",
    )
    candidates = (
        db.query(RemediationDraft)
        .join(InvestigationRun, RemediationDraft.run_id == InvestigationRun.id)
        .join(Incident, InvestigationRun.incident_id == Incident.id)
        .filter(
            RemediationDraft.status == "pr_created",
            RemediationDraft.github_pr_url.isnot(None),
            Incident.service_name == "audit-service",
        )
        .order_by(RemediationDraft.created_at.desc())
        .all()
    )
    for draft in candidates:
        rec = draft.selected_recommendation.lower()
        if any(kw in rec for kw in _SCHEMA_KEYWORDS):
            return draft
    return None
