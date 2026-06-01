import { StatusPill } from "./StatusPill";
import { REPORTING_TOOLS, TOOL_PURPOSES, type ToolCall } from "@/lib/infrapilot-api";
import { Terminal, ChevronDown, Database, FileCheck2 } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

export function ToolCallTimeline({ calls }: { calls: ToolCall[] }) {
  if (!calls || calls.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 p-8 text-center">
        <Terminal className="mx-auto h-5 w-5 text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">No tool calls yet.</p>
      </div>
    );
  }

  const sorted = [...calls].sort((a, b) => a.sequence_num - b.sequence_num);
  const investigation = sorted.filter((c) => !REPORTING_TOOLS.has(c.tool_name));
  const reporting = sorted.filter((c) => REPORTING_TOOLS.has(c.tool_name));

  return (
    <div className="space-y-6">
      <div>
        <ol className="relative space-y-3 border-l border-border/60 pl-6">
          {investigation.map((c) => (
            <ToolCallItem key={`${c.sequence_num}-${c.tool_name}`} call={c} />
          ))}
        </ol>
      </div>

      {reporting.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-2">
            <FileCheck2 className="h-3.5 w-3.5 text-muted-foreground" />
            <h3 className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
              Final report generation
            </h3>
          </div>
          <ol className="space-y-2">
            {reporting.map((c) => (
              <ToolCallItem key={`r-${c.sequence_num}`} call={c} variant="reporting" />
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function ToolCallItem({
  call,
  variant = "investigation",
}: {
  call: ToolCall;
  variant?: "investigation" | "reporting";
}) {
  const [open, setOpen] = useState(false);
  const hasInput = call.input_json && Object.keys(call.input_json).length > 0;
  const hasOutput = call.output_json !== null && call.output_json !== undefined;
  const hasDetails = hasInput || hasOutput;
  const purpose = TOOL_PURPOSES[call.tool_name];

  return (
    <li className="relative">
      {variant === "investigation" && (
        <span
          className={cn(
            "absolute -left-[29px] top-3 flex h-4 w-4 items-center justify-center rounded-full border-2 border-background",
            call.status === "success" && "bg-emerald-500",
            call.status === "error" && "bg-red-500",
            call.status === "running" && "bg-sky-500 animate-pulse",
            call.status === "pending" && "bg-muted-foreground",
          )}
        />
      )}
      <div className="rounded-md border border-border/60 bg-card">
        <button
          type="button"
          onClick={() => hasDetails && setOpen((o) => !o)}
          className={cn(
            "flex w-full items-start justify-between gap-3 p-3 text-left",
            hasDetails && "cursor-pointer hover:bg-muted/40",
          )}
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">
                #{String(call.sequence_num).padStart(2, "0")}
              </span>
              <code className="truncate rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {call.tool_name}
              </code>
              <span className="font-mono text-xs text-muted-foreground">
                {call.latency_ms}ms
              </span>
              {call.cache_hit && (
                <span className="inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-violet-600 dark:text-violet-400">
                  <Database className="h-2.5 w-2.5" />
                  cache hit
                </span>
              )}
            </div>
            {purpose && (
              <p className="mt-1 text-xs text-muted-foreground">{purpose}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <StatusPill status={call.status} />
            {hasDetails && (
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform",
                  open && "rotate-180",
                )}
              />
            )}
          </div>
        </button>
        {open && hasDetails && (
          <div className="space-y-3 border-t border-border/60 p-3">
            {hasInput && (
              <div>
                <div className="mb-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                  Input
                </div>
                <pre className="max-h-60 overflow-auto rounded bg-muted/60 p-2.5 font-mono text-xs">
                  {JSON.stringify(call.input_json, null, 2)}
                </pre>
              </div>
            )}
            {hasOutput && (
              <div>
                <div className="mb-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
                  Output
                </div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-muted/60 p-2.5 font-mono text-xs">
                  {typeof call.output_json === "string"
                    ? call.output_json
                    : JSON.stringify(call.output_json, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
