import type { RecommendedAction } from "@/lib/infrapilot-api";
import { ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

// Maps backend priority values to display styles
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

export function ActionsList({ actions }: { actions: RecommendedAction[] }) {
  if (!actions || actions.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 p-6 text-center">
        <ShieldCheck className="mx-auto h-5 w-5 text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">Recommendations will appear here.</p>
      </div>
    );
  }
  return (
    <ol className="space-y-3">
      {actions.map((a, i) => {
        const priorityCls = priorityStyles[a.priority];
        const priorityLabel = priorityLabels[a.priority] ?? a.priority;
        return (
          <li key={i} className="rounded-md border border-border/60 bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-start gap-3">
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-foreground text-background">
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
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider",
                    priorityCls,
                  )}
                >
                  {priorityLabel}
                </span>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
