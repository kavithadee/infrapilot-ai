"""
Pydantic schemas for the v1.6 GitHub MCP remediation feature.

Safety model:
  FixFile.content_no_live_mutations — stateless keyword check on generated file
    content; runs at LLM-output parse time as a first line of defence.

  Path validation is intentionally NOT done at the Pydantic level.
  RemediationPolicy.check_write_path() requires the service_root that is only
  known at runtime (resolved from SERVICE_REPO_MAP).  Path checks are enforced
  in fix_spec_agent.py via policy.check_write_path() before any MCP write call.

  Prose fields (pr_body, test_plan, risk_notes, change_summary) are never
  checked for unsafe keywords — explanatory text is fine.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.guardrails.remediation_policy import UNSAFE_CONTENT_KEYWORDS

# ---------------------------------------------------------------------------
# FixFile — one generated file in the PR
# ---------------------------------------------------------------------------


class FixFile(BaseModel):
    path: str = Field(description="Repo-relative path of the file to create/update")
    content: str = Field(description="Full file contents to write")
    commit_message: str = Field(description="Git commit message for this file")

    @field_validator("content")
    @classmethod
    def content_no_live_mutations(cls, v: str) -> str:
        """
        Reject generated file content containing live infra mutation commands.

        Path validation is handled separately by RemediationPolicy.check_write_path()
        in fix_spec_agent.py — it requires the service-scoped policy instance.
        """
        lower = v.lower()
        for keyword in UNSAFE_CONTENT_KEYWORDS:
            if keyword in lower:
                raise ValueError(
                    f"Generated file content contains an unsafe command: '{keyword}'. "
                    f"The fix spec agent must not emit live infrastructure mutation commands."
                )
        return v


# ---------------------------------------------------------------------------
# FixSpec — the full remediation spec returned by the LLM
# ---------------------------------------------------------------------------


class FixSpec(BaseModel):
    branch_name: str = Field(
        description="New branch to create, e.g. 'infrapilot/audit-schema-validation-20240101'"
    )
    pr_title: str = Field(description="GitHub PR title")
    pr_body: str = Field(
        description=(
            "GitHub PR description (markdown). May contain explanatory prose — "
            "this field is NOT checked for unsafe keywords."
        )
    )
    files: list[FixFile] = Field(
        description="Files to create/update on the branch (1–3 files)",
        min_length=1,
        max_length=3,
    )
    change_summary: str = Field(
        description="Brief description of what this fix does and why (prose, not checked for unsafe keywords)"
    )
    test_plan: str = Field(
        description="How to verify the fix works (prose, not checked for unsafe keywords)"
    )
    risk_notes: str = Field(
        description="Known risks and mitigations (prose, not checked for unsafe keywords)"
    )


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------


class CreateRemediationDraftRequest(BaseModel):
    selected_recommendation: str = Field(
        description="The exact recommended action text the user selected from the investigation report"
    )


class RemediationDraftDetail(BaseModel):
    """Returned by all three remediation endpoints."""

    model_config = {"from_attributes": True}

    id: UUID
    run_id: UUID
    status: str  # "drafting" | "pr_created" | "failed"
    selected_recommendation: str
    fix_spec_json: dict | None = None
    target_repo: str
    base_branch: str
    branch_name: str | None = None
    github_pr_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
