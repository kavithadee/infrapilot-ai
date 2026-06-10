const steps = [
  {
    title: "Choose a seeded incident",
    copy: "Start from production-style mock signals with known deploy, log, data-pipeline, and config context.",
  },
  {
    title: "Agent calls tools",
    copy: "InfraPilot uses LLM tool-calling to inspect deploys, logs, pod health, BigQuery errors, and config diffs.",
  },
  {
    title: "Review root cause",
    copy: "See an evidence-backed diagnosis with timeline, confidence score, tool-call trace, and recommended actions.",
  },
  {
    title: "Human reviews PR",
    copy: "For the schema-drift demo, InfraPilot creates a GitHub draft PR. A human reviews the diff before merging.",
  },
];

export function Workflow() {
  return (
    <section className="border-y border-border/60 py-10">
      <div className="mb-6 max-w-3xl">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Workflow
        </p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">
          How the demo works
        </h2>
      </div>
      <ol className="grid gap-3 md:grid-cols-4">
        {steps.map((s, i) => (
          <li
            key={s.title}
            className="relative rounded-lg border border-border/60 bg-card p-4"
          >
            <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              Step {String(i + 1).padStart(2, "0")}
            </div>
            <h3 className="mt-2 text-sm font-semibold tracking-tight">{s.title}</h3>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{s.copy}</p>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-xs text-muted-foreground">
        Human-in-the-loop by design: the agent drafts; the engineer reviews.
      </p>
    </section>
  );
}
