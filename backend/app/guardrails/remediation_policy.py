"""
remediation_policy.py — pattern-based write path and content safety rules.

Safety model:
  - Allowed write patterns are scoped to the resolved service_root for the
    current run, plus .github/workflows/ patterns for CI files.
  - Blocked patterns are evaluated before the allowlist — blocklist wins.
  - File content is checked for live infrastructure mutation keywords.
  - Policy is instantiated per-run with service_root from service_registry.py.

No service-to-repo mapping lives here — see service_registry.py for that.
"""

from __future__ import annotations

import fnmatch

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fnmatch_recursive(path: str, pattern: str) -> bool:
    """
    fnmatch-style match that treats '**' as matching any number of path segments
    (including zero), unlike stdlib fnmatch which treats '**' as a literal
    double-star matching within a single segment.

    This is needed for blocklist patterns like '**/secrets/**' to correctly
    catch 'demo-infra/audit-service/secrets/creds.json' as well as a bare
    'secrets/key.json'.

    Algorithm: split both path and pattern on '/' and process segment by segment,
    expanding '**' non-greedily against zero or more segments.
    """
    parts = path.split("/")
    pats = pattern.split("/")

    def _match(pi: int, si: int) -> bool:
        """Recursive match of pattern parts[pi:] against path parts[si:]."""
        while pi < len(pats):
            if pats[pi] == "**":
                # '**' matches zero or more segments — try each position.
                pi += 1
                for skip in range(si, len(parts) + 1):
                    if _match(pi, skip):
                        return True
                return False
            if si >= len(parts):
                return False
            if not fnmatch.fnmatch(parts[si], pats[pi]):
                return False
            pi += 1
            si += 1
        return si == len(parts)

    return _match(0, 0)


# ---------------------------------------------------------------------------
# Unsafe content keywords — applied to generated file content only.
# Prose fields (pr_body, test_plan, risk_notes) are NOT checked here.
# ---------------------------------------------------------------------------

UNSAFE_CONTENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "bq update",
        "bq mk",
        "kubectl apply",
        "kubectl delete",
        "kubectl exec",
        "alter table",
        "drop table",
        "drop database",
        "secret create",
        "secret patch",
        "gcloud secrets",
    }
)

# ---------------------------------------------------------------------------
# Blocked write patterns — checked before the allowlist (blocklist wins).
# These are global: no service_root substitution needed.
# ---------------------------------------------------------------------------

_BLOCKED_WRITE_PATTERNS: tuple[str, ...] = (
    ".env*",
    "**/.env*",
    "**/secrets/**",
    "**/credentials/**",
    "**/k8s/**",
    "**/terraform/**",
    "**/migrations/**",
    "**/alembic/**",
)


class RemediationPolicy:
    """
    Write-path and content-safety rules for a single remediation run.

    Scoped to service_root so that write access is restricted to the resolved
    service directory, not the entire demo-infra tree.

    Usage:
        policy = RemediationPolicy("demo-infra/audit-service")

        allowed, reason = policy.check_write_path(
            "demo-infra/audit-service/scripts/validate.py"
        )  # → (True, "")

        safe, reason = policy.check_file_content(generated_code)
        # → (False, "...bq update...") if the LLM emitted a mutation command
    """

    def __init__(self, service_root: str) -> None:
        self.service_root = service_root.rstrip("/")

    @property
    def allowed_write_patterns(self) -> tuple[str, ...]:
        """
        Write path patterns allowed for this service_root.
        All patterns use fnmatch-style globs (single path level).
        """
        return (
            f"{self.service_root}/scripts/*.py",
            f"{self.service_root}/tests/*.py",
            ".github/workflows/*validation*.yml",
            ".github/workflows/*validation*.yaml",
            ".github/workflows/*guardrail*.yml",
            ".github/workflows/*guardrail*.yaml",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_write_path(self, path: str) -> tuple[bool, str]:
        """
        Validate a proposed write path.

        Returns (True, "") if the path is allowed.
        Returns (False, reason) if rejected.

        Evaluation order:
          0. Traversal guard — reject any path containing '..'.
          1. Blocklist — any blocked pattern match → reject immediately.
          2. Allowlist — at least one allowed pattern must match.
        """
        # Step 0: traversal guard — fnmatch does NOT normalise '..', so a path
        # like 'demo-infra/audit-service/scripts/../../../app/config.py'
        # would match 'demo-infra/audit-service/scripts/*.py'.  Reject outright.
        if ".." in path.split("/"):
            return False, (
                f"Path '{path}' contains a '..' traversal segment and is not allowed."
            )

        # Step 1: blocklist — use _fnmatch_any which handles '**' across all
        # path segments, something the stdlib fnmatch does not do.
        for pattern in _BLOCKED_WRITE_PATTERNS:
            if _fnmatch_recursive(path, pattern):
                return False, (
                    f"Path '{path}' matches blocked pattern '{pattern}'."
                )

        # Step 2: allowlist
        for pattern in self.allowed_write_patterns:
            if fnmatch.fnmatch(path, pattern):
                return True, ""

        return False, (
            f"Path '{path}' does not match any allowed write pattern. "
            f"Allowed patterns for service_root='{self.service_root}': "
            f"{list(self.allowed_write_patterns)}"
        )

    def check_file_content(self, content: str) -> tuple[bool, str]:
        """
        Check generated file content for unsafe infrastructure mutation commands.

        Returns (True, "") if safe.
        Returns (False, reason) if a banned keyword is found.
        Case-insensitive match.
        """
        lower = content.lower()
        for keyword in UNSAFE_CONTENT_KEYWORDS:
            if keyword in lower:
                return False, (
                    f"Generated content contains unsafe command: '{keyword}'. "
                    f"The remediation agent must not emit live infrastructure "
                    f"mutation commands."
                )
        return True, ""
