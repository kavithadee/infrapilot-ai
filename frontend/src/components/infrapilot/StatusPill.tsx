import { cn } from "@/lib/utils";
import type { RunStatus, ToolCall } from "@/lib/infrapilot-api";

type AnyStatus = RunStatus | ToolCall["status"];

const map: Record<AnyStatus, { label: string; cls: string; dot: string }> = {
  queued: { label: "Queued", cls: "text-muted-foreground border-border bg-muted/50", dot: "bg-muted-foreground" },
  pending: { label: "Pending", cls: "text-muted-foreground border-border bg-muted/50", dot: "bg-muted-foreground" },
  running: {
    label: "Running",
    cls: "text-sky-600 dark:text-sky-400 border-sky-500/30 bg-sky-500/10",
    dot: "bg-sky-500 animate-pulse",
  },
  completed: {
    label: "Completed",
    cls: "text-emerald-600 dark:text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    dot: "bg-emerald-500",
  },
  success: {
    label: "Success",
    cls: "text-emerald-600 dark:text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
    dot: "bg-emerald-500",
  },
  failed: {
    label: "Failed",
    cls: "text-red-600 dark:text-red-400 border-red-500/30 bg-red-500/10",
    dot: "bg-red-500",
  },
  error: {
    label: "Error",
    cls: "text-red-600 dark:text-red-400 border-red-500/30 bg-red-500/10",
    dot: "bg-red-500",
  },
};

export function StatusPill({ status }: { status: AnyStatus }) {
  const s = map[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        s.cls,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}
