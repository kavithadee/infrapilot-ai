# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules for Claude Code

1. Execute **one task at a time**. Stop after each task and wait for the user to say "go" before starting the next one.
2. After completing a task, mark it `- [x]` in this file in the same edit as the code change.
3. **Always verify a change works locally before committing it.** Run the relevant service (`docker compose up --build`, curl, tests) and confirm the expected behavior before staging any commit.

## Project Overview

InfraPilot AI is an agentic on-call debugging copilot. It accepts an incident description, runs an OpenAI tool-calling agent loop that queries simulated infrastructure data (deploys, logs, K8s status, BigQuery errors, config diffs), and returns a structured JSON investigation report with root cause, evidence, timeline, and recommended actions.

## Commands

### Start / Stop
```bash
docker compose up --build        # First run (builds image, starts api + postgres + redis)
docker compose up                # Subsequent runs
docker compose down              # Stop all services
docker compose logs -f api       # Tail API logs
```

### Seed Data
```bash
# Auto-runs on startup via main.py. To run manually:
docker compose exec api python -m app.seed.seed_data
```

### Run Tests
```bash
docker compose exec api pytest                          # All tests
docker compose exec api pytest tests/unit/              # Unit tests only
docker compose exec api pytest tests/integration/       # Integration tests only
docker compose exec api pytest tests/unit/test_tools.py::test_get_recent_deploys_returns_v42  # Single test
```

### Test a Tool Directly (dev endpoint)
```bash
curl -X POST http://localhost:8000/tools/get_recent_deploys/test \
  -H "Content-Type: application/json" \
  -d '{"service_name": "lat-cron-job"}'
```

### Demo Scenarios
```bash
# Scenario 1: BigQuery auth failure (lat-cron-job)
curl -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{"title":"BQ writes stopped","description":"lat-cron-job stopped writing to BigQuery after deploy v42","service_name":"lat-cron-job","severity":"high"}'

# Scenario 2: Latency spike — red herring deploy (api-service)
curl -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{"title":"api-service latency spike","description":"api-service p99 latency spiked to 8s as of 10 minutes ago. A deploy went out 2 hours ago.","service_name":"api-service","severity":"high"}'

# Scenario 3: Silent data loss — BQ schema mismatch (audit-service)
curl -X POST http://localhost:8000/incidents \
  -H "Content-Type: application/json" \
  -d '{"title":"No audit data for 30 mins","description":"audit-service logs show no audit events written to BigQuery in the last 30 minutes","service_name":"audit-service","severity":"high"}'

# Poll for results
curl http://localhost:8000/runs/{run_id}
curl http://localhost:8000/runs/{run_id}/tool-calls
```

## Architecture

### Request Flow
```
POST /incidents
  → insert incidents row (status=open)
  → insert investigation_runs row (status=pending)
  → FastAPI BackgroundTask: run_investigation(run_id)
      → agent loop (investigator.py): OpenAI tool-calling, max 8 iterations
          → each tool call → BaseTool.run(): Redis cache → execute() → cache set → log to DB
          → final call to generate_report tool → validate as InvestigationReport (Pydantic)
      → update run: status=completed, report_json=...
```

### Key Design Decisions

**Tool Abstraction (`tools/base.py`):** Every infra tool extends `BaseTool` ABC with `name`, `description`, `input_schema`, `output_schema`, `cache_ttl`, and an `execute(input, db)` method. The base `run()` method handles Redis caching, timing, and DB logging — tools only implement `execute()`. Redis failures degrade gracefully (log warning, skip cache).

**generate_report is NOT in TOOL_REGISTRY:** It is a 6th tool added to the OpenAI spec only as the finalization mechanism. It is never cached, never logged as an infra tool call, and never appears in `GET /runs/{run_id}/tool-calls`. The agent must call ≥3 real infra tools before calling it.

**Sync SQLAlchemy:** V1 uses synchronous SQLAlchemy (`SessionLocal`). The `db` session is passed into every tool's `execute()` call and every repository function — never imported as a global.

**No Alembic:** Schema is created via `Base.metadata.create_all(engine)` on startup in `main.py`. Alembic is explicitly deferred to production.

**Simulated data:** All infra data is seeded into Postgres simulation tables (`simulated_deploys`, `simulated_logs`, `simulated_k8s_status`, `simulated_bq_errors`, `simulated_config_diffs`). Tools query these tables — there are no real cloud API calls.

**3 seed scenarios, each requiring a different reasoning strategy:**
| Scenario | Service | Failure mode | Agent strategy |
|---|---|---|---|
| 1 — BQ Auth | `lat-cron-job` | Secret path changed → BQ AUTH_ERROR, pod healthy | Correlate deploy → config diff → BQ errors |
| 2 — Red Herring | `api-service` | Latency spike; deploy 2h ago is innocent; real cause is DB connection pool exhaustion | Rule out deploy (timeline mismatch + frontend-only diff), pivot to logs |
| 3 — Schema Mismatch | `audit-service` | Code added BQ column, production table not migrated → silent SCHEMA_ERROR, 0 rows written | Correlate deploy → schema file changed → BQ SCHEMA_ERROR → missing data |

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/core/db.py` | Engine, `SessionLocal`, `get_db()` dependency, `create_all()` |
| `app/core/redis_client.py` | `get_redis()`, `redis_get/set/delete` with graceful degradation |
| `app/core/logging.py` | Structured JSON logger (used everywhere via `logger = get_logger(__name__)`) |
| `app/db/models.py` | All 8 SQLAlchemy ORM models |
| `app/db/repositories.py` | All DB reads/writes — no SQL outside this file |
| `app/tools/base.py` | `BaseTool` ABC — cache + log wrapper around `execute()` |
| `app/tools/registry.py` | `TOOL_REGISTRY` dict + `build_openai_tools_spec()` → OpenAI function-calling format |
| `app/agents/investigator.py` | OpenAI chat loop; appends tool results to message history; calls tools via `TOOL_REGISTRY` |
| `app/agents/report_builder.py` | Parses `generate_report` args, validates as `InvestigationReport`, retries once |
| `app/seed/seed_data.py` | Idempotent seeder — checks for existing rows before inserting |

### Cache Key Conventions
```
deploys:{service_name}
logs:{service_name}:{time_window}:{md5(query)}
k8s:pod:{service_name}
bq:errors:{table_name}:{time_window}
config:{service_name}:{deploy_id}
```

### Environment Variables
Defined in `app/config.py` via pydantic-settings. Loaded from `.env` (copy from `.env.example`):
- `DATABASE_URL` — postgres connection string
- `REDIS_URL` — redis connection string  
- `OPENAI_API_KEY` — required for agent runs
- `AGENT_MODEL` — defaults to `gpt-4o`
- `ENVIRONMENT` — `development` | `production`

---

## Implementation Plan & Todo

### Day 1 — Foundation + Data + Tools

#### Project Setup
- [x] Create repo directory + `.gitignore`
- [x] `requirements.txt` (fastapi, sqlalchemy, psycopg2, redis, openai, pydantic-settings, pytest, httpx, uvicorn)
- [x] `docker-compose.yml` (api, postgres, redis with healthchecks)
- [x] `backend/Dockerfile`
- [x] `.env.example` + local `.env`

#### Config + Core
- [x] `app/config.py` — pydantic-settings (DATABASE_URL, REDIS_URL, OPENAI_API_KEY, AGENT_MODEL, ENVIRONMENT)
- [x] `app/core/db.py` — sync engine, SessionLocal, `create_all()` on startup
- [x] `app/core/redis_client.py` — connection, get/set/delete helpers with graceful degradation
- [x] `app/core/logging.py` — structured JSON logger

#### Database Models
- [x] `app/db/models.py` — all 8 tables: incidents, investigation_runs, tool_calls, simulated_deploys, simulated_logs, simulated_k8s_status, simulated_bq_errors, simulated_config_diffs
- [x] `app/db/repositories.py` — CRUD helpers: create_incident, create_run, log_tool_call, get_run, get_tool_calls_for_run

#### Seed Data
- [x] `app/seed/scenarios/scenario_bq_auth.py` — lat-cron-job: deploy v42, JWT error logs, BQ AUTH_ERROR ×47, healthy pod, config diff shows secret path changed
- [x] `app/seed/scenarios/scenario_red_herring.py` — api-service: latency spike, deploy v23 innocent (frontend only + misleading slow query log), DB connection pool exhaustion is root cause
- [x] `app/seed/scenarios/scenario_bq_schema.py` — audit-service: deploy added BQ column in code, production table not migrated, silent SCHEMA_ERROR, 0 rows written
- [x] `app/seed/seed_data.py` — idempotent seeder, called on startup

#### Tool Abstractions
- [x] `app/tools/base.py` — BaseTool ABC with `run()`: Redis cache check → execute → cache set → log to DB (graceful Redis degradation)
- [x] `app/tools/registry.py` — TOOL_REGISTRY dict + `build_openai_tools_spec()`
- [x] `app/schemas/tool_schemas.py` — input/output Pydantic models for all 5 tools
- [x] `app/tools/get_recent_deploys.py`
- [x] `app/tools/get_service_logs.py`
- [x] `app/tools/get_k8s_pod_status.py`
- [x] `app/tools/get_bq_insert_errors.py`
- [x] `app/tools/get_config_diff.py`

#### Dev Endpoints + App Wiring
- [x] `app/api/health.py` — GET /health
- [x] `app/api/tools.py` — POST /tools/{tool_name}/test
- [x] `app/main.py` — wire app, startup hooks (create_all, seed)

**Day 1 Checkpoint:** `curl -X POST /tools/get_recent_deploys/test -d '{"service_name":"lat-cron-job"}'` returns seeded deploy data ✓

---

### Day 2 — Agent + API + End-to-End

#### Report + Incident Schemas
- [x] `app/schemas/report.py` — TimelineItem, EvidenceItem, RecommendedAction, InvestigationReport Pydantic models
- [x] `app/schemas/incident.py` — CreateIncidentRequest, CreateIncidentResponse, IncidentDetail

#### Agent
- [x] `app/agents/investigator.py` — OpenAI tool-calling loop (max 8 iterations, must call ≥3 infra tools before generate_report)
- [x] `app/agents/report_builder.py` — parse + Pydantic validate final JSON, retry once on failure
- [x] Wire `generate_report` as finalization tool in OpenAI spec (not in TOOL_REGISTRY, not logged as infra call)

#### API Endpoints
- [x] `app/api/incidents.py` — POST /incidents (create rows + BackgroundTask), GET /incidents
- [x] `app/api/runs.py` — GET /runs/{run_id}, GET /runs/{run_id}/tool-calls

#### Middleware + Timeouts
- [x] `app/core/middleware.py` — FastAPI request logging middleware (method, path, status code, latency ms)
- [x] Wire middleware in `app/main.py`
- [x] Add OpenAI `timeout=30` in agent loop — prevents hanging on slow/failed API calls

#### Telemetry Stubs
- [x] `app/telemetry/otel.py` — TODO stubs with comments for future OTel spans

#### Manual End-to-End
- [x] Submit Scenario 1, watch logs, confirm tool calls in Postgres, verify report JSON
- [x] Confirm Redis cache hit on second identical tool call
- [x] Confirm GET /runs/{run_id} returns completed report with evidence + timeline + confidence score

**Day 2 Checkpoint:** Scenario 1 (BigQuery auth) produces a full report with ≥3 infra tool calls, stored in Postgres ✓

---

### Day 3 — Scenario 2 + Tests + README + Polish

#### Scenario Verification
- [x] Submit Scenario 2 (api-service latency spike), verify agent rules out deploy, identifies DB connection pool exhaustion
- [x] Submit Scenario 3 (audit-service silent data loss), verify agent calls BQ errors + config diff, identifies schema migration gap

#### Tests
- [x] `tests/unit/test_tools.py` — one test per tool against seeded DB
- [x] `tests/unit/test_cache.py` — assert second call returns cache_hit=true in DB
- [x] `tests/unit/test_report_schema.py` — valid report passes, missing field raises ValidationError
- [x] `tests/integration/test_api.py` — POST /incidents → completed run → ≥3 infra tool calls persisted (mocked OpenAI)
- [x] `tests/conftest.py` — test DB setup, test Redis, seeded fixtures

#### README
- [ ] Project goal + context
- [ ] Mermaid architecture diagram (User → API → Agent → Tools → Postgres/Redis)
- [ ] Tech stack table
- [ ] Setup steps (docker compose up, seed, curl)
- [ ] Three demo curl commands (all 3 scenarios)
- [ ] Example output (paste real report JSON)
- [ ] "What is intentionally simulated" section
- [ ] "What would be added in production" section (Alembic, RQ, OTel, real cloud, frontend, auth)
- [ ] MCP-style tools note
- [ ] Planned frontend screens section

#### Stretch (if time allows)
- [ ] `app/demo/run_scenario.py` — `python -m app.demo.run_scenario bq_auth` CLI script
- [ ] Static HTML report page at GET /runs/{run_id}/report
- [ ] RQ worker + worker service in Docker Compose (replace BackgroundTasks)

**Day 3 Checkpoint:** All 10 acceptance criteria met ✓

---

### Acceptance Criteria (MVP complete when all pass)
- [ ] `docker compose up --build` starts all 3 services without errors
- [ ] Seed data loads (3 scenarios visible in Postgres)
- [ ] POST /incidents → `{ run_id, status: "pending" }`
- [ ] GET /runs/{run_id} → eventually `status: "completed"` with full report
- [ ] Report includes: evidence, timeline, likely_root_cause, confidence_score, recommended_actions
- [ ] GET /runs/{run_id}/tool-calls shows ≥3 tool calls in sequence
- [ ] Re-submitting same incident shows ≥1 `cache_hit: true` in tool_calls
- [ ] All unit tests pass (mocked LLM)
- [ ] Integration test passes (mocked LLM)
- [ ] README complete with setup, Mermaid diagram, 3 demo prompts, example report output

---


## v1.6 — GitHub MCP Human-in-the-Loop Remediation

### Goal

Close the loop from diagnosis to a real draft PR on GitHub:
```
click "Draft PR" → backend validates → GitHub MCP reads schemas → OpenAI generates fix
→ GitHub MCP creates branch + files + draft PR → frontend opens PR → human reviews/merges
```
Scoped to: `audit-service` BigQuery schema mismatch (Scenario 3) only.

### Architecture (v5.1 — Policy-Driven, Simplified)

```
POST /runs/{run_id}/remediation-drafts
  │
  ├─ 1. RemediationClassifier (deterministic, no LLM)
  │      keyword rules on selected_recommendation:
  │        schema/validation/compatibility/pre-deploy → "schema_validation"
  │        rollback/secret/kubectl/migration/ALTER TABLE → blocked (422)
  │        anything else → unsupported (422)
  │      v1 gate: only audit-service + schema_validation proceeds
  │
  ├─ 2. RepoContextResolver (GitHub MCP)
  │      lookup SERVICE_REPO_MAP[service_name] → { repo, service_root }
  │      MCP inspect (constrained — no arbitrary recursion):
  │        {service_root}/, schemas/, scripts/, tests/, .github/workflows/
  │      output: RepoContext { read_paths, candidate_write_dirs,
  │                            existing_ci_workflows, service_context_summary }
  │
  ├─ 3. FixSpecAgent (single OpenAI structured-output call)
  │      MCP reads plan.files_to_read (prefix guard: service_root or .github/)
  │      LLM returns FixSpec: branch_name, pr_title, pr_body, files[],
  │                           change_summary, test_plan, risk_notes
  │      Policy gate: every files[].path checked against RemediationPolicy
  │                   every files[].content checked for unsafe keywords
  │
  ├─ 4. MCP Execution (Python-controlled, not LLM-controlled)
  │      create_branch
  │      create_or_update_file × N (policy check before each write)
  │      create_pull_request (draft=True)
  │
  └─ 5. Persist + return 201 { github_pr_url }

GET /remediation-drafts/{draft_id}     → stored draft
GET /runs/{run_id}/remediation-drafts  → list drafts for run
```

### Safety Constraints

- **Pattern-based write paths** scoped to resolved `service_root`:
  - `{service_root}/scripts/*.py`, `{service_root}/tests/*.py`
  - `.github/workflows/*validation*.yml` / `.yaml`
- **Blocked paths:** `.env*`, `**/secrets/**`, `**/credentials/**`, `**/k8s/**`, `**/terraform/**`, `**/migrations/**`, `**/alembic/**`
- **Content safety keywords:** `bq update`, `bq mk`, `kubectl apply/delete`, `alter table`, `drop table`, `secret create/patch`, `gcloud secrets`
- **Explicit runtime path guards** (not asserts) before every MCP write call
- **Human gate:** backend creates draft PR only — never merges, never deploys, never writes to main

### New Files

| Path | Purpose |
|---|---|
| `backend/app/guardrails/service_registry.py` | `SERVICE_REPO_MAP` dict; `get_service_config(service_name)` |
| `backend/app/guardrails/remediation_policy.py` | `RemediationPolicy(service_root)` — safety rules only; `check_write_path()`, `check_file_content()` |
| `backend/app/guardrails/remediation_classifier.py` | Deterministic `classify_remediation_type(recommendation) → str`; `UnsupportedRemediationType` |
| `backend/app/services/repo_context_resolver.py` | `resolve_repo_context(mcp, service_name, owner, repo) → RepoContext`; constrained to 5 dirs |
| `backend/app/api/remediation.py` | 3 endpoints: POST + 2× GET |
| `backend/tests/unit/test_remediation.py` | Unit tests (mocked MCP + mocked OpenAI) |
| `frontend/src/lib/remediation-api.ts` | API client + TypeScript types |
| `frontend/src/components/infrapilot/RemediationDraftCard.tsx` | PR URL, branch, files, "Human review required" banner |

### Modified Files

| Path | Change |
|---|---|
| `backend/app/services/github_mcp.py` | Remove exact frozensets; add `list_directory()`; prefix-based read guard; policy-delegating write guard |
| `backend/app/schemas/remediation.py` | Add `RepoContext`; update `FixSpec` (add `change_summary`); `FixFile` validator uses `RemediationPolicy` |
| `backend/app/agents/fix_spec_agent.py` | Full rewrite: 4-stage pipeline (classify → resolve → LLM → MCP) |
| `backend/app/db/models.py` | `RemediationDraft` ORM model — already updated ✓ |
| `backend/app/db/repositories.py` | 4 remediation functions — already added ✓ |
| `backend/app/config.py` | GitHub settings — already added ✓ |
| `backend/app/main.py` | Register remediation router |
| `backend/requirements.txt` | `mcp` — already added ✓ |
| `backend/Dockerfile` | `github-mcp-server` binary — already added ✓ |
| `frontend/src/routes/runs.$runId.tsx` | Add remediation section after ActionsList |
| `README.md` | GitHub PAT setup, scopes, production GitHub App note |

### Environment Variables (Railway + local `.env`)

| Variable | Purpose |
|---|---|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Fine-grained PAT: Contents + Pull requests (read/write) on target repo only |
| `GITHUB_TARGET_REPO` | Default: `kavithadee/infrapilot-ai` |
| `GITHUB_BASE_BRANCH` | Default: `main` |

### Todo

#### Already done
- [x] **Task 1** — Create `demo-infra/audit-service/` fixture files at repo root
- [x] **Task 2** — Add `RemediationDraft` ORM model to `backend/app/db/models.py`
- [x] **Task 3** — Revise `RemediationDraft` model: add `branch_name`, `error_message`; status `"drafting|pr_created|failed"`; delete `backend/app/data/demo_infra/`
- [x] **Task 4** — Add `mcp` to `requirements.txt`; update `Dockerfile` to install `github-mcp-server` (pinned, verified)
- [x] **Task 5** — Add `github_token`, `github_target_repo`, `github_base_branch` to `app/config.py`
- [x] **Task 8** — Add 4 remediation repository functions to `repositories.py`

#### Needs revision (written with old hardcoded approach)
- [x] **Task 6r** — Revise `backend/app/services/github_mcp.py`: remove exact frozensets; add `list_directory()`; prefix-based read guard; policy-delegating write guard
- [x] **Task 7r** — Revise `backend/app/schemas/remediation.py`: add `RepoContext`; update `FixSpec` (add `change_summary`); `FixFile` validator uses `RemediationPolicy`; remove `ALLOWED_WRITE_PATHS` import

#### New files
- [x] **Task 6n** — Create `backend/app/guardrails/service_registry.py` + `backend/app/guardrails/remediation_policy.py`
- [x] **Task 7n** — Create `backend/app/guardrails/remediation_classifier.py`
- [x] **Task 8n** — Create `backend/app/services/repo_context_resolver.py`
- [x] **Task 9r** — Rewrite `backend/app/agents/fix_spec_agent.py` (4-stage pipeline)

#### Continue
- [x] **Task 10** — Create `backend/app/api/remediation.py` + register router in `main.py`
- [x] **Task 11** — Write `backend/tests/unit/test_remediation.py` (unit tests, mocked pipeline stages)

#### Backend verification gate (blocks all frontend work)
- [x] **Task 12** — All 4 checks must pass:
  1. `docker compose up --build` succeeds; `github-mcp-server --version` in build log ✓
  2. `pytest tests/unit/test_remediation.py` → 20/20 pass ✓
  3. `curl POST /runs/{run_id}/remediation-drafts` with audit-service completed run → 201 ✓
  4. Real draft PR at https://github.com/kavithadee/infrapilot-ai/pull/6, branch `infrapilot/audit-service-schema_validation-20260610`, 3 generated files ✓

#### Frontend (start only after Task 12 passes)
- [ ] **Task 13** — Create `frontend/src/lib/remediation-api.ts`
- [ ] **Task 14** — Create `frontend/src/components/infrapilot/RemediationDraftCard.tsx`
- [ ] **Task 15** — Integrate remediation section into `frontend/src/routes/runs.$runId.tsx`

#### Finishing
- [ ] **Task 16** — Verify `.gitignore` covers `GITHUB_PERSONAL_ACCESS_TOKEN`; run full test suite
- [ ] **Task 17** — Update `README.md`
- [ ] **Task 18** — Commit and deploy to Railway

### v1.6 Acceptance Criteria
- [ ] `POST /runs/{run_id}/remediation-drafts` → 201 with `github_pr_url` for completed audit-service run
- [ ] Returns 400 for incomplete run, 422 for wrong service or unsafe recommendation, 503 if token not set
- [ ] All unit tests pass (mocked MCP + mocked LLM)
- [ ] Write paths scoped to resolved service_root; unsafe content keywords rejected
- [ ] Frontend shows "Draft PR" button on eligible runs only; opens real PR in new tab
- [ ] `RemediationDraftCard` shows PR URL, branch, files changed, "Human review required" banner
- [ ] README documents GitHub PAT setup end-to-end
