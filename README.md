# InfraPilot AI

An agentic on-call copilot that investigates infrastructure incidents and closes the loop to a real GitHub draft PR — without ever merging automatically.

Submit an incident description → InfraPilot runs an OpenAI tool-calling loop across five simulated infra tools → returns a structured root-cause report with evidence, timeline, and recommendations. For eligible incidents it generates a validated, runnable pre-deploy fix and opens a draft PR on GitHub for human review.

**Live demo:** https://infrapilot-ai-phi.vercel.app

Frontend is hosted on Vercel; the FastAPI backend is deployed on Railway.

---

## Why this project matters

InfraPilot is designed to demonstrate the engineering concerns behind production agentic systems: tool orchestration, bounded context, structured outputs, deterministic guardrails, eval scenarios, caching, persistence, and human-in-the-loop remediation. The demo intentionally uses seeded infrastructure data so the full workflow can be evaluated without connecting real production systems.

---

## Architecture

```
┌──────────────┐     POST /incidents      ┌──────────────────────────────────┐
│   Frontend   │ ──────────────────────▶  │  FastAPI + BackgroundTask        │
│  (React/Vite)│ ◀──────────────────────  │                                  │
└──────────────┘   GET /runs/{id}         │  investigator.py                 │
                                          │   OpenAI tool-calling loop       │
                                          │   max 8 iters, ≥3 tools required │
                                          │   └─ BaseTool.run()              │
                                          │       Redis cache → execute()    │
                                          │       → log ToolCall to DB       │
                                          └──────────────┬───────────────────┘
                                                         │
                                    ┌────────────────────┼────────────────────┐
                                    ▼                    ▼                    ▼
                               Postgres               Redis            GitHub MCP
                          (incidents, runs,        (tool cache,      (v1.6 branch +
                           tool_calls, drafts)      60 s TTL)         file + PR ops)

Remediation pipeline (v1.6):
  POST /runs/{id}/remediation-drafts
    1. RemediationClassifier  — keyword rules, no LLM
    2. RepoContextResolver    — GitHub MCP reads 5 constrained paths
    3. FixSpecAgent           — single OpenAI structured-output call
    4. ValidationGate         — AST + policy checks, one repair attempt
    5. MCP write session      — branch → files → draft PR
```

---

## Agent memory & context

The agent operates within a single run — there is no persistent memory across runs.

**Within a run:**
- A `messages` list is accumulated in `investigator.py` and passed to every OpenAI call in the loop. Tool call results are appended as `tool` role messages, giving the model full visibility of everything it has seen in the current investigation.
- **Max iterations: 8.** The loop hard-stops at 8 tool calls regardless of whether the agent has called `generate_report`. This bounds token cost and prevents runaway loops.
- **Min tool calls: 3.** The agent cannot call `generate_report` (the finalization tool) until it has invoked at least 3 real infra tools. This is enforced by checking `tool_call_count` before allowing `generate_report` to execute — the model can't short-circuit to an answer without gathering evidence first.

**Tool-level caching (Redis, 60 s TTL):**
- `BaseTool.run()` checks Redis before calling `execute()`. Identical inputs within 60 s return a cached result, marked `cache_hit: true` in the tool call log.
- On Redis failure, the tool runs normally — no disruption to the agent loop.

**No cross-run memory.** Each investigation starts fresh. There is no retrieval over past runs, no vector store, and no session persistence beyond the duration of a single background task.

---

## Guardrails

InfraPilot uses layered, deterministic guardrails at every stage where the model could produce harmful or incorrect output.

### Investigation loop

| Guardrail | Mechanism |
|---|---|
| Minimum evidence requirement | Agent cannot call `generate_report` until `tool_call_count ≥ 3` |
| Output schema validation | Final report validated against `InvestigationReport` Pydantic model; one retry on failure |
| Loop cap | Hard limit of 8 iterations prevents runaway tool-calling |
| `generate_report` isolation | Not in `TOOL_REGISTRY`; never cached, never logged as an infra tool call |

### Remediation pipeline

```
Classifier (deterministic, no LLM)
  rollback / kubectl / migration / alter table → 422 blocked immediately
  schema / validation / compatibility / pre-deploy → proceed
  ↓
Policy write-path guard (before any MCP write)
  reject '..' path traversal segments
  reject blocklist: .env*, **/secrets/**, **/k8s/**, **/terraform/**, **/migrations/**
  reject if not in allowlist: {service_root}/scripts/*.py, {service_root}/tests/*.py,
                              .github/workflows/*validation*.yml
  ↓
Content safety (every generated file)
  reject: bq update, bq mk, kubectl apply/delete, alter table, drop table, gcloud secrets
  ↓
Code quality gate (Python files only)
  ast.parse() — syntax validation
  no hardcoded schema patterns (e.g. production_schema =)
  reads from sys.argv or open() — not inline data
  ↓
  fail → one repair OpenAI call with full error list → fail again → draft=failed, no PR
  ↓
MCP write session (only if all checks pass)
  create_branch → write files → create draft PR
```

The classifier is **deterministic keyword matching, not an LLM** — it cannot be prompt-injected past. Blocked keywords are evaluated before allowed keywords, so a recommendation containing both is always rejected.

The same classifier logic is mirrored in the frontend (`isRemediationEligible()`) so ineligible actions never surface the Draft PR button.

---

## Human-in-the-loop

InfraPilot is explicitly designed around human review at the output boundary.

**Investigation output:** The agent produces a structured report (evidence, timeline, confidence score, recommended actions) and stops. It never takes action on the findings — no restarts, no rollbacks, no automated deployments.

**Remediation output:** For eligible recommendations, the pipeline generates code and opens a **draft PR only**. The PR cannot be auto-merged. A human must review the diff, run the CI, and merge manually.

```
Agent diagnoses → human reads report
Agent generates fix → human reviews draft PR → human merges (or closes)
```

The draft PR contains three pre-validated files:

| File | Purpose |
|---|---|
| `demo-infra/audit-service/scripts/validate_bq_schema.py` | Reads both schema files via `sys.argv`, compares field names, exits 1 on mismatch |
| `demo-infra/audit-service/tests/test_validate_bq_schema.py` | Runnable pytest tests with portable `pathlib.Path(__file__)` paths |
| `.github/workflows/audit-schema-validation.yml` | CI workflow triggered on changes to the service directory |

The generated CI workflow, once merged, would block future deploys that introduce the same class of schema drift — closing the loop without requiring another human to remember to add the check.

---

## Evals

The three seeded scenarios function as adversarial evals — each is designed to defeat naive reasoning and require a different multi-hop strategy.

| Scenario | Service | What makes it hard | Expected agent path |
|---|---|---|---|
| BigQuery auth failure | `lat-cron-job` | Pod is healthy; logs are sparse. No obvious error surface. | `get_recent_deploys` → `get_config_diff` → `get_bq_insert_errors` → secret path changed in v42 |
| Latency spike | `api-service` | A deploy exists near the spike and looks guilty. It's innocent. | `get_recent_deploys` → `get_config_diff` (frontend-only diff, ruled out) → `get_service_logs` → DB pool exhausted |
| Silent data loss | `audit-service` | **No error logs at all.** Zero rows written is itself the signal. | `get_recent_deploys` → `get_config_diff` (schema file changed) → `get_bq_insert_errors` → SCHEMA_ERROR, 0 rows written |

**Scenario 2 is specifically designed to test red-herring rejection.** The deploy went out 2 hours before the spike, and the diff is frontend-only. The agent must reason about the timeline gap and diff content to rule it out — then pivot to logs for the real cause.

**Scenario 3 has no error logs.** The absence of log noise is intentional. The agent has to notice that 0 rows written in 30 minutes is an anomaly, then trace it to a BQ SCHEMA_ERROR through the deploy and config diff tools.

The test suite (`tests/unit/`, `tests/integration/`) mocks OpenAI and GitHub MCP at the network boundary. Integration tests assert that the correct tool sequence is called and that the report schema validates — not just that the model returns text.

---

## Infra tools

Each tool extends `BaseTool`. The base `run()` handles Redis caching, timing, and DB logging; tools implement only `execute(input, db)`.

### `get_recent_deploys`

```json
// Input
{ "service_name": "audit-service" }

// Output
[
  {
    "deploy_id": "v9",
    "service_name": "audit-service",
    "deployed_at": "2024-01-15T10:30:00Z",
    "deployed_by": "ci-bot",
    "commit_sha": "abc123",
    "status": "success",
    "version": "9"
  }
]
```

### `get_service_logs`

```json
// Input
{ "service_name": "audit-service", "time_window": "1h", "query": "error" }

// Output
[
  {
    "timestamp": "2024-01-15T10:32:00Z",
    "level": "INFO",
    "message": "Audit event received, dispatching to BigQuery writer",
    "service": "audit-service"
  },
  {
    "timestamp": "2024-01-15T10:33:00Z",
    "level": "INFO",
    "message": "BigQuery writer completed batch",
    "service": "audit-service"
  }
]
```

### `get_k8s_pod_status`

```json
// Input
{ "service_name": "audit-service" }

// Output
{
  "service_name": "audit-service",
  "pod_name": "audit-service-7d9f8b-xk2p",
  "status": "Running",
  "ready": true,
  "restart_count": 0,
  "cpu_usage": "45m",
  "memory_usage": "128Mi"
}
```

### `get_bq_insert_errors`

```json
// Input
{ "table_name": "audit.events", "time_window": "1h" }

// Output
[
  {
    "error_type": "SCHEMA_ERROR",
    "error_message": "No such field: user_agent",
    "count": 1847,
    "first_seen": "2024-01-15T10:31:00Z",
    "last_seen": "2024-01-15T11:00:00Z",
    "table_name": "audit.events"
  }
]
```

### `get_config_diff`

```json
// Input
{ "service_name": "audit-service", "deploy_id": "v9" }

// Output
{
  "deploy_id": "v9",
  "service_name": "audit-service",
  "changes": [
    {
      "key": "bigquery.schema_file",
      "before": "schemas/audit_event_v1.json",
      "after": "schemas/audit_event_v2.json",
      "change_type": "modified"
    }
  ],
  "commit_message": "feat: add user_agent field to audit events"
}
```

---

## API reference

### `POST /incidents`

Start an investigation. Returns immediately; agent runs in the background.

```json
// Request
{
  "title": "No audit data for 30 mins",
  "description": "audit-service logs show no audit events written to BigQuery in the last 30 minutes",
  "service_name": "audit-service",
  "severity": "high"   // "low" | "medium" | "high" | "critical"
}

// Response 201
{
  "incident_id": "3fa85f64-...",
  "run_id": "7c9e6679-...",
  "status": "pending"
}
```

### `GET /runs/{run_id}`

Poll for investigation status and the final report.

```json
// Response — completed
{
  "status": "completed",   // "pending" | "running" | "completed" | "failed"
  "report_json": {
    "incident_summary": "audit-service stopped writing to BigQuery after deploy v9...",
    "likely_root_cause": "Deploy v9 added user_agent field in code but the production BQ table was never migrated.",
    "confidence_score": 0.95,
    "evidence": [
      {
        "tool": "get_bq_insert_errors",
        "finding": "1847 SCHEMA_ERROR events since 10:31 UTC — 'No such field: user_agent'",
        "significance": "Directly explains why 0 rows were written"
      }
    ],
    "timeline": [
      { "timestamp": "10:30 UTC", "event": "Deploy v9 pushed", "source": "get_recent_deploys" },
      { "timestamp": "10:31 UTC", "event": "BQ SCHEMA_ERRORs begin", "source": "get_bq_insert_errors" }
    ],
    "recommended_actions": [
      {
        "action": "Add a pre-deploy schema compatibility validation check",
        "priority": "short_term",
        "rationale": "Prevents schema drift from silently dropping writes"
      }
    ],
    "tools_used": ["get_recent_deploys", "get_config_diff", "get_bq_insert_errors"],
    "final_summary": "Schema mismatch introduced in v9 caused all BQ writes to fail silently."
  }
}
```

### `GET /runs/{run_id}/tool-calls`

Ordered tool-call trace with inputs, outputs, latency, and cache status.

```json
[
  {
    "sequence_num": 1,
    "tool_name": "get_recent_deploys",
    "input_json": { "service_name": "audit-service" },
    "output_json": [ { "deploy_id": "v9", "deployed_at": "..." } ],
    "latency_ms": 42,
    "cache_hit": false,
    "status": "success"
  },
  {
    "sequence_num": 2,
    "tool_name": "get_config_diff",
    "input_json": { "service_name": "audit-service", "deploy_id": "v9" },
    "output_json": { "changes": [ { "key": "bigquery.schema_file", "..." } ] },
    "latency_ms": 5,
    "cache_hit": true,
    "status": "success"
  }
]
```

### `POST /runs/{run_id}/remediation-drafts`

Trigger the remediation pipeline. Returns immediately; PR creation runs in the background.

```json
// Request
{ "selected_recommendation": "Add a pre-deploy schema compatibility validation check" }

// Response 201
{
  "id": "d1e2f3...",
  "run_id": "7c9e6679-...",
  "status": "drafting",
  "selected_recommendation": "Add a pre-deploy schema compatibility validation check",
  "fix_spec_json": null,
  "branch_name": null,
  "github_pr_url": null,
  "created_at": "2024-01-15T11:05:00Z"
}
```

| Status code | Meaning |
|---|---|
| `201` | Draft created; poll `GET /remediation-drafts/{id}` |
| `400` | Run not yet completed |
| `422` | Recommendation blocked by classifier or service not eligible |
| `503` | `GITHUB_PERSONAL_ACCESS_TOKEN` not set |

### `GET /remediation-drafts/{draft_id}`

Poll until `status` transitions out of `"drafting"`.

```json
// Response — pr_created
{
  "id": "d1e2f3...",
  "status": "pr_created",   // "drafting" | "pr_created" | "failed"
  "branch_name": "infrapilot/audit-service-schema_validation-20240115-d1e2f3a4",
  "github_pr_url": "https://github.com/kavithadee/infrapilot-ai/pull/7",
  "fix_spec_json": {
    "pr_title": "Add Schema Validation CI for audit-service",
    "files": [
      { "path": "demo-infra/audit-service/scripts/validate_bq_schema.py", "commit_message": "Add BQ schema validation script" },
      { "path": "demo-infra/audit-service/tests/test_validate_bq_schema.py", "commit_message": "Add schema validation tests" },
      { "path": ".github/workflows/audit-schema-validation.yml", "commit_message": "Add schema validation CI workflow" }
    ],
    "change_summary": "Introduces a CI workflow that validates BQ schema compatibility before deploy.",
    "risk_notes": "Read-only validation script; no mutations to production resources."
  }
}
```

---

## GitHub MCP operations

The remediation pipeline uses [`github-mcp-server`](https://github.com/github/github-mcp-server) v1.2.0 via the Python MCP SDK. Two sessions are opened per run to prevent anyio `ExceptionGroup` from wrapping LLM/validation errors (a read-only session for context discovery, closed before the LLM call; a write session opened only after all validation passes).

### Read session (`RepoContextResolver`)

| Operation | Arguments | Purpose |
|---|---|---|
| `list_directory` | `path: "{service_root}/schemas"` | Discover schema/config files to read |
| `list_directory` | `path: "{service_root}/scripts"` | Confirm write target exists |
| `list_directory` | `path: "{service_root}/tests"` | Confirm write target exists |
| `list_directory` | `path: "{service_root}"` | Top-level service listing |
| `list_directory` | `path: ".github/workflows"` | Discover existing CI workflow names |
| `get_file_contents` | `path: "{schema_file}"` | Read schema files for LLM context |

All read paths are prefix-guarded: must start with `demo-infra/` or `.github/`.

### Write session (`fix_spec_agent`)

| Operation | Arguments | Purpose |
|---|---|---|
| `create_branch` | `branch: "infrapilot/...-{short_id}", base: "main"` | Create fix branch |
| `create_or_update_file` | `path, content, message, branch` | Write each generated file (policy-checked before each call) |
| `create_pull_request` | `title, body, head, base, draft: true` | Open draft PR for human review |

---

## Tech stack

| Layer | Technology | Notes |
|---|---|---|
| API | FastAPI + Uvicorn | Sync SQLAlchemy; no Alembic (`create_all` on startup) |
| Agent | OpenAI gpt-4o tool-calling | Structured output via JSON mode + Pydantic |
| Database | PostgreSQL + SQLAlchemy | 9 tables: incidents, runs, tool_calls, 5 simulated data tables, remediation_drafts |
| Cache | Redis | 60 s TTL per tool call; graceful degradation on connection failure |
| GitHub | github-mcp-server v1.2.0 | Python MCP SDK; binary pinned in Dockerfile |
| Frontend | React 19 + Vite + TanStack Router | Tailwind + shadcn/ui; polling every 2 s |
| Tests | pytest + pytest-asyncio | 66 tests; OpenAI and MCP both mocked at the network boundary |

---

## Quickstart

**Prerequisites:** Docker Desktop, an OpenAI API key.

```bash
git clone https://github.com/kavithadee/infrapilot-ai
cd infrapilot-ai
cp .env.example .env
# Add your OPENAI_API_KEY to .env
docker compose up --build
```

- **API:** http://localhost:8000
- **Frontend:** http://localhost:5173
- Seed data loads automatically on startup (idempotent).

For the remediation feature, add to `.env`:

```bash
GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...   # fine-grained PAT: Contents + Pull requests (read/write)
GITHUB_TARGET_REPO=kavithadee/infrapilot-ai
GITHUB_BASE_BRANCH=main
```

> **Production path:** Replace the fine-grained PAT with a GitHub App installation token for per-installation audit logs, automatic token rotation, and org-level scoping.

> **Idempotency:** The remediation pipeline is idempotent for the demo scenario. If a `pr_created` draft already exists for the `audit-service` schema-validation remediation, the backend returns the existing PR immediately — no OpenAI call, no new branch. The deterministic branch `infrapilot/demo-audit-schema-validation` is reused across runs; a GitHub-side fallback (`list_pull_requests`) handles the case where the database was wiped but the PR still exists.

---

## Running tests

```bash
docker compose exec api pytest                                         # 66 tests
docker compose exec api pytest tests/unit/test_remediation.py -v      # 26 remediation unit tests
docker compose exec api pytest tests/integration/                      # full API flow (mocked OpenAI)
```

OpenAI and GitHub MCP are both mocked at the network boundary — no real API calls needed.

---

## Codebase map

```
backend/
  app/
    agents/
      investigator.py              # OpenAI tool-calling loop; manages message history
      report_builder.py            # Parses + validates InvestigationReport; retries once
      fix_spec_agent.py            # 4-stage remediation pipeline
      generated_code_validator.py  # AST + pattern checks on generated Python
    guardrails/
      remediation_classifier.py    # Deterministic keyword classifier
      remediation_policy.py        # Write-path guard + content safety rules
      service_registry.py          # SERVICE_REPO_MAP; service → repo + service_root
    services/
      github_mcp.py                # MCP session; read/write/PR helpers; path guards
      repo_context_resolver.py     # Discovers schema/script/test paths via MCP
    tools/
      base.py                      # BaseTool ABC: cache + log wrapper around execute()
      registry.py                  # TOOL_REGISTRY + build_openai_tools_spec()
      get_recent_deploys.py
      get_service_logs.py
      get_k8s_pod_status.py
      get_bq_insert_errors.py
      get_config_diff.py
    api/
      incidents.py                 # POST /incidents, GET /incidents
      runs.py                      # GET /runs/{id}, GET /runs/{id}/tool-calls
      remediation.py               # POST + 2× GET remediation drafts
    db/
      models.py                    # 8 ORM models (+ RemediationDraft)
      repositories.py              # All DB reads/writes; no SQL outside this file
    schemas/
      report.py                    # InvestigationReport Pydantic model
      remediation.py               # FixSpec, FixFile, RemediationDraftDetail

frontend/src/
  routes/runs.$runId.tsx           # Run detail page with polling + remediation section
  components/infrapilot/
    RemediationDraftCard.tsx       # Draft PR lifecycle (idle → drafting → result)
    Hero.tsx / DemoScenarios.tsx / Workflow.tsx
    ToolCallTimeline.tsx / EvidenceList.tsx / ActionsList.tsx
  lib/
    infrapilot-api.ts              # API client + types
    remediation-api.ts             # Remediation client + isRemediationEligible()
```

---

## Intentional simulation

All infra data is seeded into Postgres tables. Tool interfaces are designed so each could be swapped for a real implementation (Loki MCP, GCP MCP, `kubectl`) without changing the agent loop.

| Tool | Real equivalent | Simulated via |
|---|---|---|
| `get_recent_deploys` | CI/CD API (GitHub Actions, Spinnaker) | `simulated_deploys` table |
| `get_service_logs` | Loki / CloudWatch / Stackdriver | `simulated_logs` table |
| `get_k8s_pod_status` | kube-apiserver | `simulated_k8s_status` table |
| `get_bq_insert_errors` | BQ `INFORMATION_SCHEMA.STREAMING_TIMELINE` | `simulated_bq_errors` table |
| `get_config_diff` | Vault / git log | `simulated_config_diffs` table |
| GitHub operations | GitHub REST API | Real API via github-mcp-server |

---

## What production would add

- **Alembic** for schema migrations (currently `Base.metadata.create_all` on startup)
- **Worker queue** (RQ / Celery) to replace `BackgroundTask` — survives process restarts
- **OpenTelemetry** spans per tool call and agent iteration
- **Real data sources** — swap simulated tools for MCP servers (Loki MCP, GCP MCP, etc.)
- **GitHub App** for remediation PRs — no personal account association, automatic token rotation
- **Authentication** on all endpoints (currently open for demo)
- **Branch protection rules** enforcing the generated CI workflow before merge is allowed
- **Persistent agent memory** — vector store over past runs for cross-incident pattern recognition
