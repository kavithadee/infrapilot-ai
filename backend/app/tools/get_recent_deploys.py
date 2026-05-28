from sqlalchemy.orm import Session

from app.db.models import SimulatedDeploy
from app.schemas.tool_schemas import (
    DeployInfo,
    GetRecentDeploysInput,
    GetRecentDeploysOutput,
)
from app.tools.base import BaseTool


class GetRecentDeploysTool(BaseTool):
    name = "get_recent_deploys"
    description = (
        "Retrieve the most recent deployments for a service. "
        "Returns version, timestamp, author, changed files, config changes, and deploy status. "
        "Use this first to establish whether a recent deploy coincides with the incident timeline."
    )
    input_schema = GetRecentDeploysInput
    output_schema = GetRecentDeploysOutput
    cache_ttl = 300  # 5 minutes

    def _build_cache_key(self, raw_input: dict) -> str:
        limit = raw_input.get("limit", 5)
        return f"deploys:{raw_input.get('service_name', '')}:{limit}"

    def execute(
        self, input: GetRecentDeploysInput, db: Session
    ) -> GetRecentDeploysOutput:
        rows = (
            db.query(SimulatedDeploy)
            .filter(SimulatedDeploy.service_name == input.service_name)
            .order_by(SimulatedDeploy.deployed_at.desc())
            .limit(input.limit)
            .all()
        )

        deploys = [
            DeployInfo(
                version=row.version,
                deployed_at=row.deployed_at.isoformat(),
                author=row.author,
                commit_sha=row.commit_sha,
                changed_files=row.changed_files or [],
                config_changes=row.config_changes or {},
                status=row.status or "unknown",
            )
            for row in rows
        ]

        return GetRecentDeploysOutput(
            service_name=input.service_name,
            deploys=deploys,
        )
