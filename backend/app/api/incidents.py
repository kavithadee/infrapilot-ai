from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.agents.investigator import run_investigation
from app.config import settings
from app.core.db import get_db
from app.db import repositories as repo
from app.schemas.incident import CreateIncidentRequest, CreateIncidentResponse, IncidentDetail


router = APIRouter()


@router.post("", response_model=CreateIncidentResponse, status_code=202)
def create_incident(
    body: CreateIncidentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Submit a new incident for investigation.

    Creates an incident row and an investigation run, then fires the agent
    loop as a background task. Returns immediately with run_id so the caller
    can poll GET /runs/{run_id} for results.

    Example:
        curl -X POST http://localhost:8000/incidents \\
          -H "Content-Type: application/json" \\
          -d '{"title":"BQ writes stopped","description":"lat-cron-job stopped writing...","service_name":"lat-cron-job","severity":"high"}'
    """
    # Create both rows atomically — if either insert fails, neither is committed.
    incident, run = repo.create_incident_and_run(
        db,
        title=body.title,
        description=body.description,
        service_name=body.service_name,
        severity=body.severity,
        agent_model=settings.agent_model,
    )

    # Fire investigation in background — returns 202 immediately.
    # time_window is passed explicitly so the agent uses a fixed value for all
    # temporal queries, making Redis cache keys deterministic across re-runs.
    background_tasks.add_task(run_investigation, run.id, body.time_window)

    return CreateIncidentResponse(
        incident_id=incident.id,
        run_id=run.id,
        status="pending",
    )


@router.get("", response_model=list[IncidentDetail])
def list_incidents(db: Session = Depends(get_db)):
    """
    List all incidents, most recent first.
    """
    rows = repo.list_incidents(db)
    return [IncidentDetail.model_validate(row) for row in rows]
