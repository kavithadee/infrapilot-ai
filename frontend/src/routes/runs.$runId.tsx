import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/infrapilot/AppShell";
import { SeverityBadge } from "@/components/infrapilot/SeverityBadge";
import { StatusPill } from "@/components/infrapilot/StatusPill";
import { ToolCallTimeline } from "@/components/infrapilot/ToolCallTimeline";
import { EvidenceList } from "@/components/infrapilot/EvidenceList";
import { ActionsList } from "@/components/infrapilot/ActionsList";
import { RemediationDraftCard } from "@/components/infrapilot/RemediationDraftCard";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  getRun,
  getToolCalls,
  REPORTING_TOOLS,
  type Run,
  type ToolCall,
} from "@/lib/infrapilot-api";
import { isRemediationEligible } from "@/lib/remediation-api";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import {
  ArrowLeft,
  AlertCircle,
  Activity,
  Database,
  Wrench,
  ChevronDown,
} from "lucide-react";

export const Route = createFileRoute("/runs/$runId")({
  component: RunPage,
});

const TERMINAL = new Set(["completed", "failed"]);

function RunPage() {
  const { runId } = Route.useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // fetchedCallsRef: true once tool-calls have been successfully loaded for this run.
  const fetchedCallsRef = useRef(false);
  // statusRef: mirrors run.status so the interval can read it without a stale closure
  // or the React anti-pattern of calling setState just to peek at current value.
  const statusRef = useRef<string | null>(null);
  // inFlightRef: prevents concurrent loadAll() calls when a fetch takes longer than 2 s.
  const inFlightRef = useRef(false);

  async function loadAll() {
    if (inFlightRef.current) return; // skip tick if a previous fetch is still in-flight
    inFlightRef.current = true;
    try {
      const r = await getRun(runId);
      setRun(r);
      statusRef.current = r.status; // keep the ref in sync for the interval
      setError(null);
      if (TERMINAL.has(r.status) && !fetchedCallsRef.current) {
        // Set optimistically so concurrent loadAll() calls don't double-fetch,
        // but reset on transient failure so Refresh can retry.
        fetchedCallsRef.current = true;
        try {
          const c = await getToolCalls(runId);
          setCalls(c);
        } catch {
          // Transient error — reset so the Refresh button can retry.
          fetchedCallsRef.current = false;
        }
      } else if (r.status === "running") {
        try {
          const c = await getToolCalls(runId);
          setCalls(c);
        } catch {
          /* ignore — tool calls may not exist yet */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run");
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }

  // Single effect: reset state and start polling whenever runId changes.
  // Using statusRef (not a setRun updater) to read the current status in the
  // interval avoids the React anti-pattern of issuing side-effects inside
  // setState callbacks (which React Strict Mode double-invokes in development).
  useEffect(() => {
    setRun(null);
    setCalls([]);
    setLoading(true);
    setError(null);
    fetchedCallsRef.current = false;
    statusRef.current = null;
    inFlightRef.current = false;

    loadAll();

    const id = setInterval(() => {
      if (!statusRef.current || !TERMINAL.has(statusRef.current)) {
        loadAll();
      } else {
        clearInterval(id);
      }
    }, 2000);

    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const report = run?.report_json;
  const investigationCalls = calls.filter((c) => !REPORTING_TOOLS.has(c.tool_name));
  const cacheHits = investigationCalls.filter((c) => c.cache_hit).length;

  return (
    <AppShell>
      <div className="mb-6 flex items-center justify-between gap-4">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          New incident
        </Link>
      </div>

      {loading && !run && (
        <div className="py-24 text-center text-sm text-muted-foreground">
          Loading investigation…
        </div>
      )}

      {error && !run && (
        <Card className="border-red-500/30 bg-red-500/5 p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 text-red-500" />
            <div>
              <h3 className="font-medium">Couldn't load run</h3>
              <p className="mt-1 text-sm text-muted-foreground">{error}</p>
              <p className="mt-2 font-mono text-xs text-muted-foreground">run_id: {runId}</p>
            </div>
          </div>
        </Card>
      )}

      {run && (
        <>
          <Card className="mb-6 border-border/60 p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  Run · {runId}
                </p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight">
                  {report?.final_summary ?? report?.incident_summary ?? "Investigation in progress"}
                </h1>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <StatusPill status={run.status} />
                </div>
              </div>
            </div>

            {!TERMINAL.has(run.status) && (
              <div className="mt-5 flex items-center gap-3 rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-sm">
                <Activity className="h-4 w-4 animate-pulse text-sky-500" />
                <span className="text-muted-foreground">
                  InfraPilot is investigating. Polling every 2 seconds…
                </span>
              </div>
            )}

            {run.status === "failed" && (
              <div className="mt-5 flex items-start gap-3 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm">
                <AlertCircle className="mt-0.5 h-4 w-4 text-red-500" />
                <div>
                  <p className="font-medium">Investigation failed</p>
                  <p className="mt-0.5 text-muted-foreground">
                    {run.error_message ?? "The agent could not complete this run."}
                  </p>
                </div>
              </div>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
            {/* Main column */}
            <div className="space-y-6">
              {report && (
                <Card className="border-border/60 p-6">
                  <div className="grid gap-5 md:grid-cols-2">
                    <div>
                      <SectionLabel>Summary</SectionLabel>
                      <p className="mt-1.5 text-sm leading-relaxed">{report.incident_summary}</p>
                    </div>
                    <div>
                      <SectionLabel>Likely root cause</SectionLabel>
                      <p className="mt-1.5 text-sm leading-relaxed">
                        {report.likely_root_cause}
                      </p>
                    </div>
                  </div>
                </Card>
              )}

              {/* Recommended actions — directly below summary so Draft PR is visible early */}
              <section>
                <SectionHeader
                  title="Recommended actions"
                  count={report?.recommended_actions?.length ?? 0}
                />
                {run.status === "completed" && (report?.recommended_actions?.length ?? 0) > 0 ? (
                  <ol className="space-y-3">
                    {(report!.recommended_actions ?? []).map((a, i) => {
                      const priorityStyles: Record<string, string> = {
                        immediate: "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
                        short_term: "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400",
                        long_term: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
                      };
                      const priorityLabels: Record<string, string> = {
                        immediate: "Immediate",
                        short_term: "Short term",
                        long_term: "Long term",
                      };
                      const priorityCls = priorityStyles[a.priority];
                      const priorityLabel = priorityLabels[a.priority] ?? a.priority;
                      return (
                        <li key={i} className="rounded-md border border-border/60 bg-card p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex min-w-0 items-start gap-3">
                              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
                                <span className="font-mono text-xs font-semibold">{i + 1}</span>
                              </div>
                              <div className="min-w-0">
                                <h4 className="text-sm font-medium">{a.action}</h4>
                                {a.rationale && (
                                  <p className="mt-1 text-sm text-muted-foreground">{a.rationale}</p>
                                )}
                              </div>
                            </div>
                            {a.priority && priorityCls && (
                              <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider ${priorityCls}`}>
                                {priorityLabel}
                              </span>
                            )}
                          </div>
                          {isRemediationEligible(a.action) && (
                            <div className="mt-1 pl-9">
                              <RemediationDraftCard runId={runId} recommendation={a.action} />
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                ) : (
                  <ActionsList actions={report?.recommended_actions ?? []} />
                )}
              </section>

              {/* Evidence — collapsible */}
              {report && (
                <Collapsible defaultOpen={false}>
                  <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md border border-border/60 bg-card px-4 py-3 text-left hover:bg-muted/40 transition-colors">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-semibold tracking-tight">Evidence</span>
                      <span className="font-mono text-xs text-muted-foreground">{report.evidence?.length ?? 0}</span>
                    </div>
                    <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
                  </CollapsibleTrigger>
                  <CollapsibleContent className="mt-2">
                    <EvidenceList items={report.evidence ?? []} />
                  </CollapsibleContent>
                </Collapsible>
              )}

              {/* Timeline — collapsible */}
              {report && report.timeline && report.timeline.length > 0 && (
                <Collapsible defaultOpen={false}>
                  <CollapsibleTrigger className="group flex w-full items-center justify-between rounded-md border border-border/60 bg-card px-4 py-3 text-left hover:bg-muted/40 transition-colors">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-semibold tracking-tight">Incident timeline</span>
                      <span className="font-mono text-xs text-muted-foreground">{report.timeline.length}</span>
                    </div>
                    <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
                  </CollapsibleTrigger>
                  <CollapsibleContent className="mt-2">
                    <ol className="relative space-y-3 border-l border-border/60 pl-6">
                      {report.timeline.map((t, i) => (
                        <li key={i} className="relative">
                          <span className="absolute -left-[25px] top-2 h-2 w-2 rounded-full bg-foreground/40" />
                          <div className="rounded-md border border-border/60 bg-card p-3">
                            {t.timestamp && (
                              <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                                {t.timestamp}
                              </div>
                            )}
                            {t.event && <div className="text-sm font-medium">{t.event}</div>}
                            {t.source && (
                              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                                via {t.source}
                              </p>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </CollapsibleContent>
                </Collapsible>
              )}

              <section>
                <SectionHeader title="Tool-call timeline" count={calls.length} />
                <ToolCallTimeline calls={calls} />
              </section>
            </div>

            {/* Sidebar */}
            <aside className="space-y-4">
              <Card className="border-border/60 p-4">
                <SectionLabel>Confidence score</SectionLabel>
                <ConfidenceMeter score={report?.confidence_score} />
              </Card>

              <Card className="border-border/60 p-4 text-sm">
                <SidebarRow label="Status">
                  <StatusPill status={run.status} />
                </SidebarRow>
                <SidebarRow label="Tools called">
                  <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                    <Wrench className="h-3 w-3 text-muted-foreground" />
                    {report?.tools_used?.length ?? investigationCalls.length}
                  </span>
                </SidebarRow>
                <SidebarRow label="Cache hits" last>
                  <span className="inline-flex items-center gap-1.5 font-mono text-xs">
                    <Database className="h-3 w-3 text-muted-foreground" />
                    {cacheHits}
                  </span>
                </SidebarRow>
              </Card>

              {report?.tools_used && report.tools_used.length > 0 && (
                <Card className="border-border/60 p-4">
                  <SectionLabel>Tools used</SectionLabel>
                  <ul className="mt-2 space-y-1">
                    {report.tools_used.map((t) => (
                      <li key={t}>
                        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                          {t}
                        </code>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {report?.final_summary && (
                <Card className="border-border/60 p-4">
                  <SectionLabel>Summary</SectionLabel>
                  <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
                    {report.final_summary}
                  </p>
                </Card>
              )}
            </aside>
          </div>
        </>
      )}
    </AppShell>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
      {children}
    </h3>
  );
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="mb-3 flex items-baseline justify-between">
      <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      <span className="font-mono text-xs text-muted-foreground">{count}</span>
    </div>
  );
}

function SidebarRow({
  label,
  children,
  last,
}: {
  label: string;
  children: React.ReactNode;
  last?: boolean;
}) {
  return (
    <div
      className={
        "flex items-center justify-between py-2 " +
        (last ? "" : "border-b border-border/60")
      }
    >
      <span className="text-xs text-muted-foreground">{label}</span>
      <div>{children}</div>
    </div>
  );
}

function ConfidenceMeter({ score }: { score?: number }) {
  if (score == null) {
    return <p className="mt-2 text-sm text-muted-foreground">Pending…</p>;
  }
  const pct = Math.round(score * 100);
  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between">
        <span className="text-2xl font-semibold tabular-nums">{pct}%</span>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          agent confidence
        </span>
      </div>
      <Progress value={pct} className="mt-2 h-1.5" />
    </div>
  );
}
