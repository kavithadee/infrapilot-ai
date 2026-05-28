from sqlalchemy.orm import Session

from app.db.models import SimulatedK8sStatus
from app.schemas.tool_schemas import (
    GetK8sPodStatusInput,
    GetK8sPodStatusOutput,
    PodStatus,
)
from app.tools.base import BaseTool


class GetK8sPodStatusTool(BaseTool):
    name = "get_k8s_pod_status"
    description = (
        "Retrieve the current Kubernetes pod status for a service. "
        "Returns pod name, status (Running/CrashLoopBackOff/Pending), restart count, "
        "and the last K8s event. "
        "A healthy pod (Running, restarts=0) rules out a crash as the root cause. "
        "CrashLoopBackOff with high restart count indicates the container is failing on startup."
    )
    input_schema = GetK8sPodStatusInput
    output_schema = GetK8sPodStatusOutput
    cache_ttl = 60  # 1 minute — pod status can change quickly

    def _build_cache_key(self, raw_input: dict) -> str:
        return f"k8s:pod:{raw_input.get('service_name', '')}"

    def execute(
        self, input: GetK8sPodStatusInput, db: Session
    ) -> GetK8sPodStatusOutput:
        rows = (
            db.query(SimulatedK8sStatus)
            .filter(SimulatedK8sStatus.service_name == input.service_name)
            .order_by(SimulatedK8sStatus.recorded_at.desc())
            .all()
        )

        pods = [
            PodStatus(
                pod_name=row.pod_name,
                pod_status=row.pod_status or "Unknown",
                restarts=row.restarts or 0,
                last_event=row.last_event,
                recorded_at=row.recorded_at.isoformat(),
            )
            for row in rows
        ]

        return GetK8sPodStatusOutput(
            service_name=input.service_name,
            pods=pods,
        )
