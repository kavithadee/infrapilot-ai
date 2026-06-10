import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowRight, Sparkles } from "lucide-react";
import { DEMO_SCENARIOS, type DemoScenario, type IncidentInput } from "@/lib/infrapilot-api";

interface Props {
  onSelect: (incident: IncidentInput) => void;
}

function badgeVariantFor(label: string): "default" | "secondary" | "outline" {
  if (label === "Recommended") return "default";
  if (label === "Full demo" || label === "GitHub draft PR") return "secondary";
  return "outline";
}

function FeaturedCard({ s, onSelect }: { s: DemoScenario; onSelect: Props["onSelect"] }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-foreground/25 bg-gradient-to-br from-muted/60 via-card to-card p-6 shadow-sm">
      <div className="absolute right-0 top-0 hidden h-32 w-32 -translate-y-10 translate-x-10 rounded-full bg-foreground/[0.04] blur-2xl sm:block" />
      <div className="relative flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="max-w-2xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-2xl leading-none">{s.emoji}</span>
            <h3 className="text-lg font-semibold tracking-tight">{s.label}</h3>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {s.badges.map((b) => (
              <Badge key={b} variant={badgeVariantFor(b)} className="gap-1">
                {b === "Recommended" && <Sparkles className="h-3 w-3" />}
                {b}
              </Badge>
            ))}
          </div>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
            {s.description}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Best starting point: demonstrates investigation, diagnosis, recommendation, and human-in-the-loop PR remediation.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
              {s.incident.service_name}
            </code>
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {s.incident.severity}
            </span>
          </div>
        </div>
        <div className="shrink-0">
          <Button onClick={() => onSelect(s.incident)} className="gap-2">
            {s.ctaLabel}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function SecondaryCard({ s, onSelect }: { s: DemoScenario; onSelect: Props["onSelect"] }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border/60 bg-card p-5">
      <div className="flex items-center gap-2">
        <span className="text-xl leading-none">{s.emoji}</span>
        <h4 className="text-sm font-semibold tracking-tight">{s.label}</h4>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {s.badges.map((b) => (
          <Badge key={b} variant="outline" className="text-[10px]">
            {b}
          </Badge>
        ))}
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{s.description}</p>
      <div className="mt-3 flex items-center gap-2">
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
          {s.incident.service_name}
        </code>
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {s.incident.severity}
        </span>
      </div>
      <div className="mt-4 border-t border-border/60 pt-3">
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-2"
          onClick={() => onSelect(s.incident)}
        >
          {s.ctaLabel}
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

export function DemoScenarios({ onSelect }: Props) {
  const featured = DEMO_SCENARIOS.find((s) => s.featured)!;
  const others = DEMO_SCENARIOS.filter((s) => !s.featured);

  return (
    <section className="py-10">
      <div className="mb-5 max-w-3xl">
        <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
          Demo scenarios
        </p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">
          Try a seeded production incident
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          These scenarios run against seeded infrastructure data so reviewers can evaluate the full
          agent workflow without connecting real production systems.
        </p>
      </div>

      <FeaturedCard s={featured} onSelect={onSelect} />

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {others.map((s) => (
          <SecondaryCard key={s.id} s={s} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}
