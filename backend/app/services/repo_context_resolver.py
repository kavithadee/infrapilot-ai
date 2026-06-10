"""
repo_context_resolver.py — discovers repo context via GitHub MCP.

Inspects exactly 5 constrained paths per run (no arbitrary recursion):
  {service_root}/schemas/      → schema/config files to read
  {service_root}/scripts/      → candidate write target
  {service_root}/tests/        → candidate write target
  {service_root}/              → top-level listing (README, etc. — not read)
  .github/workflows/           → existing CI workflow names

Returns a RepoContext describing what was found. The FixSpecAgent reads the
actual file contents for paths in read_paths; this module only discovers paths.
"""

from __future__ import annotations

from mcp import ClientSession
from pydantic import BaseModel

from app.core.logging import get_logger
from app.services.github_mcp import list_directory

logger = get_logger(__name__)

# File extensions that indicate schema / config files worth reading
_SCHEMA_EXTENSIONS: frozenset[str] = frozenset({".json", ".yaml", ".yml", ".toml"})


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class RepoContext(BaseModel):
    """
    Discovered context for a service in the target repo.

    Produced by resolve_repo_context(); consumed by FixSpecAgent.
    """

    service_name: str
    service_root: str                   # e.g. "demo-infra/audit-service"
    read_paths: list[str]               # schema/config files the LLM should read
    candidate_write_dirs: list[str]     # dirs where the LLM may write fixes
    existing_ci_workflows: list[str]    # .github/workflows/ files already present
    service_context_summary: str        # prose description for the LLM prompt


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


async def resolve_repo_context(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    service_name: str,
    service_root: str,
) -> RepoContext:
    """
    Discover repo context by inspecting known subdirectories via GitHub MCP.

    Uses list_directory() for each of the 5 constrained paths.
    Missing or empty directories return [] rather than raising.
    The read-path prefix guard in list_directory() enforces that all
    inspected paths start with "demo-infra/" or ".github/".
    """
    root = service_root.rstrip("/")

    logger.info("repo_context_resolver_start", service_name=service_name, service_root=root)

    # ------------------------------------------------------------------
    # 1. schemas/ — discover files the agent should read
    # ------------------------------------------------------------------
    schemas_listing = await list_directory(
        session, owner=owner, repo=repo, path=f"{root}/schemas"
    )
    read_paths = [
        p for p in schemas_listing
        if any(p.endswith(ext) for ext in _SCHEMA_EXTENSIONS)
    ]
    logger.info("repo_context_resolver_schemas", paths=read_paths)

    # ------------------------------------------------------------------
    # 2. scripts/ and tests/ — candidate write targets
    #    Always included; .gitkeep means the dir is intentionally empty.
    # ------------------------------------------------------------------
    await list_directory(session, owner=owner, repo=repo, path=f"{root}/scripts")
    await list_directory(session, owner=owner, repo=repo, path=f"{root}/tests")
    candidate_write_dirs = [
        f"{root}/scripts",
        f"{root}/tests",
    ]

    # ------------------------------------------------------------------
    # 3. service root top-level — informational only (not added to read_paths)
    # ------------------------------------------------------------------
    await list_directory(session, owner=owner, repo=repo, path=root)

    # ------------------------------------------------------------------
    # 4. .github/workflows/ — note existing CI to avoid duplicate names
    # ------------------------------------------------------------------
    workflows_listing = await list_directory(
        session, owner=owner, repo=repo, path=".github/workflows"
    )
    existing_ci_workflows = [
        p for p in workflows_listing
        if p.endswith(".yml") or p.endswith(".yaml")
    ]
    logger.info("repo_context_resolver_workflows", workflows=existing_ci_workflows)

    # ------------------------------------------------------------------
    # Build prose summary for the LLM prompt
    # ------------------------------------------------------------------
    summary_parts = [f"Service '{service_name}' at repo path '{root}'."]

    if read_paths:
        summary_parts.append(f"Schema/config files available to read: {read_paths}.")
    else:
        summary_parts.append("No schema or config files found in schemas/.")

    if existing_ci_workflows:
        summary_parts.append(
            f"Existing CI workflows (avoid duplicate names): {existing_ci_workflows}."
        )
    else:
        summary_parts.append("No existing CI workflows found in .github/workflows/.")

    summary_parts.append(
        f"Candidate write targets: {candidate_write_dirs}."
    )

    context = RepoContext(
        service_name=service_name,
        service_root=root,
        read_paths=read_paths,
        candidate_write_dirs=candidate_write_dirs,
        existing_ci_workflows=existing_ci_workflows,
        service_context_summary=" ".join(summary_parts),
    )

    logger.info(
        "repo_context_resolver_complete",
        read_paths=read_paths,
        candidate_write_dirs=candidate_write_dirs,
        existing_ci_workflows=existing_ci_workflows,
    )
    return context
