# InfraPilot AI

An agentic on-call copilot that investigates infrastructure incidents and closes the loop to a real GitHub draft PR — without ever merging automatically.

Submit an incident description → InfraPilot runs an OpenAI tool-calling loop across five simulated infra tools → returns a structured root-cause report with evidence, timeline, and recommendations. For eligible incidents it generates a validated, runnable pre-deploy fix and opens a draft PR on GitHub for human review.

> **Live demo:** [`infrapilot-ai.vercel.app`](https://infrapilot-ai.vercel.app) (frontend only; backend deployed on Railway)

---

## What makes this non-trivial to build

Most LLM demos stop at "the model returns some text." The hard parts here are:

**1. Keeping the agent grounded.**  
The investigation loop constrains the model to call at least 3 real infra tools before generating the final report, and validates the output against a typed Pydantic schema with a retry on failure. The model can't short-circuit to an answer — it must gather evidence first.

**2. Three scenarios that require different reasoning strategies.**  
The seed data is specifically designed so the same reasoning pattern doesn't solve all three. Scenario 2 has a deploy that *looks* guilty (it went out near the latency spike) but is innocent — the agent has to reason about timeline gaps and diff content to dismiss it. Scenario 3 has *no error logs at all* — the agent has to notice that zero rows written in 30 minutes is itself the signal.

**3. Safe, policy-gated LLM code generation.**  
The remediation pipeline (v1.6) lets OpenAI generate Python scripts and CI workflows. Letting an LLM write code that gets pushed to GitHub introduces real risks. The solution is a layered safety model:
- Deterministic keyword classifier (no LLM) decides if a recommendation is eligible before any OpenAI call
- Write paths are scoped to a resolved `service_root` — the model can't write to `backend/` or any path outside `demo-infra/audit-service/`
- `..` traversal segments are rejected before `fnmatch` runs (`fnmatch` doesn't normalise paths)
- A `**`-aware blocklist rejects `**/secrets/**`, `**/k8s/**`, `**/migrations/**` at any nesting depth
- Every generated `.py` file is AST-parsed for syntax errors, checked for hardcoded mock schemas, and verified to read from `sys.argv` rather than inline data
- If validation fails, a single repair OpenAI call is made with the full error list — if it still fails, the draft is marked `failed` and no PR is opened
- Two separate MCP sessions prevent anyio `ExceptionGroup` from swallowing the original exception type when LLM/validation errors escape the subprocess TaskGroup

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

## Key design decisions

### Tool abstraction (`tools/base.py`)
Every infra tool extends `BaseTool` with a single `execute(input, db)` method. The base `run()` method wraps it with Redis caching, timing, DB logging, and graceful Redis degradation — tools implement only the domain logic. This makes it trivial to add a new tool and guaranteed that all tools get consistent observability.

`generate_report` is explicitly *not* in `TOOL_REGISTRY`. It's injected into the OpenAI spec as the finalization mechanism, never cached, never logged as an infra tool call, and forces the agent to call ≥3 real tools first.

### Structured output with typed validation
The agent's final output is validated against a `InvestigationReport` Pydantic model (evidence items, timeline, confidence score, recommended actions). If validation fails, the loop retries the generation step once before marking the run failed. This means the API always returns either a well-typed report or a clear failure — never a raw LLM string.

### Remediation classifier is deterministic
The recommendation classifier uses keyword matching, not an LLM. This keeps the gate fast, auditable, and impossible to prompt-inject past. Blocked keywords (`rollback`, `kubectl`, `migration`, `alter table`) are evaluated before allowed ones (`schema`, `validation`, `compatibility`) — a recommendation containing both is always blocked.

### Two-session MCP architecture
Opening a single long-lived `github_mcp_session()` and running both the LLM call and the MCP writes inside it causes anyio's `stdio_client` TaskGroup to wrap any Python exception in `ExceptionGroup`, losing the original type. The solution: open a read-only MCP session, close it before the LLM call, then open a write-only session only after validation passes. Exceptions during LLM/validation propagate cleanly; the write session only ever sees post-validated data.

### Branch uniqueness
Each draft appends `str(draft_id)[:8]` to the LLM-generated branch name (`infrapilot/audit-service-schema_validation-YYYYMMDD-{short_id}`). Without this, re-running remediation for the same service on the same day would hit a GitHub 422 "PR already exists" error on an already-created branch.

---

## Tech stack

| Layer | Technology | Notes |
|---|---|---|
| API | FastAPI + Uvicorn | Sync SQLAlchemy; no Alembic (create_all on startup) |
| Agent | OpenAI gpt-4o tool-calling | Structured output via JSON mode + Pydantic |
| Database | PostgreSQL + SQLAlchemy | 8 tables: incidents, runs, tool_calls, 5 simulated data tables, remediation_drafts |
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

---

## Demo scenarios

Three incidents are pre-seeded. Each requires a different multi-hop reasoning strategy — the same agent prompt solves all three.

### Scenario 1 — BigQuery auth failure

*Service:* `lat-cron-job` | *Challenge:* The pod is healthy and logs are sparse. The agent must follow deploy → config diff → BQ errors to find that the service account key path changed.

```bash
curl -s -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "BQ writes stopped",
    "description": "lat-cron-job stopped writing to BigQuery after deploy v42",
    "service_name": "lat-cron-job",
    "severity": "high"
  }'
```

**Agent path:** `get_recent_deploys` → `get_config_diff(v42)` → `get_bq_insert_errors` → root cause: secret path changed in v42, BQ client can't authenticate.

### Scenario 2 — Latency spike with red-herring deploy

*Service:* `api-service` | *Challenge:* A deploy exists near the spike — but the agent must notice the 2-hour timeline gap and that the diff is frontend-only, then pivot to the real cause.

```bash
curl -s -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "api-service latency spike",
    "description": "api-service p99 latency spiked to 8s. A deploy went out 2 hours ago.",
    "service_name": "api-service",
    "severity": "high"
  }'
```

**Agent path:** `get_recent_deploys` → `get_config_diff` (frontend only, innocent) → `get_service_logs` → root cause: DB connection pool exhausted; deploy is a red herring.

### Scenario 3 — Silent BigQuery data loss

*Service:* `audit-service` | *Challenge:* No error logs — only silence. The agent must connect deploy → schema file change → BQ SCHEMA_ERRORs to identify a missing table migration.

```bash
curl -s -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "title": "No audit data for 30 mins",
    "description": "audit-service logs show no audit events written to BigQuery in the last 30 minutes",
    "service_name": "audit-service",
    "severity": "high"
  }'
```

**Agent path:** `get_recent_deploys` → `get_config_diff` (schema file changed) → `get_bq_insert_errors` → root cause: code added `user_agent` column, production BQ table never migrated → 0 rows written.

**This scenario unlocks v1.6 remediation** — the agent's recommendation triggers a real GitHub draft PR.

### Poll results

```bash
curl http://localhost:8000/runs/{run_id}           # report_json when completed
curl http://localhost:8000/runs/{run_id}/tool-calls # ordered tool call trace
```

---

## v1.6 — Human-in-the-loop remediation

After Scenario 3 completes, click "Draft PR" in the frontend (or use the API) to generate a real GitHub PR.

### What the generated PR contains

Three files, all validated before the branch is created:

| File | Purpose |
|---|---|
| `demo-infra/audit-service/scripts/validate_bq_schema.py` | Reads both schema files via `sys.argv[1]`/`sys.argv[2]`, compares field names as dicts, exits 1 with a clear diff on mismatch |
| `demo-infra/audit-service/tests/test_validate_bq_schema.py` | Runnable pytest tests using a factory fixture and `pathlib.Path(__file__)` for portable paths |
| `.github/workflows/audit-schema-validation.yml` | CI workflow (`checkout@v4`, `setup-python@v5`, Python 3.12) triggered on changes to the service directory |

**InfraPilot never merges automatically.** Draft PR only.

### Safety model

The pipeline enforces multiple independent layers:

```
Request arrives
  ↓
Classifier (deterministic keywords)
  rollback / kubectl / migration / alter table → 422 blocked
  schema / validation / compatibility / pre-deploy → proceed
  ↓
Policy write-path guard (before any MCP write)
  reject if path contains '..' segments
  reject if path matches blocklist: .env*, **/secrets/**, **/k8s/**, **/terraform/**, **/migrations/**
  reject if path not in allowlist: {service_root}/scripts/*.py, {service_root}/tests/*.py,
                                   .github/workflows/*validation*.yml
  ↓
Content safety check (on every generated file)
  reject if content contains: bq update, bq mk, kubectl apply/delete, alter table,
                              drop table, gcloud secrets, secret create/patch
  ↓
Code quality gate (Python files only)
  ast.parse() — syntax check
  no hardcoded schema patterns (production_schema =, Mocked production schema)
  reads from files (sys.argv or open()) — not inline data
  dict field access when iterating schema fields
  ↓
  if any check fails → one repair OpenAI call with full error list
  if repair still fails → draft=failed, no PR opened
  ↓
MCP write session (only if all checks pass)
  create_branch → write files → create draft PR
```

### Setup

**Create a fine-grained PAT** (GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens):
- Repository access: **Only select repositories** → `infrapilot-ai`
- Permissions: **Contents** (read/write), **Pull requests** (read/write) — nothing else

```bash
# .env
GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
GITHUB_TARGET_REPO=kavithadee/infrapilot-ai
GITHUB_BASE_BRANCH=main
```

```bash
# After Scenario 3 completes:
curl -s -X POST http://localhost:8000/runs/{run_id}/remediation-drafts \
  -H "Content-Type: application/json" \
  -d '{"selected_recommendation": "Add a pre-deploy schema compatibility validation check"}'

# Poll until pr_created
curl http://localhost:8000/remediation-drafts/{draft_id}
# → { "status": "pr_created", "github_pr_url": "https://github.com/..." }
```

| HTTP code | Meaning |
|---|---|
| `201` | Draft created; poll for `pr_created` |
| `400` | Run not yet completed |
| `422` | Recommendation blocked or service not eligible |
| `503` | `GITHUB_PERSONAL_ACCESS_TOKEN` not set |

> **Production path:** Replace the fine-grained PAT with a GitHub App installation token for per-installation audit logs, automatic token rotation, and org-level scoping without personal account association.

---

## Running tests

```bash
docker compose exec api pytest                                         # 66 tests
docker compose exec api pytest tests/unit/test_remediation.py -v      # 26 remediation unit tests
docker compose exec api pytest tests/integration/                      # full API flow (mocked OpenAI)
```

The test suite mocks OpenAI and GitHub MCP at the network boundary — no real API calls needed to run tests. The remediation tests verify the full pipeline including the classifier, policy gate, code quality validator, repair loop, and async agent entry point.

---

## Codebase map

```
backend/
  app/
    agents/
      investigator.py          # OpenAI tool-calling loop; manages message history
      report_builder.py        # Parses + validates InvestigationReport; retries once
      fix_spec_agent.py        # 4-stage remediation pipeline
      generated_code_validator.py  # AST + pattern checks on generated Python
    guardrails/
      remediation_classifier.py  # Deterministic keyword classifier
      remediation_policy.py      # Write-path guard + content safety rules
      service_registry.py        # SERVICE_REPO_MAP; service → repo + service_root
    services/
      github_mcp.py              # MCP session; read/write/PR helpers; path guards
      repo_context_resolver.py   # Discovers schema/script/test paths via MCP
    tools/
      base.py                    # BaseTool ABC: cache + log wrapper around execute()
      registry.py                # TOOL_REGISTRY + build_openai_tools_spec()
      get_recent_deploys.py      # ...each tool implements only execute()
      get_service_logs.py
      get_k8s_pod_status.py
      get_bq_insert_errors.py
      get_config_diff.py
    api/
      incidents.py               # POST /incidents, GET /incidents
      runs.py                    # GET /runs/{id}, GET /runs/{id}/tool-calls
      remediation.py             # POST + 2× GET remediation drafts
    db/
      models.py                  # 8 ORM models (+ RemediationDraft)
      repositories.py            # All DB reads/writes; no SQL outside this file
    schemas/
      report.py                  # InvestigationReport Pydantic model
      remediation.py             # FixSpec, FixFile, RemediationDraftDetail

frontend/src/
  routes/runs.$runId.tsx         # Run detail page with polling + remediation section
  components/infrapilot/
    RemediationDraftCard.tsx     # Draft PR lifecycle component (idle → drafting → result)
    ActionsList.tsx
    ToolCallTimeline.tsx
  lib/
    infrapilot-api.ts            # API client + types
    remediation-api.ts           # Remediation API client + types
```

---

## Intentional simulation

The infra data is seeded into Postgres tables rather than calling real cloud APIs. This keeps the demo self-contained and reproducible. The agent's tool interfaces are designed so each tool could be replaced with a real implementation (Loki MCP, GCP APIs, `kubectl`) without changing the agent loop.

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
