import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/infrapilot/AppShell";
import { IncidentForm } from "@/components/infrapilot/IncidentForm";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "InfraPilot AI — Agentic On-Call Copilot" },
      {
        name: "description",
        content:
          "Submit an incident and let InfraPilot AI investigate autonomously with full tool-call visibility, evidence, and recommended remediation.",
      },
      { property: "og:title", content: "InfraPilot AI — Agentic On-Call Copilot" },
      {
        property: "og:description",
        content: "Agentic debugging copilot for SRE and on-call teams.",
      },
    ],
  }),
  component: HomePage,
});

function HomePage() {
  return (
    <AppShell>
      <div className="mb-8">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          New investigation
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">
          What's broken?
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Describe the incident and InfraPilot will inspect deploy history, service logs,
          Kubernetes-style health, config changes, and data-pipeline errors to generate an
          evidence-backed investigation.
        </p>
      </div>
      <IncidentForm />
    </AppShell>
  );
}
