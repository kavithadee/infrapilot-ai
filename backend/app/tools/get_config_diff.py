from sqlalchemy.orm import Session

from app.db.models import SimulatedConfigDiff
from app.schemas.tool_schemas import (
    ConfigDiffEntry,
    GetConfigDiffInput,
    GetConfigDiffOutput,
)
from app.tools.base import BaseTool


class GetConfigDiffTool(BaseTool):
    name = "get_config_diff"
    description = (
        "Retrieve configuration diffs for a service deployment. "
        "Returns what was added, removed, or changed in environment variables, "
        "K8s config, or schema files for each deploy. "
        "This is the most direct evidence of what changed — cross-reference with "
        "deploy timestamps and error onset to confirm root cause. "
        "If deploy_id is omitted, diffs for all recent deployments are returned."
    )
    input_schema = GetConfigDiffInput
    output_schema = GetConfigDiffOutput
    cache_ttl = 300  # 5 minutes — config diffs are immutable once recorded

    def _build_cache_key(self, raw_input: dict) -> str:
        service = raw_input.get("service_name", "")
        deploy_id = raw_input.get("deploy_id") or "all"
        return f"config:{service}:{deploy_id}"

    def execute(
        self, input: GetConfigDiffInput, db: Session
    ) -> GetConfigDiffOutput:
        query = db.query(SimulatedConfigDiff).filter(
            SimulatedConfigDiff.service_name == input.service_name
        )

        if input.deploy_id:
            query = query.filter(
                SimulatedConfigDiff.deploy_id == input.deploy_id
            )

        rows = query.order_by(SimulatedConfigDiff.recorded_at.desc()).all()

        diffs = [
            ConfigDiffEntry(
                deploy_id=row.deploy_id,
                diff_json=row.diff_json or {},
                recorded_at=row.recorded_at.isoformat(),
            )
            for row in rows
        ]

        return GetConfigDiffOutput(
            service_name=input.service_name,
            diffs=diffs,
        )
