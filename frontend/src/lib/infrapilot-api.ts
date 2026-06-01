// Simple fetch wrappers for the InfraPilot backend API.
// Base URL is configurable via VITE_INFRAPILOT_API_URL; defaults to local dev server.

const BASE_URL: string =
  import.meta.env.VITE_INFRAPILOT_API_URL ?? "http://localhost:8000";

export type Severity = "low" | "medium" | "high" | "critical";

export interface IncidentInput {
  title: string;
  description: string;
  severity: Severity;
  service_name: string;   // matches backend CreateIncidentRequest.service_name
}

export interface IncidentResponse {
  incident_id: string;
  run_id: string;
  status: "pending" | "running" | "completed" | "failed";
}

export type RunStatus = "pending" | "queued" | "running" | "completed" | "failed";

// Matches backend EvidenceItem: {tool, finding, significance}
export interface Evidence {
  tool: string;
  finding: string;
  significance: string;
  [key: string]: unknown;
}

// Matches backend RecommendedAction: {action, priority, rationale}
export interface RecommendedAction {
  action: string;
  priority: "immediate" | "short_term" | "long_term";
  rationale: string;
  [key: string]: unknown;
}

// Matches backend TimelineItem: {timestamp, event, source}
export interface TimelineEvent {
  timestamp: string;
  event: string;
  source: string;
  [key: string]: unknown;
}

// Matches backend InvestigationReport Pydantic model exactly
export interface RunReport {
  incident_summary: string;
  likely_root_cause: string;
  confidence_score: number;
  evidence: Evidence[];
  timeline: TimelineEvent[];
  recommended_actions: RecommendedAction[];
  tools_used: string[];
  final_summary: string;
}

export interface Run {
  status: RunStatus;
  report_json?: RunReport;
  error_message?: string;   // matches backend field name
}

export interface ToolCall {
  tool_name: string;
  input_json: Record<string, unknown>;
  output_json: unknown;
  latency_ms: number;
  cache_hit: boolean;
  sequence_num: number;
  status: "pending" | "running" | "success" | "error";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...((init?.headers as object) ?? {}) },
    ...init,
  });
  if (!res.ok) {
    // Surface FastAPI's structured error body (e.g. 422 validation detail) so the
    // UI can show a field-level message rather than the opaque "422 Unprocessable Entity".
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail) && body.detail.length > 0) {
        detail = body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join("; ");
      }
    } catch {
      // body wasn't JSON — fall back to status text
    }
    throw new Error(`Request failed: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function createIncident(input: IncidentInput) {
  return request<IncidentResponse>("/incidents", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getRun(runId: string) {
  return request<Run>(`/runs/${runId}`);
}

export function getToolCalls(runId: string) {
  return request<ToolCall[]>(`/runs/${runId}/tool-calls`);
}

// Tools whose role is finalization/reporting rather than infrastructure inspection.
export const REPORTING_TOOLS = new Set(["generate_report"]);

export const TOOL_PURPOSES: Record<string, string> = {
  get_recent_deploys: "Fetch recent deploy history for the service",
  get_service_logs: "Pull recent application logs",
  get_k8s_pod_status: "Inspect pod health and restart counts",
  get_bq_insert_errors: "Look up BigQuery insert error counts",
  get_config_diff: "Diff config / service-account changes across deploys",
  generate_report: "Compose the final investigation report",
};

// ----- Demo scenarios (match the 3 backend-seeded incidents) -----

export interface DemoScenario {
  id: string;
  label: string;
  emoji: string;
  description: string;
  incident: IncidentInput;
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "bq-auth-failure",
    label: "BigQuery auth failure",
    emoji: "🔐",
    description: "lat-cron-job stopped writing to BigQuery after deploy v42",
    incident: {
      title: "BigQuery auth failure",
      service_name: "lat-cron-job",
      severity: "high",
      description:
        "lat-cron-job stopped writing to BigQuery after deploy v42 changed the service account key path.",
    },
  },
  {
    id: "latency-red-herring",
    label: "Latency spike with red herring deploy",
    emoji: "🕵️",
    description: "api-service p99 latency spiked to 8s, but the deploy is innocent",
    incident: {
      title: "Latency spike with red herring deploy",
      service_name: "api-service",
      severity: "high",
      description:
        "api-service p99 latency spiked to 8s — a deploy went out 2 hours ago, but it is innocent; the real cause is DB connection pool exhaustion.",
    },
  },
  {
    id: "silent-bq-data-loss",
    label: "Silent BigQuery data loss",
    emoji: "🔕",
    description: "audit-service wrote zero audit events after schema drift",
    incident: {
      title: "Silent BigQuery data loss",
      service_name: "audit-service",
      severity: "critical",
      description:
        "audit-service wrote zero audit events to BigQuery for 30 minutes — deploy v9 added a new column in code but the production table was never migrated.",
    },
  },
];
