# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

> **Rules for Claude Code:**
> 1. Execute **one task at a time**. Stop after each task and wait for the user to say "go" before starting the next one.
> 2. After completing a task, mark it `- [x]` in this file in the same edit as the code change.

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

## v1.5 — Optional Grafana/Loki/MCP Observability Extension

> **Do not start v1.5 until all MVP acceptance criteria above are met.**
>
> Core MVP must work with only FastAPI + Postgres + Redis. Nothing in v1.5 is required
> for the app to function. All Loki/Grafana services are opt-in via Docker Compose profiles.

### Goal

Simulate a real on-call workflow by pushing the same seeded logs into Loki and showing
how Claude Code can query them via the Grafana MCP server — demonstrating that
InfraPilot's `get_service_logs` tool could be replaced or augmented with real log
infrastructure in production.

### Architecture Addition
```
docker compose --profile observability up
  → adds: Loki (port 3100) + Grafana (port 3000)
  → seed_loki.py pushes simulated_logs rows → Loki via HTTP push API
  → Grafana auto-provisioned with Loki datasource
  → Claude Code configured with Grafana MCP → queries Loki via LogQL
```

### Todo

#### Docker + Infrastructure
- [ ] `docker-compose.yml` — add `loki` (grafana/loki:2.9.0) and `grafana` (grafana/grafana:10.2.0) services under `profiles: ["observability"]`
- [ ] `docker/grafana/provisioning/datasources/loki.yaml` — auto-provision Loki as default datasource pointing to `http://loki:3100`

#### Loki Seeder
- [ ] `app/seed/seed_loki.py` — read all `simulated_logs` rows from Postgres, batch by `(service_name, severity)`, push to Loki HTTP push API (`POST http://loki:3100/loki/api/v1/push`); idempotent (Loki deduplicates by stream + timestamp)

#### README
- [ ] "Optional MCP Observability Extension" section covering:
  1. Start observability stack: `docker compose --profile observability up`
  2. Seed logs into Loki: `docker compose --profile observability exec api python -m app.seed.seed_loki`
  3. Configure Grafana MCP in `.claude/settings.json` (see snippet below)
  4. Demo workflow: ask Claude Code to query Loki for lat-cron-job ERROR logs via LogQL
  5. Comparison note: same logs accessible via InfraPilot's `get_service_logs` (Postgres) vs Grafana MCP (Loki)
  6. Production path: `get_service_logs` could be replaced with a Grafana/Loki MCP-backed tool

#### Grafana MCP Config (document in README)
```json
// .claude/settings.json — mcpServers block
{
  "mcpServers": {
    "grafana": {
      "command": "npx",
      "args": ["-y", "@grafana/mcp-grafana"],
      "env": {
        "GRAFANA_URL": "http://localhost:3000",
        "GRAFANA_API_KEY": ""
      }
    }
  }
}
```
> Anonymous auth is enabled in the Grafana container so no API key is needed locally.

### v1.5 Acceptance Criteria
- [ ] `docker compose --profile observability up` starts all 5 services cleanly
- [ ] `curl http://localhost:3100/ready` → `ready`
- [ ] `curl http://localhost:3000` → Grafana UI loads with Loki datasource pre-configured
- [ ] `seed_loki.py` runs without errors; Grafana Explore query `{service="lat-cron-job"}` returns JWT error logs
- [ ] Grafana MCP configured in `.claude/settings.json`; Claude Code can call `loki_query` MCP tool and return lat-cron-job ERROR logs matching what `get_service_logs` returns from Postgres
