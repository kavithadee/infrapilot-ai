"""
fix_spec_agent.py — policy-driven remediation agent (v5.1).

Entry point: run_fix_spec_agent(draft_id, run, incident, selected_recommendation, db)

Pipeline:
  1. RemediationClassifier  — deterministic keyword classification      (guardrails)
  2. ServiceRegistry        — resolve service_root + repo               (guardrails)
  3. RemediationPolicy      — instantiate with service_root             (guardrails)
  4. RepoContextResolver    — MCP directory inspection, no hardcoded paths (services)
  5. MCP read               — fetch file contents for discovered paths  (services)
  6. OpenAI                 — single structured-output call → FixSpec   (agent)
  7. Policy validation      — every FixSpec file path + content checked (guardrails)
  8. MCP execution          — create_branch → write files → create PR   (services)
  9. Persist result         — update RemediationDraft row               (db)

On any exception: update draft → status=failed, error_message=str(e), then re-raise.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.db import repositories as repo
from app.db.models import Incident, InvestigationRun
from app.guardrails.remediation_classifier import (
    UnsupportedRemediationType,
    classify_remediation_type,
)
from app.guardrails.remediation_policy import RemediationPolicy
from app.guardrails.service_registry import get_service_config
from app.agents.generated_code_validator import CodeValidationError, validate_fix_spec_code
from app.schemas.remediation import FixSpec
from app.services.github_mcp import (
    create_branch,
    create_pull_request,
    github_mcp_session,
    read_file,
    write_file,
)
from app.services.repo_context_resolver import RepoContext, resolve_repo_context

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# System prompt — generic, no scenario-specific hardcoding
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are InfraPilot's remediation agent. You will be given:
  - A remediation type (e.g. "schema_validation")
  - A summary of what was found in the service's repository
  - The ACTUAL CONTENTS of relevant schema/config files discovered in the repository
  - The candidate write directories where new files should be placed
  - The developer's chosen recommended action
  - An investigation report with root cause evidence

Your task is to generate a FixSpec JSON object that defines a safe, reviewable draft PR.

---

## File paths — READ CAREFULLY

Generate exactly these 3 paths (use the actual service directory from Candidate Write Directories):

  1. {service_root}/scripts/validate_bq_schema.py   ← validation script
  2. {service_root}/tests/test_validate_bq_schema.py ← pytest tests
  3. .github/workflows/{service}-schema-validation.yml  ← CI workflow

CRITICAL PATH RULES:
  - The workflow file MUST be at .github/workflows/ at the REPOSITORY ROOT.
  - NEVER put the workflow under the service directory.
    WRONG: demo-infra/audit-service/.github/workflows/ci.yml
    RIGHT: .github/workflows/audit-schema-validation.yml
  - The workflow filename MUST contain "validation" (e.g. audit-schema-validation.yml).
  - Only .py files go under {service_root}/scripts/ and {service_root}/tests/.

---

## Validation script rules

  - MUST accept both schema file paths as command-line arguments (sys.argv[1], sys.argv[2])
    Example invocation: python3 validate_bq_schema.py schemas/emitted_schema.json schemas/bq_table_schema.json
  - MUST NOT hardcode any schema fields or paths as Python literals
  - BigQuery table schema files use this structure:
      {"fields": [{"name": "field_name", "type": "STRING", "mode": "NULLABLE"}, ...]}
    Extract field names with: {f["name"] for f in schema["fields"]}
  - Emitted event schema files may use the same structure or a flat list; inspect the
    file contents provided and parse accordingly
  - MUST compare the field names between the two schemas and exit(1) with a clear
    printed message listing missing/extra fields when there is a mismatch
  - MUST exit(0) and print "Schema compatible" when schemas match

---

## Test file rules — READ THESE CAREFULLY

  - MUST be syntactically valid Python that passes `python -m py_compile`
  - JSON strings inside Python source MUST use single outer quotes:
      CORRECT:   valid_json = '{"fields": [{"name": "event_type", "type": "STRING"}]}'
      WRONG:     valid_json = "{"fields": [{"name": "event_type"}]}"  ← SyntaxError
  - MUST use a factory fixture so tests can pass different content.
    DO NOT use type annotations in the inner factory function — they cause
    NameError at runtime if types like Path are not imported.
  - The subprocess call MUST use the FULL repo-relative path to the script
    (pytest runs from the repo root; relative paths like "../scripts/…" break).
    Compute it from __file__ so it works regardless of working directory:
      import pathlib, subprocess, pytest

      _SCRIPT = str(pathlib.Path(__file__).parent.parent / "scripts" / "validate_bq_schema.py")

      @pytest.fixture
      def make_schema_file(tmp_path):
          def _make(name, content):
              p = tmp_path / name
              p.write_text(content)
              return p
          return _make

      def test_matching_schemas_pass(make_schema_file):
          emitted = make_schema_file("emitted.json", '<valid JSON>')
          bq = make_schema_file("bq.json", '<valid JSON>')
          result = subprocess.run(["python3", _SCRIPT, str(emitted), str(bq)])
          assert result.returncode == 0
  - Test JSON content MUST use the actual field names shown in the "Repository File
    Contents" section, not invented names
  - The subprocess call MUST pass the correct number of arguments the script expects
  - MUST include at least: one test where schemas match (expect exit 0) and one where
    there is a mismatch (expect exit 1)

---

## GitHub Actions workflow rules

  - Use actions/checkout@v4 and actions/setup-python@v5 (NOT @v2 or @v4)
  - Include `python-version: "3.12"` in the setup-python step
  - Run: pip install pytest, then pytest on the test file
  - Trigger on push/pull_request with a paths filter scoped to the service directory
  - Include a comment: "Pre-deploy validation check — does not configure branch protection"
  - MUST NOT include any deployment steps

---

## STRICT PROHIBITIONS — generated content must never contain

  - bq update, bq mk, or any BigQuery mutation commands
  - kubectl, helm, or any Kubernetes commands
  - ALTER TABLE, DROP TABLE, or any SQL DDL
  - Secret rotation, key creation, or credential management
  - Any direct writes to main or merge instructions

---

Return ONLY a valid JSON object — no text, markdown, or explanation outside it.
Example of CORRECT file paths for audit-service:
{
  "branch_name": "infrapilot/audit-service-schema_validation-YYYYMMDD",
  "pr_title": "...",
  "pr_body": "...",
  "files": [
    { "path": "demo-infra/audit-service/scripts/validate_bq_schema.py", "content": "...", "commit_message": "..." },
    { "path": "demo-infra/audit-service/tests/test_validate_bq_schema.py", "content": "...", "commit_message": "..." },
    { "path": ".github/workflows/audit-schema-validation.yml", "content": "...", "commit_message": "..." }
  ],
  "change_summary": "...",
  "test_plan": "...",
  "risk_notes": "..."
}

branch_name must use today's date: REPLACE_DATE_PLACEHOLDER.
"""


def _build_system_prompt() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _SYSTEM_PROMPT.replace("REPLACE_DATE_PLACEHOLDER", today)


# ---------------------------------------------------------------------------
# OpenAI call (sync — wrapped in asyncio.to_thread by the caller)
# ---------------------------------------------------------------------------


def _call_openai(
    remediation_type: str,
    repo_context: RepoContext,
    file_contents: dict[str, str],
    report_json: dict,
    selected_recommendation: str,
    incident_description: str,
) -> FixSpec:
    """
    Single structured-output call to OpenAI.
    Returns a Pydantic-validated FixSpec or raises ValueError / ValidationError.
    """
    client = OpenAI(api_key=settings.openai_api_key, timeout=60.0)

    files_section = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in file_contents.items()
    ) or "No files were found to read."

    user_content = (
        f"## Remediation Type\n{remediation_type}\n\n"
        f"## Repository Context\n{repo_context.service_context_summary}\n\n"
        f"## Candidate Write Directories\n{repo_context.candidate_write_dirs}\n\n"
        f"## Existing CI Workflows (avoid duplicate names)\n"
        f"{repo_context.existing_ci_workflows or 'None'}\n\n"
        f"## Repository File Contents\n{files_section}\n\n"
        f"## Selected Recommendation\n{selected_recommendation}\n\n"
        f"## Investigation Report\n{json.dumps(report_json, indent=2)}\n\n"
        f"## Incident Description\n{incident_description}\n\n"
        "Generate the FixSpec JSON now."
    )

    logger.info("fix_spec_openai_call_start", model=settings.agent_model)
    response = client.chat.completions.create(
        model=settings.agent_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": user_content},
        ],
    )
    logger.info("fix_spec_openai_call_complete")

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"OpenAI returned non-JSON content: {e}") from e

    # Pydantic validates structure + content safety (content_no_live_mutations validator)
    fix_spec = FixSpec(**parsed)
    logger.info("fix_spec_parsed", files=[f.path for f in fix_spec.files])
    return fix_spec


# ---------------------------------------------------------------------------
# Repair call — second OpenAI call when code validation fails
# ---------------------------------------------------------------------------


def _repair_openai(
    remediation_type: str,
    repo_context: RepoContext,
    file_contents: dict[str, str],
    report_json: dict,
    selected_recommendation: str,
    incident_description: str,
    validation_errors: list[str],
    broken_spec: FixSpec,
) -> FixSpec:
    """
    Second structured-output call to repair a FixSpec that failed code validation.
    Passes the full error list and the broken spec back to the model.
    Returns a Pydantic-validated FixSpec or raises.
    """
    client = OpenAI(api_key=settings.openai_api_key, timeout=60.0)

    error_bullets = "\n".join(f"  - {e}" for e in validation_errors)
    files_section = "\n\n".join(
        f"### {path}\n```\n{content}\n```" for path, content in file_contents.items()
    ) or "No files were found to read."

    repair_content = (
        f"## Code Validation Errors\n"
        f"The FixSpec you generated failed with these errors:\n\n{error_bullets}\n\n"
        f"## Broken FixSpec\n{broken_spec.model_dump_json(indent=2)}\n\n"
        f"## Remediation Type\n{remediation_type}\n\n"
        f"## Repository Context\n{repo_context.service_context_summary}\n\n"
        f"## Candidate Write Directories\n{repo_context.candidate_write_dirs}\n\n"
        f"## Repository File Contents\n{files_section}\n\n"
        f"## Selected Recommendation\n{selected_recommendation}\n\n"
        "## Repair Instructions — fix ALL errors listed above:\n"
        "  1. JSON inside Python strings MUST use single outer quotes:\n"
        "         correct: valid = '{\"fields\": [...]}'\n"
        "         wrong:   valid = \"{\\\"fields\\\": [...]}\"  (use single quotes!)\n"
        "  2. The validation script MUST NOT hardcode any schema. "
        "     Use sys.argv[1] and sys.argv[2] for the two schema file paths.\n"
        "  3. Extract field names with: {f['name'] for f in schema['fields']}\n"
        "  4. pytest fixture must return a callable (factory pattern):\n"
        "         @pytest.fixture\n"
        "         def make_schema_file(tmp_path):\n"
        "             def _make(name, content):\n"
        "                 p = tmp_path / name\n"
        "                 p.write_text(content)\n"
        "                 return p\n"
        "             return _make\n"
        "\nReturn ONLY the repaired FixSpec JSON object — no text outside it."
    )

    logger.info("fix_spec_repair_call_start", model=settings.agent_model)
    response = client.chat.completions.create(
        model=settings.agent_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": repair_content},
        ],
    )
    logger.info("fix_spec_repair_call_complete")

    raw = response.choices[0].message.content
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"OpenAI repair returned non-JSON: {e}") from e

    repaired = FixSpec(**parsed)
    logger.info("fix_spec_repaired", files=[f.path for f in repaired.files])
    return repaired


# ---------------------------------------------------------------------------
# Policy validation — after LLM returns, before any MCP write
# ---------------------------------------------------------------------------


def _validate_fix_spec_against_policy(
    fix_spec: FixSpec, policy: RemediationPolicy
) -> None:
    """
    Validate every file path and content against the RemediationPolicy.
    Raises ValueError on the first violation.

    This is a second layer of defence: FixSpec.content_no_live_mutations already
    ran during Pydantic parsing; this adds the path check and a redundant content
    check using the same policy instance used by write_file().
    """
    for fix_file in fix_spec.files:
        allowed, reason = policy.check_write_path(fix_file.path)
        if not allowed:
            raise ValueError(f"FixSpec path rejected by policy: {reason}")

        safe, reason = policy.check_file_content(fix_file.content)
        if not safe:
            raise ValueError(f"FixSpec content rejected by policy: {reason}")

    logger.info("fix_spec_policy_validated", files=[f.path for f in fix_spec.files])


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------


async def run_fix_spec_agent(
    *,
    draft_id: UUID,
    run: InvestigationRun,
    incident: Incident,
    selected_recommendation: str,
    db: Session,
) -> str:
    """
    Orchestrate the full remediation pipeline. Returns the GitHub PR URL.

    Updates RemediationDraft throughout:
      - On success: status=pr_created, branch_name, fix_spec_json, github_pr_url
      - On failure: status=failed, error_message

    Raises the original exception after recording failure so the API layer
    can return an appropriate HTTP error.
    """
    try:
        # ------------------------------------------------------------------
        # Stage 1: Classify recommendation (deterministic, no LLM)
        # ------------------------------------------------------------------
        logger.info(
            "fix_spec_agent_classifying",
            recommendation=selected_recommendation[:120],
        )
        remediation_type = classify_remediation_type(selected_recommendation)
        logger.info("fix_spec_agent_classified", remediation_type=remediation_type)

        # ------------------------------------------------------------------
        # Stage 2: Resolve service config + instantiate policy
        # ------------------------------------------------------------------
        service_config = get_service_config(incident.service_name)

        # settings.github_target_repo takes precedence over the registry default
        # (the two should match in v1; this allows Railway overrides in future).
        target_repo = settings.github_target_repo or service_config["repo"]
        owner, repo_name = target_repo.split("/", 1)
        service_root = service_config["service_root"]

        policy = RemediationPolicy(service_root)
        logger.info(
            "fix_spec_agent_policy_ready",
            service_root=service_root,
            allowed_write_patterns=list(policy.allowed_write_patterns),
        )

        # ------------------------------------------------------------------
        # Stage 3: MCP session 1 (read-only) — resolve context + fetch files
        # Closed before LLM calls so exceptions from validation/OpenAI never
        # propagate through anyio's stdio TaskGroup (which wraps them in
        # ExceptionGroup and loses the original exception type).
        # ------------------------------------------------------------------
        async with github_mcp_session() as mcp:
            logger.info("fix_spec_agent_resolving_context")
            repo_context = await resolve_repo_context(
                mcp,
                owner=owner,
                repo=repo_name,
                service_name=incident.service_name,
                service_root=service_root,
            )

            file_contents: dict[str, str] = {}
            for path in repo_context.read_paths:
                logger.info("fix_spec_agent_reading_file", path=path)
                file_contents[path] = await read_file(
                    mcp, owner=owner, repo=repo_name, path=path
                )
        # MCP session 1 closed — no anyio TaskGroup active from here.

        # ------------------------------------------------------------------
        # Stage 5: Generate FixSpec via OpenAI (sync call → thread)
        # ------------------------------------------------------------------
        logger.info("fix_spec_agent_generating")
        fix_spec: FixSpec = await asyncio.to_thread(
            _call_openai,
            remediation_type,
            repo_context,
            file_contents,
            run.report_json or {},
            selected_recommendation,
            incident.description,
        )

        # ------------------------------------------------------------------
        # Stage 6a: Validate FixSpec against policy (path + content safety)
        # ------------------------------------------------------------------
        # Stage 6: Combined validation gate with one repair attempt.
        # Policy errors (wrong paths) and code quality errors (bad Python) are
        # both collected and passed to the repair call so the LLM sees everything.
        # ------------------------------------------------------------------
        validation_errors: list[str] = []

        try:
            _validate_fix_spec_against_policy(fix_spec, policy)
        except ValueError as e:
            validation_errors.append(str(e))

        if not validation_errors:
            # Only run code checks if paths are valid — avoids confusing dual errors.
            try:
                validate_fix_spec_code(fix_spec)
            except CodeValidationError as e:
                validation_errors.extend(e.errors)

        if validation_errors:
            logger.warning(
                "fix_spec_validation_failed_retrying",
                error_count=len(validation_errors),
                errors=validation_errors,
            )
            fix_spec = await asyncio.to_thread(
                _repair_openai,
                remediation_type,
                repo_context,
                file_contents,
                run.report_json or {},
                selected_recommendation,
                incident.description,
                validation_errors,
                fix_spec,
            )
            # Re-validate the repaired spec — no try/except here.
            # Either error propagates to the outer except → draft=failed.
            _validate_fix_spec_against_policy(fix_spec, policy)
            validate_fix_spec_code(fix_spec)

        # Append a short draft-id suffix to guarantee branch uniqueness across
        # retries / reruns.  Without this, a second run for the same service+date
        # would hit GitHub 422 "PR already exists for that branch".
        short_id = str(draft_id).replace("-", "")[:8]
        branch = f"{fix_spec.branch_name}-{short_id}"
        logger.info("fix_spec_agent_branch_name", branch=branch)

        # ------------------------------------------------------------------
        # Stage 7: MCP session 2 (write) — create branch, files, PR
        # Opened only after the FixSpec has passed all validation gates.
        # ------------------------------------------------------------------
        async with github_mcp_session() as mcp:
            logger.info("fix_spec_agent_creating_branch", branch=branch)
            await create_branch(
                mcp,
                owner=owner,
                repo=repo_name,
                branch=branch,
                from_branch=settings.github_base_branch,
            )

            for fix_file in fix_spec.files:
                logger.info("fix_spec_agent_writing_file", path=fix_file.path)
                await write_file(
                    mcp,
                    owner=owner,
                    repo=repo_name,
                    path=fix_file.path,
                    content=fix_file.content,
                    commit_message=fix_file.commit_message,
                    branch=branch,
                    policy=policy,
                )

            logger.info("fix_spec_agent_creating_pr", branch=branch)
            pr_url = await create_pull_request(
                mcp,
                owner=owner,
                repo=repo_name,
                title=fix_spec.pr_title,
                body=fix_spec.pr_body,
                head=branch,
                base=settings.github_base_branch,
            )

        # ------------------------------------------------------------------
        # Stage 8: Persist success
        # ------------------------------------------------------------------
        repo.update_remediation_draft(
            db,
            draft_id=draft_id,
            status="pr_created",
            branch_name=branch,
            fix_spec_json=fix_spec.model_dump(mode="json"),
            github_pr_url=pr_url,
        )
        logger.info("fix_spec_agent_complete", pr_url=pr_url)
        return pr_url

    except Exception as exc:
        # Recursively unwrap anyio ExceptionGroup — raised when stdio_client's
        # TaskGroup exits with an exception alongside CancelledError from background
        # task cleanup.  Walk down until we reach a non-group exception.
        root_cause: BaseException = exc
        while hasattr(root_cause, "exceptions") and root_cause.exceptions:
            root_cause = root_cause.exceptions[0]

        logger.error(
            "fix_spec_agent_failed",
            error=str(root_cause),
            exc_type=type(root_cause).__name__,
        )
        repo.update_remediation_draft(
            db,
            draft_id=draft_id,
            status="failed",
            error_message=str(root_cause),
        )
        raise
