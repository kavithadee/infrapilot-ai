"""
test_remediation.py — unit tests for the v1.6 policy-driven remediation feature.

Tests cover (no MCP or OpenAI calls made):

  Group 1 — RemediationClassifier         (5 tests)
  Group 2 — RemediationPolicy             (8 tests)
  Group 3 — ServiceRegistry               (2 tests)
  Group 4 — FixSpec / FixFile validation  (2 tests)
  Group 5 — API pre-flight checks         (3 tests, mocked DB)
  Group 6 — GeneratedCodeValidator        (3 tests)
  Group 7 — FixSpecAgent retry logic      (3 async tests, mocked MCP + OpenAI)

All tests are deterministic and require no running services.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.guardrails.remediation_classifier import (
    UnsupportedRemediationType,
    classify_remediation_type,
)
from app.guardrails.remediation_policy import RemediationPolicy
from app.guardrails.service_registry import get_service_config
from app.schemas.remediation import FixFile, FixSpec

# ---------------------------------------------------------------------------
# Group 1 — RemediationClassifier
# ---------------------------------------------------------------------------


def test_classifier_returns_schema_validation_for_exact_demo_recommendation():
    """The Scenario 3 recommendation text must classify as schema_validation."""
    result = classify_remediation_type(
        "Add a pre-deploy schema compatibility validation check"
    )
    assert result == "schema_validation"


def test_classifier_returns_schema_validation_for_partial_keyword():
    """Any recommendation containing 'schema' or 'validation' qualifies."""
    assert classify_remediation_type("Validate schema before deploying") == "schema_validation"
    assert classify_remediation_type("Add a schema mismatch check") == "schema_validation"


def test_classifier_raises_for_blocked_rollback_keyword():
    """Rollback keyword is always blocked regardless of other content."""
    with pytest.raises(UnsupportedRemediationType, match="rollback"):
        classify_remediation_type("Rollback the deployment to v41")


def test_classifier_raises_for_blocked_migration_keyword():
    """Migration keyword is blocked — InfraPilot does not automate schema migrations."""
    with pytest.raises(UnsupportedRemediationType, match="migration"):
        classify_remediation_type("Run a database migration to add the user_agent column")


def test_classifier_raises_for_unrecognised_recommendation():
    """Text with no recognised keywords → UnsupportedRemediationType."""
    with pytest.raises(UnsupportedRemediationType):
        classify_remediation_type("Increase the Kubernetes pod replica count to 3")


# ---------------------------------------------------------------------------
# Group 2 — RemediationPolicy
# ---------------------------------------------------------------------------


def test_policy_allows_script_under_service_root():
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path(
        "demo-infra/audit-service/scripts/validate_bq_schema.py"
    )
    assert allowed is True
    assert reason == ""


def test_policy_allows_test_file_under_service_root():
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path(
        "demo-infra/audit-service/tests/test_schema_validation.py"
    )
    assert allowed is True


def test_policy_allows_validation_workflow():
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path(
        ".github/workflows/audit-schema-validation.yml"
    )
    assert allowed is True


def test_policy_rejects_path_outside_service_root():
    """Scripts in a different service's directory are not allowed."""
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path(
        "demo-infra/other-service/scripts/something.py"
    )
    assert allowed is False
    assert "does not match" in reason


def test_policy_rejects_dotenv_via_blocklist():
    """.env* paths are always blocked, even if they somehow matched an allowlist."""
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path(".env.production")
    assert allowed is False
    assert "blocked pattern" in reason


def test_policy_rejects_secrets_dir_via_blocklist():
    policy = RemediationPolicy("demo-infra/audit-service")
    allowed, reason = policy.check_write_path("demo-infra/audit-service/secrets/key.json")
    assert allowed is False
    assert "blocked pattern" in reason


def test_policy_rejects_file_with_bq_update():
    policy = RemediationPolicy("demo-infra/audit-service")
    safe, reason = policy.check_file_content(
        "#!/bin/bash\nbq update --schema schema.json my_dataset.my_table"
    )
    assert safe is False
    assert "bq update" in reason


def test_policy_accepts_safe_python_content():
    policy = RemediationPolicy("demo-infra/audit-service")
    safe, reason = policy.check_file_content(
        "import json\n\ndef validate(a, b):\n    return set(a) == set(b)\n"
    )
    assert safe is True
    assert reason == ""


# ---------------------------------------------------------------------------
# Group 3 — ServiceRegistry
# ---------------------------------------------------------------------------


def test_service_registry_returns_audit_service_config():
    config = get_service_config("audit-service")
    assert "service_root" in config
    assert config["service_root"] == "demo-infra/audit-service"
    assert "repo" in config


def test_service_registry_raises_for_unknown_service():
    with pytest.raises(ValueError, match="not supported"):
        get_service_config("nonexistent-service-xyz")


# ---------------------------------------------------------------------------
# Group 4 — FixSpec / FixFile Pydantic schema validation
# ---------------------------------------------------------------------------


def test_fix_file_rejects_content_with_bq_update():
    """content_no_live_mutations validator must fire at parse time."""
    with pytest.raises(ValidationError, match="unsafe command"):
        FixFile(
            path="demo-infra/audit-service/scripts/fix.py",
            content="import os\nos.system('bq update dataset.table schema.json')",
            commit_message="add fix",
        )


def test_fix_spec_accepts_valid_structure():
    """A well-formed FixSpec with safe content should validate without error."""
    spec = FixSpec(
        branch_name="infrapilot/audit-service-schema-validation-20260610",
        pr_title="Add schema validation check",
        pr_body="This draft PR adds a pre-deploy schema compatibility check.",
        files=[
            FixFile(
                path="demo-infra/audit-service/scripts/validate_bq_schema.py",
                content=(
                    "import json, sys\n\n"
                    "def main():\n"
                    "    print('checking schemas')\n"
                    "    sys.exit(0)\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                ),
                commit_message="Add schema validation script",
            ),
        ],
        change_summary="Adds a pre-deploy script that compares emitted and BQ schemas.",
        test_plan="Run pytest tests/test_schema_validation.py",
        risk_notes="Read-only check; no infrastructure mutations.",
    )
    assert len(spec.files) == 1
    assert spec.change_summary.startswith("Adds")


# ---------------------------------------------------------------------------
# Group 5 — API endpoint pre-flight checks (mocked DB + settings)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from app.core.db import get_db
from app.main import app


@pytest.fixture(scope="module")
def _test_db_engine():
    """Minimal in-memory DB for API pre-flight tests."""
    from app.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def api_client(_test_db_engine):
    """TestClient wired to the in-memory test DB."""
    TestSession = sessionmaker(bind=_test_db_engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@patch("app.api.remediation.settings")
def test_api_503_when_github_token_not_configured(mock_settings, api_client):
    """
    When github_token is empty the endpoint must return 503 before touching the DB.
    We patch settings explicitly so the test is independent of what .env contains.
    """
    mock_settings.github_token = ""
    resp = api_client.post(
        f"/runs/{uuid4()}/remediation-drafts",
        json={"selected_recommendation": "Add a pre-deploy schema validation check"},
    )
    assert resp.status_code == 503
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in resp.json()["detail"]


@patch("app.api.remediation.settings")
@patch("app.api.remediation.repo")
def test_api_400_when_run_not_completed(mock_repo, mock_settings, api_client):
    """Run with status != 'completed' → 400 before creating a draft row."""
    mock_settings.github_token = "ghp_fake_token"
    mock_settings.github_target_repo = "owner/repo"
    mock_settings.github_base_branch = "main"

    run_id = uuid4()
    mock_repo.get_run.return_value = MagicMock(
        id=run_id, status="running", incident_id=uuid4()
    )

    resp = api_client.post(
        f"/runs/{run_id}/remediation-drafts",
        json={"selected_recommendation": "Add a pre-deploy schema validation check"},
    )
    assert resp.status_code == 400
    assert "must complete" in resp.json()["detail"]


@patch("app.api.remediation.settings")
@patch("app.api.remediation.repo")
def test_api_422_for_blocked_recommendation(mock_repo, mock_settings, api_client):
    """Recommendation with 'rollback' keyword → 422 from classifier."""
    mock_settings.github_token = "ghp_fake_token"
    mock_settings.github_target_repo = "owner/repo"
    mock_settings.github_base_branch = "main"

    run_id = uuid4()
    incident_id = uuid4()
    mock_repo.get_run.return_value = MagicMock(
        id=run_id, status="completed", incident_id=incident_id
    )
    mock_repo.get_incident.return_value = MagicMock(
        id=incident_id, service_name="audit-service"
    )

    resp = api_client.post(
        f"/runs/{run_id}/remediation-drafts",
        json={"selected_recommendation": "Rollback the deployment to v41"},
    )
    assert resp.status_code == 422
    assert "rollback" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Group 6 — GeneratedCodeValidator
# ---------------------------------------------------------------------------

from app.agents.generated_code_validator import CodeValidationError, validate_fix_spec_code

# A correct schema comparison script: valid syntax, reads from sys.argv,
# accesses fields as dicts — should pass all validator checks.
_VALID_SCHEMA_SCRIPT = (
    "import json\n"
    "import sys\n\n"
    "def load(p):\n"
    "    with open(p) as f:\n"
    "        return json.load(f)\n\n"
    "if __name__ == '__main__':\n"
    "    emitted = load(sys.argv[1])\n"
    "    bq = load(sys.argv[2])\n"
    "    emitted_fields = {f['name'] for f in emitted['fields']}\n"
    "    bq_fields = {f['name'] for f in bq['fields']}\n"
    "    extra = emitted_fields - bq_fields\n"
    "    if extra:\n"
    "        print(f'Mismatch: {extra}')\n"
    "        sys.exit(1)\n"
    "    print('Schema compatible')\n"
)

# A script with a Python syntax error.
_SYNTAX_ERROR_SCRIPT = "def foo(x y):\n    pass\n"  # missing comma

# A script that hardcodes the production schema instead of reading from files.
_HARDCODED_SCHEMA_SCRIPT = (
    "import sys, json\n\n"
    "production_schema = {'fields': ['event_type', 'user_id']}\n"
    "local = json.load(open(sys.argv[1]))\n"
    "print('done')\n"
)


def _script_fix_spec(content: str) -> FixSpec:
    """Build a minimal FixSpec with a single scripts/ file for validator tests."""
    return FixSpec(
        branch_name="infrapilot/audit-service-schema_validation-20260610",
        pr_title="Test",
        pr_body="Test body.",
        files=[
            FixFile(
                path="demo-infra/audit-service/scripts/validate_bq_schema.py",
                content=content,
                commit_message="add script",
            )
        ],
        change_summary="Test",
        test_plan="pytest",
        risk_notes="None.",
    )


def test_validator_rejects_python_syntax_error():
    """A .py file with a syntax error must raise CodeValidationError."""
    with pytest.raises(CodeValidationError) as exc_info:
        validate_fix_spec_code(_script_fix_spec(_SYNTAX_ERROR_SCRIPT))
    assert any("syntax error" in e.lower() for e in exc_info.value.errors)


def test_validator_rejects_hardcoded_mock_schema():
    """A scripts/ file with 'production_schema =' must be rejected."""
    with pytest.raises(CodeValidationError) as exc_info:
        validate_fix_spec_code(_script_fix_spec(_HARDCODED_SCHEMA_SCRIPT))
    errors_text = " ".join(exc_info.value.errors)
    assert "production_schema" in errors_text or "hardcoded" in errors_text.lower()


def test_validator_accepts_valid_schema_comparison_script():
    """A correct schema comparison script must pass all validator checks."""
    validate_fix_spec_code(_script_fix_spec(_VALID_SCHEMA_SCRIPT))  # must not raise


# ---------------------------------------------------------------------------
# Group 7 — FixSpecAgent retry logic (async, mocked MCP + OpenAI)
# ---------------------------------------------------------------------------

from app.agents.fix_spec_agent import run_fix_spec_agent
from app.agents.generated_code_validator import CodeValidationError as _CodeValidationError
from app.db.models import RemediationDraft
from app.services.repo_context_resolver import RepoContext

# Module-level FixSpec objects shared across Group 7 tests.
_VALID_SPEC = _script_fix_spec(_VALID_SCHEMA_SCRIPT)   # passes validate_fix_spec_code
_BROKEN_SPEC = _script_fix_spec(                        # fails validate_fix_spec_code
    "production_schema = {'fields': ['a']}\nprint('done')\n"
)


@pytest.fixture
def _agent_db_session(_test_db_engine):
    """Function-scoped DB session for agent retry tests."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=_test_db_engine)
    db = Session()
    yield db
    db.close()


def _setup_draft(db) -> object:
    """Insert a RemediationDraft row and return its id."""
    from app.db import repositories as repo
    draft = repo.create_remediation_draft(
        db,
        run_id=uuid4(),  # FK not enforced in SQLite test DB
        selected_recommendation="Add a pre-deploy schema validation check",
        target_repo="owner/repo",
        base_branch="main",
    )
    return draft.id


def _mock_run():
    return MagicMock(id=uuid4(), report_json={}, status="completed")


def _mock_incident():
    return MagicMock(id=uuid4(), service_name="audit-service", description="Test")


def _make_mock_mcp_session():
    """Return an asynccontextmanager usable as a drop-in for github_mcp_session."""
    mock_mcp = MagicMock()

    @asynccontextmanager
    async def _session():
        yield mock_mcp

    return _session


_MOCK_REPO_CONTEXT = RepoContext(
    service_name="audit-service",
    service_root="demo-infra/audit-service",
    read_paths=[],
    candidate_write_dirs=["demo-infra/audit-service/scripts/"],
    existing_ci_workflows=[],
    service_context_summary="Audit service test context.",
)

_FAKE_PR_URL = "https://github.com/owner/repo/pull/99"

_MOCK_SETTINGS = {
    "github_token": "ghp_fake",
    "github_target_repo": "owner/repo",
    "github_base_branch": "main",
    "openai_api_key": "sk-fake",
    "agent_model": "gpt-4o",
}


def _agent_patches(mock_mcp_session, call_openai_rv, repair_openai_rv):
    """Return a list of patch context managers covering all external agent deps."""
    s = MagicMock(**_MOCK_SETTINGS)
    return [
        patch("app.agents.fix_spec_agent.github_mcp_session", mock_mcp_session),
        patch("app.agents.fix_spec_agent.resolve_repo_context",
              new_callable=AsyncMock, return_value=_MOCK_REPO_CONTEXT),
        patch("app.agents.fix_spec_agent._call_openai", return_value=call_openai_rv),
        patch("app.agents.fix_spec_agent._repair_openai", return_value=repair_openai_rv),
        patch("app.agents.fix_spec_agent.create_branch", new_callable=AsyncMock),
        patch("app.agents.fix_spec_agent.write_file", new_callable=AsyncMock),
        patch("app.agents.fix_spec_agent.create_pull_request",
              new_callable=AsyncMock, return_value=_FAKE_PR_URL),
        patch("app.agents.fix_spec_agent.settings", s),
    ]


@pytest.mark.asyncio
async def test_agent_does_not_call_mcp_if_validation_always_fails(_agent_db_session):
    """Both the initial and repaired FixSpec fail code validation → no branch created."""
    db = _agent_db_session
    draft_id = _setup_draft(db)
    mock_session = _make_mock_mcp_session()

    patches = _agent_patches(mock_session, _BROKEN_SPEC, _BROKEN_SPEC)
    with patches[0], patches[1], patches[2], patches[3], \
         patches[4] as mock_branch, patches[5], patches[6], patches[7]:

        with pytest.raises(_CodeValidationError):
            await run_fix_spec_agent(
                draft_id=draft_id,
                run=_mock_run(),
                incident=_mock_incident(),
                selected_recommendation="Add a pre-deploy schema validation check",
                db=db,
            )

        mock_branch.assert_not_called()

        db.expire_all()
        draft = db.get(RemediationDraft, draft_id)
        assert draft.status == "failed"


@pytest.mark.asyncio
async def test_agent_retries_openai_once_when_validation_fails(_agent_db_session):
    """Initial spec fails validation → repair is called → repaired spec passes → PR created."""
    db = _agent_db_session
    draft_id = _setup_draft(db)
    mock_session = _make_mock_mcp_session()

    patches = _agent_patches(mock_session, _BROKEN_SPEC, _VALID_SPEC)
    with patches[0], patches[1], patches[2], patches[3] as mock_repair, \
         patches[4], patches[5], patches[6], patches[7]:

        pr_url = await run_fix_spec_agent(
            draft_id=draft_id,
            run=_mock_run(),
            incident=_mock_incident(),
            selected_recommendation="Add a pre-deploy schema validation check",
            db=db,
        )

        mock_repair.assert_called_once()
        assert pr_url == _FAKE_PR_URL

        db.expire_all()
        draft = db.get(RemediationDraft, draft_id)
        assert draft.status == "pr_created"


@pytest.mark.asyncio
async def test_agent_marks_draft_failed_if_repaired_spec_still_fails(_agent_db_session):
    """Repair call also returns a broken spec → draft is marked failed, no PR."""
    db = _agent_db_session
    draft_id = _setup_draft(db)
    mock_session = _make_mock_mcp_session()

    patches = _agent_patches(mock_session, _BROKEN_SPEC, _BROKEN_SPEC)
    with patches[0], patches[1], patches[2], patches[3] as mock_repair, \
         patches[4] as mock_branch, patches[5], patches[6], patches[7]:

        with pytest.raises(_CodeValidationError):
            await run_fix_spec_agent(
                draft_id=draft_id,
                run=_mock_run(),
                incident=_mock_incident(),
                selected_recommendation="Add a pre-deploy schema validation check",
                db=db,
            )

        mock_repair.assert_called_once()
        mock_branch.assert_not_called()

        db.expire_all()
        draft = db.get(RemediationDraft, draft_id)
        assert draft.status == "failed"
