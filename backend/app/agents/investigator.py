"""
investigator.py — OpenAI tool-calling agent loop.

Entry point: run_investigation(run_id) — called as a FastAPI BackgroundTask.

Loop constraints:
  - Max 8 iterations before giving up
  - Agent must call ≥3 infra tools before generate_report is accepted
  - generate_report is NOT in TOOL_REGISTRY; added to the OpenAI spec here only
  - generate_report calls are never cached or logged as infra tool calls
  - Report validation failure allows one retry (error sent back as tool result)
  - OpenAI requests use timeout=30s
"""

import json
from uuid import UUID

from openai import OpenAI

from app.agents.report_builder import (
    ReportValidationError,
    build_report,
    format_validation_error_for_llm,
)
from app.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.db import repositories as repo
from app.schemas.report import InvestigationReport
from app.tools.registry import TOOL_REGISTRY, build_openai_tools_spec

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 8
MIN_INFRA_TOOLS = 3

# ---------------------------------------------------------------------------
# generate_report tool spec (finalization-only — never in TOOL_REGISTRY)
# ---------------------------------------------------------------------------

def _inline_refs(schema: dict) -> dict:
    """
    Recursively resolve all $ref / $defs in a JSON Schema dict so that
    OpenAI sees a flat schema without any references.

    Pydantic v2's model_json_schema() produces $defs for nested models.
    OpenAI's function-calling API does NOT resolve $ref, so the LLM
    receives an empty schema for nested objects and omits those fields.
    This resolver inlines every $ref in-place before the spec is sent.
    """
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]
            return resolve(dict(defs.get(ref_name, {})))
        result = {}
        for key, value in node.items():
            if key == "$defs":
                continue  # drop the definitions block from output
            if isinstance(value, dict):
                result[key] = resolve(value)
            elif isinstance(value, list):
                result[key] = [resolve(item) if isinstance(item, dict) else item for item in value]
            else:
                result[key] = value
        return result

    return resolve(schema)


_GENERATE_REPORT_SPEC: dict = {
    "type": "function",
    "function": {
        "name": "generate_report",
        "description": (
            "Produce the final structured investigation report. "
            "Call this only after you have gathered sufficient evidence from at least "
            f"{MIN_INFRA_TOOLS} infra tools. "
            "The report must include a root cause, supporting evidence from each tool you called, "
            "a chronological timeline, and concrete recommended actions."
        ),
        "parameters": _inline_refs(InvestigationReport.model_json_schema()),
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""You are InfraPilot, an expert on-call debugging assistant. \
Your job is to investigate infrastructure incidents by systematically querying \
available tools and producing a structured root cause analysis report.

## Investigation Strategy

Work through these steps in order, adjusting based on what you find:

1. **get_recent_deploys** — Always start here. Check whether a deployment coincides \
with the incident timeline. A deploy within 2 hours of the first error is a strong signal.

2. **get_service_logs** — Fetch logs for the affected service. Filter by ERROR or CRITICAL \
severity to focus on actionable signals. Look for repeating error patterns, exception messages, \
or sudden gaps in log volume.

3. **get_k8s_pod_status** — Check pod health and restart counts. \
CrashLoopBackOff with 3+ restarts strongly indicates a startup failure. \
A healthy Running pod with 0 restarts means the failure is logic/data, not crash.

4. **get_bq_insert_errors** — Use this when the incident involves BigQuery, data pipelines, \
or missing/delayed data. You MUST provide `table_name` — look for it in service logs \
(e.g. "BigQuery insert failed for table analytics.daily_metrics") or deploy config changes. \
Never call this tool without a specific table name. \
AUTH_ERROR indicates a credentials problem; \
SCHEMA_ERROR indicates a code/schema mismatch (e.g., a new column was added in code \
but the table was not migrated).

5. **get_config_diff** — Use this after finding a suspicious deploy. \
Pass the service name and deploy version. Look for changed secret paths, \
renamed environment variables, or modified schema files.

## Rules

- You MUST call at least {MIN_INFRA_TOOLS} different infra tools before calling \
generate_report. Calling the same tool twice counts as one unique tool.
- Do not guess. Form hypotheses from tool results, then test them with further queries.
- Correlate timestamps: a deploy at T-2h followed by errors starting at T is suspicious.
- Not every deploy is guilty — rule out innocent changes (e.g., frontend-only CSS changes, \
documentation updates) before assigning blame.
- If a deploy changes a config path, secret reference, or schema file, \
always follow up with get_config_diff and the relevant error tool.
- When multiple root causes are possible, state the most likely one and note the alternatives.
- Set confidence_score honestly: 0.9+ means you have corroborating evidence from 3+ tools; \
0.5–0.7 means you have a strong hypothesis but incomplete proof.

Call generate_report when you have enough evidence to state a likely root cause confidently.
"""

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_investigation(run_id: UUID, time_window: str = "2h") -> None:
    """
    Run the full investigation for a given run_id.

    Opens its own DB session (called from a BackgroundTask, outside request context).
    Updates the run to status=running on start, completed/failed on finish.

    Args:
        run_id:      The InvestigationRun to execute.
        time_window: How far back to query logs/errors (e.g. "2h"). Passed from
                     CreateIncidentRequest so the same value is used for every tool
                     call in this run — making Redis cache keys deterministic across
                     re-investigations of the same incident.
    """
    db = SessionLocal()
    try:
        _investigate(run_id, db, time_window)
    except Exception as e:
        logger.error("investigation_fatal", run_id=str(run_id), error=str(e))
        try:
            repo.update_run_failed(db, run_id, error_message=str(e))
        except Exception:
            pass  # DB might also be unavailable; nothing else we can do
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


def _investigate(run_id: UUID, db, time_window: str = "2h") -> None:
    run = repo.get_run(db, run_id)
    if run is None:
        logger.error("run_not_found", run_id=str(run_id))
        return

    incident = repo.get_incident(db, run.incident_id)
    if incident is None:
        logger.error("incident_not_found", run_id=str(run_id), incident_id=str(run.incident_id))
        return

    repo.update_run_started(db, run_id)
    logger.info(
        "investigation_started",
        run_id=str(run_id),
        incident=incident.title,
        service=incident.service_name,
    )
    print(f"\n[InfraPilot] ═══════════════════════════════════════════════", flush=True)
    print(f"[InfraPilot] Investigation started", flush=True)
    print(f"[InfraPilot]   run_id:  {run_id}", flush=True)
    print(f"[InfraPilot]   service: {incident.service_name}", flush=True)
    print(f"[InfraPilot]   title:   {incident.title}", flush=True)
    print(f"[InfraPilot]   window:  {time_window}", flush=True)
    print(f"[InfraPilot] ═══════════════════════════════════════════════", flush=True)

    client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Investigate this incident:\n\n"
                f"**Title:** {incident.title}\n"
                f"**Service:** {incident.service_name}\n"
                f"**Severity:** {incident.severity}\n"
                f"**time_window:** {time_window} — use this exact value for ALL log and error tool calls in this investigation.\n\n"
                f"**Description:**\n{incident.description}"
            ),
        },
    ]

    # Track state across iterations
    infra_tools_called: list[str] = []   # names of infra tools used (for MIN_INFRA_TOOLS gate)
    sequence_num: int = 0                 # monotonic counter for tool_calls table
    report_retry_count: int = 0           # generate_report retries allowed: max 1
    investigation_complete: bool = False

    all_tools_spec = build_openai_tools_spec() + [_GENERATE_REPORT_SPEC]

    for iteration in range(MAX_ITERATIONS):
        logger.info(
            "agent_iteration_start",
            run_id=str(run_id),
            iteration=iteration + 1,
            max_iterations=MAX_ITERATIONS,
            infra_tools_called=infra_tools_called,
        )
        print(f"\n[InfraPilot] ── Iteration {iteration + 1}/{MAX_ITERATIONS} ──────────────────", flush=True)
        print(f"[InfraPilot]    tools so far: {infra_tools_called or ['(none)']}", flush=True)
        print(f"[InfraPilot]    calling OpenAI ({settings.agent_model})...", flush=True)

        response = client.chat.completions.create(
            model=settings.agent_model,
            messages=messages,
            tools=all_tools_spec,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message
        tool_names = [tc.function.name for tc in (assistant_msg.tool_calls or [])]
        print(f"[InfraPilot]    LLM wants to call: {tool_names or ['(no tool calls)']}", flush=True)

        # Append assistant turn to history
        messages.append(_message_to_dict(assistant_msg))

        # No tool calls — agent produced a text response (shouldn't happen with tools available)
        if not assistant_msg.tool_calls:
            logger.warning(
                "agent_no_tool_calls",
                run_id=str(run_id),
                iteration=iteration + 1,
                content=assistant_msg.content or "",
            )
            break

        # Process each tool call in this response
        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            tool_call_id = tool_call.id

            try:
                raw_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as json_err:
                logger.warning(
                    "tool_args_json_decode_failed",
                    run_id=str(run_id),
                    tool_name=tool_name,
                    raw=tool_call.function.arguments[:200],
                    error=str(json_err),
                )
                raw_args = {}

            if tool_name == "generate_report":
                print(f"[InfraPilot]    → generate_report called (unique tools: {set(infra_tools_called)})", flush=True)
                tool_result = _handle_generate_report(
                    raw_args=raw_args,
                    infra_tools_called=infra_tools_called,
                    report_retry_count=report_retry_count,
                    run_id=run_id,
                    db=db,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result["content"],
                })

                if tool_result["status"] == "retry":
                    report_retry_count += 1

                if tool_result["status"] == "complete":
                    print(f"[InfraPilot] ✓ Investigation complete!", flush=True)
                    investigation_complete = True
                    break  # stop processing further tool calls in this batch
                elif tool_result["status"] == "retry_exhausted":
                    print(f"[InfraPilot]    ✗ generate_report validation failed — retries exhausted", flush=True)
                    investigation_complete = True
                    break  # run already marked failed; stop processing
                elif tool_result["status"] == "too_early":
                    print(f"[InfraPilot]    ✗ generate_report rejected: not enough tools yet", flush=True)
                elif tool_result["status"] == "retry":
                    print(f"[InfraPilot]    ✗ generate_report validation failed — retrying", flush=True)

            else:
                # Infra tool call
                print(f"[InfraPilot]    → {tool_name}({list(raw_args.keys())})", flush=True)
                # Only advance sequence_num for tools that exist in the registry
                if tool_name in TOOL_REGISTRY:
                    sequence_num += 1
                result_content = _handle_infra_tool(
                    tool_name=tool_name,
                    raw_args=raw_args,
                    db=db,
                    run_id=run_id,
                    sequence_num=sequence_num,
                )
                if tool_name in TOOL_REGISTRY:
                    infra_tools_called.append(tool_name)
                    print(f"[InfraPilot]       ✓ {tool_name} returned", flush=True)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_content,
                })

        if investigation_complete:
            break

    else:
        # for-loop exhausted MAX_ITERATIONS without completing
        logger.warning("agent_max_iterations", run_id=str(run_id), iterations=MAX_ITERATIONS)
        repo.update_run_failed(
            db,
            run_id,
            error_message=(
                f"Agent reached maximum iterations ({MAX_ITERATIONS}) without producing a report. "
                f"Infra tools called: {infra_tools_called}"
            ),
        )


def _handle_generate_report(
    *,
    raw_args: dict,
    infra_tools_called: list[str],
    report_retry_count: int,
    run_id: UUID,
    db,
) -> dict:
    """
    Handle a generate_report tool call.

    Returns a dict with:
      - status: "too_early" | "retry" | "retry_exhausted" | "complete"
      - content: string to send back as the tool result message
    """
    unique_tools = set(infra_tools_called)

    # Gate: not enough infra tools yet
    if len(unique_tools) < MIN_INFRA_TOOLS:
        missing = MIN_INFRA_TOOLS - len(unique_tools)
        content = (
            f"Cannot generate the report yet. "
            f"You have called {len(unique_tools)} unique infra tool(s) "
            f"({', '.join(sorted(unique_tools)) or 'none'}). "
            f"You need at least {MIN_INFRA_TOOLS} — call {missing} more before generating the report."
        )
        logger.info(
            "generate_report_too_early",
            run_id=str(run_id),
            tools_called=len(unique_tools),
        )
        return {"status": "too_early", "content": content}

    # Validate the report
    try:
        report = build_report(raw_args)
    except ReportValidationError as e:
        if report_retry_count >= 1:
            # Retries exhausted — fail the run
            logger.error(
                "report_validation_failed_final",
                run_id=str(run_id),
                error=str(e),
            )
            repo.update_run_failed(db, run_id, error_message=f"Report validation failed: {e}")
            return {
                "status": "retry_exhausted",
                "content": f"Report validation failed and retries are exhausted: {e}",
            }

        logger.warning(
            "report_validation_retry",
            run_id=str(run_id),
            attempt=report_retry_count + 1,
        )
        content = format_validation_error_for_llm(e)
        return {"status": "retry", "content": content}

    # Success — persist and close out the run
    repo.update_run_completed(
        db,
        run_id,
        report_json=report.model_dump(),
        final_summary=report.final_summary,
        likely_root_cause=report.likely_root_cause,
        confidence_score=report.confidence_score,
    )
    logger.info(
        "investigation_complete",
        run_id=str(run_id),
        root_cause=report.likely_root_cause[:120],
        confidence=report.confidence_score,
        tools_used=report.tools_used,
    )
    return {
        "status": "complete",
        "content": "Report accepted and stored.",
    }


def _handle_infra_tool(
    *,
    tool_name: str,
    raw_args: dict,
    db,
    run_id: UUID,
    sequence_num: int,
) -> str:
    """
    Execute an infra tool and return its result as a JSON string.
    Returns an error string on unknown tool or execution failure.
    """
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        logger.warning("unknown_tool", tool_name=tool_name, run_id=str(run_id))
        return json.dumps({"error": f"Unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"})

    try:
        result = tool.run(
            raw_input=raw_args,
            db=db,
            run_id=run_id,
            sequence_num=sequence_num,
        )
        logger.info(
            "infra_tool_called",
            tool=tool_name,
            run_id=str(run_id),
            sequence_num=sequence_num,
        )
        return json.dumps(result, default=str)
    except Exception as e:
        logger.error(
            "infra_tool_error",
            tool=tool_name,
            run_id=str(run_id),
            error=str(e),
        )
        return json.dumps({"error": f"Tool '{tool_name}' failed: {str(e)}"})


def _message_to_dict(message) -> dict:
    """
    Convert an OpenAI ChatCompletionMessage to a plain dict for the messages list.
    Avoids model_dump() to control exactly what fields are included.
    """
    d: dict = {"role": message.role}
    if message.content is not None:
        d["content"] = message.content
    if message.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return d
