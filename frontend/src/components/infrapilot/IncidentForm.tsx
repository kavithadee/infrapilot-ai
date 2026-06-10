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
  type IncidentInput,
  type Severity,
} from "@/lib/infrapilot-api";

const empty: IncidentInput = {
  title: "",
  description: "",
  severity: "high",
  service_name: "",
};

const KNOWN_SERVICES = ["audit-service", "lat-cron-job", "api-service"];

interface Props {
  form: IncidentInput;
  setForm: React.Dispatch<React.SetStateAction<IncidentInput>>;
}

export function IncidentForm({ form, setForm }: Props) {
  const navigate = useNavigate();
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

  // Map current service_name to Select value:
  // known service → use as-is; non-empty unknown → "__custom"; empty → ""
  const serviceValue = form.service_name && KNOWN_SERVICES.includes(form.service_name)
    ? form.service_name
    : form.service_name
      ? "__custom"
      : "";

  return (
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
            placeholder="e.g. audit-service stopped writing BigQuery events"
            value={form.title}
            onChange={(e) => update("title", e.target.value)}
            required
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Service
            </Label>
            <Select
              value={serviceValue || undefined}
              onValueChange={(v) => {
                if (v === "__custom") {
                  update("service_name", "");
                } else {
                  update("service_name", v);
                }
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a service" />
              </SelectTrigger>
              <SelectContent>
                {KNOWN_SERVICES.map((svc) => (
                  <SelectItem key={svc} value={svc}>
                    {svc}
                  </SelectItem>
                ))}
                <SelectItem value="__custom">Other (custom)…</SelectItem>
              </SelectContent>
            </Select>
            {serviceValue === "__custom" && (
              <Input
                placeholder="custom-service-name"
                value={form.service_name}
                onChange={(e) => update("service_name", e.target.value)}
                className="mt-2"
              />
            )}
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
            placeholder="Describe symptoms, timing, recent deploys, affected service, and anything unusual…"
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
            Custom incidents use the same investigation flow, but seeded scenarios have the
            richest mock data and are recommended for evaluating the end-to-end agent demo.
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
  );
}

export { empty as emptyIncident };
