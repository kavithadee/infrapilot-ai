import { Search, Stethoscope, GitPullRequest } from "lucide-react";

const capabilities = [
  {
    icon: Search,
    title: "Investigate with tools",
    copy: "Uses LLM tool-calling to query seeded deploy history, service logs, pod health, BigQuery errors, and config diffs.",
    iconCls: "bg-sky-500/10 border-sky-500/30 text-sky-600 dark:text-sky-400",
  },
  {
    icon: Stethoscope,
    title: "Build evidence chains",
    copy: "Produces structured root-cause analysis with timeline, confidence score, tool-call trace, and recommended actions.",
    iconCls: "bg-violet-500/10 border-violet-500/30 text-violet-600 dark:text-violet-400",
  },
  {
    icon: GitPullRequest,
    title: "Draft safe fixes",
    copy: "Turns eligible recommendations into policy-guarded GitHub draft PRs so humans can review, edit, and merge.",
    iconCls: "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400",
  },
];

export function Hero() {
  return (
    <section className="border-b border-border/60 pb-10">
      <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-muted/40 px-3 py-1 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-foreground/60" />
        Portfolio demo · LLM tool-calling · human-in-the-loop remediation
      </div>
      <h1 className="mt-5 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
        Agentic on-call debugging, from alert to draft PR.
      </h1>
      <p className="mt-4 max-w-3xl text-base leading-relaxed text-muted-foreground">
        InfraPilot is an agentic on-call copilot that uses LLM tool-calling to investigate
        production-style incidents, build an evidence chain across logs, deploys, Kubernetes
        health, BigQuery errors, and config diffs, then create policy-guarded GitHub draft
        PRs for human review.
      </p>

      <div className="mt-8 grid gap-3 md:grid-cols-3">
        {capabilities.map(({ icon: Icon, title, copy, iconCls }) => (
          <div
            key={title}
            className="rounded-lg border border-border/60 bg-card p-5"
          >
            <div className="flex items-center gap-2.5">
              <div className={`flex h-7 w-7 items-center justify-center rounded-md border ${iconCls}`}>
                <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
              </div>
              <span className="text-sm font-semibold tracking-tight">{title}</span>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{copy}</p>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        InfraPilot never merges or deploys automatically.
      </p>
    </section>
  );
}
