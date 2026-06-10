import { useState, useRef } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/infrapilot/AppShell";
import { Hero } from "@/components/infrapilot/Hero";
import { DemoScenarios } from "@/components/infrapilot/DemoScenarios";
import { Workflow } from "@/components/infrapilot/Workflow";
import { IncidentForm, emptyIncident } from "@/components/infrapilot/IncidentForm";
import type { IncidentInput } from "@/lib/infrapilot-api";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "InfraPilot AI — Agentic On-Call Copilot" },
      {
        name: "description",
        content:
          "Agentic on-call debugging copilot that investigates production-style incidents and turns safe recommendations into GitHub draft PRs for human review.",
      },
      { property: "og:title", content: "InfraPilot AI — Agentic On-Call Copilot" },
      {
        property: "og:description",
        content:
          "From alert to draft PR: evidence-backed root-cause investigation for SRE and on-call teams.",
      },
    ],
  }),
  component: HomePage,
});

function HomePage() {
  const [form, setForm] = useState<IncidentInput>(emptyIncident);
  const formRef = useRef<HTMLDivElement>(null);

  const handleScenario = (incident: IncidentInput) => {
    setForm(incident);
    requestAnimationFrame(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  return (
    <AppShell>
      <Hero />
      <DemoScenarios onSelect={handleScenario} />
      <Workflow />
      <section ref={formRef} id="custom-incident" className="pt-10">
        <div className="mb-5 max-w-3xl">
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Custom incident
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            Or submit a custom incident
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Custom incidents use the same investigation flow, but seeded scenarios have the
            richest mock data and are recommended for evaluating the end-to-end agent demo.
          </p>
        </div>
        <IncidentForm form={form} setForm={setForm} />
      </section>
    </AppShell>
  );
}
