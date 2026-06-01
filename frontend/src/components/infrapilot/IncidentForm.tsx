import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { AlertCircle, Loader2, Send } from "lucide-react";
import {
  createIncident,
  DEMO_SCENARIOS,
  type IncidentInput,
  type Severity,
} from "@/lib/infrapilot-api";

const empty: IncidentInput = {
  title: "",
  description: "",
  severity: "high",
  service_name: "",
};

export function IncidentForm() {
  const navigate = useNavigate();
  const [form, setForm] = useState<IncidentInput>(empty);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = <K extends keyof IncidentInput>(key: K, value: IncidentInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const { run_id } = await createIncident(form);
      navigate({ to: "/runs/$runId", params: { runId: run_id } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit incident");
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <Card className="border-border/60 p-6">
        <form onSubmit={onSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label
              htmlFor="title"
              className="text-xs font-mono uppercase tracking-wider text-muted-foreground"
            >
              Title
            </Label>
            <Input
              id="title"
              placeholder="e.g. lat-cron-job BigQuery writes stopped"
              value={form.title}
              onChange={(e) => update("title", e.target.value)}
              required
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label
                htmlFor="service"
                className="text-xs font-mono uppercase tracking-wider text-muted-foreground"
              >
                Service
              </Label>
              <Input
                id="service"
                placeholder="lat-cron-job"
                value={form.service_name}
                onChange={(e) => update("service_name", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Severity
              </Label>
              <Select
                value={form.severity}
                onValueChange={(v) => update("severity", v as Severity)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="low">Low</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="critical">Critical</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label
              htmlFor="description"
              className="text-xs font-mono uppercase tracking-wider text-muted-foreground"
            >
              Incident description
            </Label>
            <Textarea
              id="description"
              placeholder="Symptoms, timing, recent deploys, affected service, and anything unusual…"
              rows={7}
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              required
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
            <p className="text-xs text-muted-foreground">
              InfraPilot will investigate autonomously and show the tool-call timeline.
            </p>
            <Button type="submit" disabled={submitting} className="gap-2">
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Dispatching…
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  Investigate
                </>
              )}
            </Button>
          </div>
        </form>
      </Card>

      <div>
        <div className="mb-3 flex items-baseline justify-between">
          <div>
            <h3 className="text-sm font-semibold tracking-tight">Demo scenarios</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Prefill a seeded production-style incident to try the copilot end-to-end.
            </p>
          </div>
          <span className="font-mono text-xs text-muted-foreground">
            {DEMO_SCENARIOS.length}
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {DEMO_SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setForm(s.incident)}
              className="group flex h-full flex-col rounded-md border border-border/60 bg-card p-4 text-left transition-colors hover:border-foreground/30 hover:bg-muted/40"
            >
              <div className="flex items-center gap-2">
                <span className="text-xl leading-none">{s.emoji}</span>
                <span className="text-sm font-medium">{s.label}</span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {s.description}
              </p>
              <div className="mt-3 flex items-center gap-2 border-t border-border/60 pt-2">
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                  {s.incident.service_name}
                </code>
                <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {s.incident.severity}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
