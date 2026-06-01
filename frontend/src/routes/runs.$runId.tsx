import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/infrapilot/AppShell";
import { SeverityBadge } from "@/components/infrapilot/SeverityBadge";
import { StatusPill } from "@/components/infrapilot/StatusPill";
import { ToolCallTimeline } from "@/components/infrapilot/ToolCallTimeline";
import { EvidenceList } from "@/components/infrapilot/EvidenceList";
import { ActionsList } from "@/components/infrapilot/ActionsList";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import {
  getRun,
  getToolCalls,
  REPORTING_TOOLS,
  type Run,
  type ToolCall,
} from "@/lib/infrapilot-api";
import {
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  Activity,
  Database,
  Wrench,
  Info,
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
  const fetchedCallsRef = useRef(false);

  // Reset per-run state whenever the run ID changes.
  useEffect(() => {
    setRun(null);
    setCalls([]);
    setLoading(true);
    setError(null);
    fetchedCallsRef.current = false;
  }, [runId]);

  async function loadAll() {
    try {
      const r = await getRun(runId);
      setRun(r);
      setError(null);
      if (TERMINAL.has(r.status) && !fetchedCallsRef.current) {
        fetchedCallsRef.current = true;
        try {
          const c = await getToolCalls(runId);
          setCalls(c);
        } catch {
          // tool-calls might 404 on failure; ignore
        }
      } else if (r.status === "running") {
        try {
          const c = await getToolCalls(runId);
          setCalls(c);
        } catch {
          /* ignore */
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();

    const id = setInterval(() => {
      setRun((current) => {
        // Read latest run status inside the updater to avoid stale closure.
        if (!current || !TERMINAL.has(current.status)) {
          loadAll();
        } else {
          // Run is terminal — stop polling.
          clearInterval(id);
        }
        return current; // no state change, just peeking
      });
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
        <Button variant="outline" size="sm" onClick={loadAll} className="gap-1.5">
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
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

              {report && (
                <section>
                  <SectionHeader title="Evidence" count={report.evidence?.length ?? 0} />
                  <EvidenceList items={report.evidence ?? []} />
                </section>
              )}

              {report && report.timeline && report.timeline.length > 0 && (
                <section>
                  <SectionHeader title="Timeline" count={report.timeline.length} />
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
                </section>
              )}

              <section>
                <SectionHeader
                  title="Recommended actions"
                  count={report?.recommended_actions?.length ?? 0}
                />
                <ActionsList actions={report?.recommended_actions ?? []} />
              </section>

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
