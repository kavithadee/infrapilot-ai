"""
service_registry.py — maps service names to their GitHub repo and service_root path.

SERVICE_REPO_MAP is the single source of truth for which services InfraPilot
can remediate and where their code lives in the target repo.

Adding a new service: add an entry to SERVICE_REPO_MAP.
Policy (write-path rules, content safety) lives in remediation_policy.py — not here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Service → repo mapping
# ---------------------------------------------------------------------------

# Key  : service_name (matches Incident.service_name in the DB)
# Value: dict with:
#   "repo"         — owner/repo on GitHub (may be overridden by settings.github_target_repo)
#   "service_root" — repo-relative path to the service's code root
SERVICE_REPO_MAP: dict[str, dict[str, str]] = {
    "audit-service": {
        "repo": "kavithadee/infrapilot-ai",
        "service_root": "demo-infra/audit-service",
    },
}


def get_service_config(service_name: str) -> dict[str, str]:
    """
    Return the repo config dict for service_name.

    Raises ValueError if the service is not in SERVICE_REPO_MAP.
    The API layer treats this as an unsupported-service condition (→ 422).
    """
    config = SERVICE_REPO_MAP.get(service_name)
    if config is None:
        supported = sorted(SERVICE_REPO_MAP.keys())
        raise ValueError(
            f"Service '{service_name}' is not supported for automated remediation. "
            f"Supported services in v1: {supported}"
        )
    return config
