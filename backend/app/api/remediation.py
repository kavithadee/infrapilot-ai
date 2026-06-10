"""
remediation.py — GitHub MCP human-in-the-loop remediation endpoints.

Endpoints:
  POST /runs/{run_id}/remediation-drafts   → 201  kick off the agent pipeline
  GET  /runs/{run_id}/remediation-drafts   → 200  list drafts for a run
  GET  /remediation-drafts/{draft_id}      → 200  get a single draft

Error codes:
  400 — run not completed yet
  404 — run or draft not found
  422 — unsupported recommendation type or service
  503 — GitHub token not configured
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.fix_spec_agent import run_fix_spec_agent
from app.config import settings
from app.core.db import SessionLocal, get_db
from app.core.logging import get_logger
from app.db import repositories as repo
from app.guardrails.remediation_classifier import (
    UnsupportedRemediationType,
    classify_remediation_type,
)
from app.guardrails.service_registry import get_service_config
from app.schemas.remediation import (
    CreateRemediationDraftRequest,
    RemediationDraftDetail,
)

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _run_agent_background(
    *,
    draft_id: UUID,
    run_id: UUID,
    incident_id: UUID,
    selected_recommendation: str,
) -> None:
    """
    Background task wrapper — creates its own DB session (request session
    closes before this runs) and calls the async agent pipeline.

    Errors are logged and persisted inside run_fix_spec_agent; this wrapper
    silently absorbs exceptions so FastAPI does not log a double-traceback.
    """
    db = SessionLocal()
    try:
        run = repo.get_run(db, run_id)
        incident = repo.get_incident(db, incident_id)
        await run_fix_spec_agent(
            draft_id=draft_id,
            run=run,
            incident=incident,
            selected_recommendation=selected_recommendation,
            db=db,
        )
    except Exception as exc:
        # Already logged + persisted as status=failed inside run_fix_spec_agent.
        logger.error("remediation_background_task_error", error=str(exc))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/remediation-drafts",
    response_model=RemediationDraftDetail,
    status_code=201,
)
async def create_remediation_draft(
    run_id: UUID,
    body: CreateRemediationDraftRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start a remediation draft for a completed investigation run.

    Pre-flight checks (before creating any DB rows):
      - GitHub token configured        → 503 if missing
      - Run exists + is completed      → 404 / 400
      - Recommendation is classifiable → 422 if blocked or unrecognised
      - Service is in SERVICE_REPO_MAP → 422 if unsupported

    On success: creates a RemediationDraft row (status=drafting), fires the
    agent pipeline as a background task, and returns 201 immediately.
    Poll GET /remediation-drafts/{draft_id} for the result.
    """
    # -- Pre-flight 1: GitHub token --
    if not settings.github_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "GitHub integration is not configured. "
                "Set GITHUB_PERSONAL_ACCESS_TOKEN in your environment."
            ),
        )

    # -- Pre-flight 2: Run must exist and be completed --
    run = repo.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")

    if run.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Run {run_id} has status '{run.status}'. "
                "The investigation must complete before creating a remediation draft."
            ),
        )

    incident = repo.get_incident(db, run.incident_id)
    if not incident:
        raise HTTPException(
            status_code=404, detail=f"Incident {run.incident_id} not found."
        )

    # -- Pre-flight 3: Classify recommendation (fail fast, no DB row yet) --
    try:
        classify_remediation_type(body.selected_recommendation)
    except UnsupportedRemediationType as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # -- Pre-flight 4: Service must be in SERVICE_REPO_MAP --
    try:
        get_service_config(incident.service_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # -- Create draft row (status=drafting) --
    draft = repo.create_remediation_draft(
        db,
        run_id=run_id,
        selected_recommendation=body.selected_recommendation,
        target_repo=settings.github_target_repo,
        base_branch=settings.github_base_branch,
    )
    logger.info(
        "remediation_draft_created",
        draft_id=str(draft.id),
        run_id=str(run_id),
        service_name=incident.service_name,
    )

    # -- Fire agent pipeline as background task --
    background_tasks.add_task(
        _run_agent_background,
        draft_id=draft.id,
        run_id=run_id,
        incident_id=incident.id,
        selected_recommendation=body.selected_recommendation,
    )

    return RemediationDraftDetail.model_validate(draft)


@router.get(
    "/remediation-drafts/{draft_id}",
    response_model=RemediationDraftDetail,
)
def get_remediation_draft(draft_id: UUID, db: Session = Depends(get_db)):
    """
    Get a single remediation draft by ID.
    Poll this endpoint to check whether the agent has finished (status=pr_created or failed).
    """
    draft = repo.get_remediation_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found.")
    return RemediationDraftDetail.model_validate(draft)


@router.get(
    "/runs/{run_id}/remediation-drafts",
    response_model=list[RemediationDraftDetail],
)
def list_remediation_drafts(run_id: UUID, db: Session = Depends(get_db)):
    """
    List all remediation drafts for a run, most recent first.
    """
    run = repo.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
    drafts = repo.list_remediation_drafts_for_run(db, run_id)
    return [RemediationDraftDetail.model_validate(d) for d in drafts]
