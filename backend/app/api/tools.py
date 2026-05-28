from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.db import get_db
from app.db import repositories as repo
from app.tools.registry import TOOL_REGISTRY

router = APIRouter()


@router.post("/tools/{tool_name}/test")
def test_tool(
    tool_name: str,
    raw_input: dict,
    db: Session = Depends(get_db),
):
    """
    Dev-only endpoint: call a single tool directly and return its result.
    Useful for verifying seed data and tool output before running the full agent.

    Creates a throwaway incident + run row to satisfy FK constraints so the
    full tool pipeline (cache + DB logging) is exercised end-to-end.

    Example:
        curl -X POST http://localhost:8000/tools/get_recent_deploys/test \\
          -H "Content-Type: application/json" \\
          -d '{"service_name": "lat-cron-job"}'
    """
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="Not found")

    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found. Available: {list(TOOL_REGISTRY.keys())}",
        )

    # Create throwaway incident + run so tool_calls FK constraint is satisfied
    incident = repo.create_incident(
        db,
        title=f"[dev-test] {tool_name}",
        description="Throwaway incident created by /tools/test endpoint.",
        service_name=raw_input.get("service_name", "unknown"),
    )
    run = repo.create_run(db, incident_id=incident.id, agent_model=settings.agent_model)

    try:
        result = tool.run(
            raw_input=raw_input,
            db=db,
            run_id=run.id,
            sequence_num=1,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "tool": tool_name,
        "input": raw_input,
        "result": result,
    }
