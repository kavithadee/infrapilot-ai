"""
GitHub MCP service — wraps the github-mcp-server subprocess via the Python MCP SDK.

The github-mcp-server binary is installed in the Docker image (see Dockerfile).
All GitHub operations (read file, list directory, create branch, write file, open PR)
go through this module so that the rest of the codebase never calls GitHub directly.

Safety model:
  - _enforce_read_path  — prefix-based guard; paths must start with an allowed prefix
                          (default: "demo-infra/" or ".github/")
  - _enforce_write_path — delegates to RemediationPolicy.check_write_path(); policy is
                          injected by the caller, not hardcoded here
  - No exact-path allowlist frozensets — the policy layer owns write boundaries
  - No assert statements used as security boundaries
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Required MCP tools — validated at session open via list_tools()
# ---------------------------------------------------------------------------

REQUIRED_TOOLS: frozenset[str] = frozenset(
    {
        "get_file_contents",
        "create_branch",
        "create_or_update_file",
        "create_pull_request",
    }
)

# Default prefixes for read-path guard.  Callers may override via allowed_prefixes.
_DEFAULT_READ_PREFIXES: tuple[str, ...] = ("demo-infra/", ".github/")


# ---------------------------------------------------------------------------
# Path guards — explicit runtime validation, never assert
# ---------------------------------------------------------------------------


def _enforce_read_path(
    path: str,
    allowed_prefixes: tuple[str, ...] = _DEFAULT_READ_PREFIXES,
) -> None:
    """Raise ValueError if path does not start with one of allowed_prefixes."""
    if not any(path.startswith(p) for p in allowed_prefixes):
        raise ValueError(
            f"Read blocked: '{path}' does not start with an allowed prefix. "
            f"Allowed prefixes: {sorted(allowed_prefixes)}"
        )


def _enforce_write_path(path: str, policy: Any) -> None:
    """Raise ValueError if RemediationPolicy.check_write_path() rejects the path."""
    allowed, reason = policy.check_write_path(path)
    if not allowed:
        raise ValueError(f"Write blocked: {reason}")


# ---------------------------------------------------------------------------
# MCP result parsers
# ---------------------------------------------------------------------------


def _text_content(result: Any) -> str:
    """Extract the first text content item from an MCP tool result."""
    try:
        for item in result.content:
            if hasattr(item, "text"):
                return item.text
    except (AttributeError, TypeError):
        pass
    raise ValueError(f"Could not extract text content from MCP result: {result!r}")


def _extract_file_contents(result: Any) -> str:
    """Return the decoded file contents string from a get_file_contents result."""
    raw = _text_content(result)
    # GitHub MCP returns JSON with a "content" key (base64) or the decoded text directly.
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # Decoded content is returned under "content" as a string (MCP decodes base64).
            if "content" in parsed:
                return parsed["content"]
            # Some versions return the file text directly in the JSON wrapper.
            if "text" in parsed:
                return parsed["text"]
    except (json.JSONDecodeError, TypeError):
        pass
    # Plain text — return as-is.
    return raw


def _extract_sha(result: Any) -> str:
    """Return the blob SHA from a get_file_contents result (needed for file updates)."""
    raw = _text_content(result)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "sha" in parsed:
            return parsed["sha"]
    except (json.JSONDecodeError, TypeError):
        pass
    raise ValueError(f"Could not extract SHA from get_file_contents result: {raw!r}")


def _extract_pr_url(result: Any) -> str:
    """Return the html_url from a create_pull_request result."""
    raw = _text_content(result)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for key in ("html_url", "url", "pr_url"):
                if key in parsed:
                    return parsed[key]
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: if result is a plain URL string
    if isinstance(raw, str) and raw.startswith("https://github.com"):
        return raw
    raise ValueError(f"Could not extract PR URL from create_pull_request result: {raw!r}")


def _extract_directory_listing(result: Any) -> list[str]:
    """Return a list of file paths from a get_file_contents directory listing.

    GitHub MCP returns a JSON array of objects (each with a "path" key) when
    called on a directory path.  Returns [] for unrecognised or empty responses.
    """
    raw = _text_content(result)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [
                item["path"]
                for item in parsed
                if isinstance(item, dict) and "path" in item
            ]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Session context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def github_mcp_session():
    """
    Async context manager that opens a GitHub MCP session via the
    github-mcp-server subprocess (stdio transport).

    Yields the validated ClientSession. Raises RuntimeError if required
    tools are missing from the server's tool list.

    Usage:
        async with github_mcp_session() as mcp:
            result = await mcp.call_tool("get_file_contents", {...})
    """
    if not settings.github_token:
        raise ValueError(
            "GITHUB_PERSONAL_ACCESS_TOKEN is not configured. "
            "Set it in your environment or .env file."
        )

    params = StdioServerParameters(
        command="github-mcp-server",
        args=["stdio"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": settings.github_token},
    )

    logger.info("github_mcp_session_opening")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await _validate_required_tools(session)
            logger.info("github_mcp_session_ready")
            yield session
    logger.info("github_mcp_session_closed")


async def _validate_required_tools(session: ClientSession) -> None:
    """
    Call list_tools() and verify every tool in REQUIRED_TOOLS is present.
    Raises RuntimeError naming any missing tools so the caller can return 503.
    """
    tools_result = await session.list_tools()
    available = {t.name for t in tools_result.tools}
    missing = REQUIRED_TOOLS - available
    if missing:
        raise RuntimeError(
            f"GitHub MCP server is missing required tools: {sorted(missing)}. "
            f"Available tools: {sorted(available)}"
        )
    logger.info("github_mcp_tools_validated", tools=sorted(REQUIRED_TOOLS))


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


async def read_file(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    allowed_prefixes: tuple[str, ...] = _DEFAULT_READ_PREFIXES,
) -> str:
    """
    Read a file from the repo. Path must start with one of allowed_prefixes
    (default: "demo-infra/" or ".github/").
    Returns the decoded file contents as a string.
    """
    _enforce_read_path(path, allowed_prefixes)
    kwargs: dict[str, Any] = {"owner": owner, "repo": repo, "path": path}
    if ref:
        kwargs["ref"] = ref
    logger.info("github_mcp_read_file", path=path)
    result = await session.call_tool("get_file_contents", kwargs)
    return _extract_file_contents(result)


async def list_directory(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    path: str,
    allowed_prefixes: tuple[str, ...] = _DEFAULT_READ_PREFIXES,
) -> list[str]:
    """
    List file paths in a repo directory.

    Path must start with one of allowed_prefixes.
    Returns [] if the directory is empty, does not exist, or the MCP call fails —
    callers should treat an empty list as "nothing found" rather than an error.
    """
    _enforce_read_path(path, allowed_prefixes)
    logger.info("github_mcp_list_directory", path=path)
    try:
        result = await session.call_tool(
            "get_file_contents",
            {"owner": owner, "repo": repo, "path": path},
        )
        return _extract_directory_listing(result)
    except Exception as exc:
        # Directory may not exist yet (e.g. scripts/ is empty in the fixture).
        # Return an empty list rather than propagating the error.
        logger.warning("github_mcp_list_directory_empty", path=path, error=str(exc))
        return []


async def create_branch(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    branch: str,
    from_branch: str,
) -> None:
    """Create a new branch from from_branch."""
    logger.info("github_mcp_create_branch", branch=branch, from_branch=from_branch)
    await session.call_tool(
        "create_branch",
        {"owner": owner, "repo": repo, "branch": branch, "from_branch": from_branch},
    )


async def write_file(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    path: str,
    content: str,
    commit_message: str,
    branch: str,
    policy: Any,
) -> None:
    """
    Create or update a file on branch.

    Path is validated against the injected policy before any MCP call is made.
    Handles the SHA requirement for updates: attempts a create first; if the
    server signals the file already exists (422 / "sha" / "already exists"),
    fetches the current SHA and retries as an update.
    """
    _enforce_write_path(path, policy)  # explicit guard — not an assert

    kwargs: dict[str, Any] = {
        "owner": owner,
        "repo": repo,
        "path": path,
        "content": content,
        "message": commit_message,
        "branch": branch,
    }

    logger.info("github_mcp_write_file", path=path, branch=branch)
    try:
        await session.call_tool("create_or_update_file", kwargs)
    except Exception as e:
        err = str(e).lower()
        if "sha" in err or "already exists" in err or "422" in err:
            logger.info("github_mcp_write_file_sha_retry", path=path)
            # File exists on this branch — get its SHA and retry as update
            existing = await session.call_tool(
                "get_file_contents",
                {"owner": owner, "repo": repo, "path": path, "ref": branch},
            )
            sha = _extract_sha(existing)
            await session.call_tool("create_or_update_file", {**kwargs, "sha": sha})
        else:
            raise


async def create_pull_request(
    session: ClientSession,
    *,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> str:
    """
    Open a draft PR from head → base. Returns the GitHub PR HTML URL.
    Draft=True is always set; InfraPilot never merges automatically.
    """
    logger.info("github_mcp_create_pr", head=head, base=base)
    try:
        result = await session.call_tool(
            "create_pull_request",
            {
                "owner": owner,
                "repo": repo,
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": True,
            },
        )
    except Exception as e:
        # GitHub returns 422 "already_exists" when a PR already exists for this branch.
        # The error message often includes the existing PR URL — extract and return it
        # so the agent is idempotent on same-day re-runs.
        err_str = str(e)
        if "already exists" in err_str.lower() or "422" in err_str:
            import re as _re
            match = _re.search(r"https://github\.com/[^\s\"']+/pull/\d+", err_str)
            if match:
                existing_url = match.group(0)
                logger.info("github_mcp_pr_already_exists", pr_url=existing_url)
                return existing_url
        raise

    # _extract_pr_url raises ValueError when the result is an error response
    # (e.g. 422 "PR already exists").  Catch it here — inside the MCP session —
    # so the ValueError never propagates out through anyio's stdio TaskGroup and
    # gets wrapped in ExceptionGroup.
    try:
        pr_url = _extract_pr_url(result)
    except ValueError:
        # The result may be an error response from GitHub.  Check the raw text for
        # a PR URL or "already exists" signal, then raise a plain ValueError
        # (NOT an ExceptionGroup) so the caller sees a clean error.
        import re as _re
        raw = _text_content(result)
        match = _re.search(r"https://github\.com/[^\s\"']+/pull/\d+", raw)
        if match:
            existing_url = match.group(0)
            logger.info("github_mcp_pr_already_exists_from_result", pr_url=existing_url)
            pr_url = existing_url
        else:
            logger.error("github_mcp_create_pr_error_result", raw=raw[:500])
            raise ValueError(f"GitHub PR creation failed: {raw[:300]}") from None

    logger.info("github_mcp_pr_created", pr_url=pr_url)
    return pr_url
