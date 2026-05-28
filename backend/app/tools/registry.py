from app.tools.get_bq_insert_errors import GetBqInsertErrorsTool
from app.tools.get_config_diff import GetConfigDiffTool
from app.tools.get_k8s_pod_status import GetK8sPodStatusTool
from app.tools.get_recent_deploys import GetRecentDeploysTool
from app.tools.get_service_logs import GetServiceLogsTool
from app.tools.base import BaseTool

# ---------------------------------------------------------------------------
# Tool registry
# All infrastructure tools available to the agent. generate_report is NOT
# registered here — it is added directly to the OpenAI spec in investigator.py
# as a finalization tool only.
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, BaseTool] = {
    "get_recent_deploys":   GetRecentDeploysTool(),
    "get_service_logs":     GetServiceLogsTool(),
    "get_k8s_pod_status":  GetK8sPodStatusTool(),
    "get_bq_insert_errors": GetBqInsertErrorsTool(),
    "get_config_diff":      GetConfigDiffTool(),
}


def build_openai_tools_spec() -> list[dict]:
    """
    Convert all registered tools to OpenAI function-calling format.

    Returns a list of tool dicts ready to pass as the `tools` argument to
    openai.chat.completions.create(). Each entry looks like:

        {
            "type": "function",
            "function": {
                "name": "get_recent_deploys",
                "description": "...",
                "parameters": { ...JSON schema from input_schema... }
            }
        }

    generate_report is intentionally excluded — investigator.py appends it
    separately so it is never treated as an infrastructure tool call.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema.model_json_schema(),
            },
        }
        for tool in TOOL_REGISTRY.values()
    ]
