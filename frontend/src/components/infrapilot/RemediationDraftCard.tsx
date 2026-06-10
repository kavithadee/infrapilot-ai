/**
 * RemediationDraftCard — v1.6 human-in-the-loop remediation UI.
 *
 * States:
 *   idle      — no draft yet; shows "Draft PR" button
 *   drafting  — background task running; spinner + polling every 3 s
 *   pr_created — success; PR URL, branch, file list, human-review banner
 *   failed    — error message from backend
 *
 * Usage:
 *   <RemediationDraftCard runId={runId} recommendation={action.action} />
 */

import { useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  createRemediationDraft,
  getRemediationDraft,
  listRemediationDrafts,
  type RemediationDraft,
} from "@/lib/remediation-api";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileCode,
  GitPullRequest,
  Loader2,
  ShieldAlert,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RemediationDraftCardProps {
  runId: string;
  /** The exact recommendation text that will be sent to the backend. */
  recommendation: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RemediationDraftCard({ runId, recommendation }: RemediationDraftCardProps) {
  const [draft, setDraft] = useState<RemediationDraft | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable ref so the polling interval can read the latest draft without
  // causing a stale-closure bug.
  const draftRef = useRef<RemediationDraft | null>(null);
  draftRef.current = draft;

  // On mount: check if a draft already exists for this recommendation so the
  // card restores its state after a page refresh.
  useEffect(() => {
    let cancelled = false;
    listRemediationDrafts(runId)
      .then((drafts) => {
        if (cancelled) return;
        // Find the most recent draft for this exact recommendation.
        const match = drafts.find((d) => d.selected_recommendation === recommendation);
        if (match) setDraft(match);
      })
      .catch(() => {
        // Non-fatal — card just starts in idle state.
      });
    return () => {
      cancelled = true;
    };
  }, [runId, recommendation]);

  // Poll while status === "drafting".
  useEffect(() => {
    if (!draft || draft.status !== "drafting") return;

    const id = setInterval(async () => {
      if (draftRef.current?.status !== "drafting") {
        clearInterval(id);
        return;
      }
      try {
        const updated = await getRemediationDraft(draft.id);
        setDraft(updated);
        if (updated.status !== "drafting") clearInterval(id);
      } catch {
        // Transient fetch error — keep polling.
      }
    }, 3000);

    return () => clearInterval(id);
  }, [draft?.id, draft?.status]);

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  async function handleDraftPR() {
    setSubmitting(true);
    setError(null);
    try {
      const created = await createRemediationDraft(runId, recommendation);
      setDraft(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create draft");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Nothing yet — show the "Draft PR" trigger.
  if (!draft) {
    return (
      <div className="mt-3 flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 text-xs"
          onClick={handleDraftPR}
          disabled={submitting}
        >
          {submitting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <GitPullRequest className="h-3.5 w-3.5" />
          )}
          {submitting ? "Creating draft…" : "Draft PR"}
        </Button>
        {error && (
          <p className="text-xs text-red-500">{error}</p>
        )}
      </div>
    );
  }

  // Drafting — spinner card.
  if (draft.status === "drafting") {
    return (
      <Card className="mt-3 border-sky-500/30 bg-sky-500/5 p-4">
        <div className="flex items-center gap-3">
          <Loader2 className="h-4 w-4 animate-spin text-sky-500 shrink-0" />
          <div>
            <p className="text-sm font-medium">Creating draft PR…</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Reading schemas, generating fix, opening branch. This takes ~30–60 s.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  // Failed.
  if (draft.status === "failed") {
    return (
      <Card className="mt-3 border-red-500/30 bg-red-500/5 p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <div className="min-w-0">
            <p className="text-sm font-medium">Draft PR failed</p>
            <p className="mt-0.5 text-xs text-muted-foreground break-words">
              {draft.error_message ?? "An unknown error occurred."}
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 h-6 gap-1 px-2 text-xs"
              onClick={() => {
                setDraft(null);
                setError(null);
              }}
            >
              Try again
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  // pr_created — the full card.
  const spec = draft.fix_spec_json;
  return (
    <Card className="mt-3 border-emerald-500/30 bg-card p-4">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
          <span className="text-sm font-medium">Draft PR ready</span>
        </div>
        {draft.github_pr_url && (
          <a
            href={draft.github_pr_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0"
          >
            <Button variant="default" size="sm" className="h-7 gap-1.5 text-xs">
              <ExternalLink className="h-3 w-3" />
              Open PR
            </Button>
          </a>
        )}
      </div>

      {/* Human-review banner */}
      <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
        <p className="text-xs text-amber-700 dark:text-amber-400">
          <span className="font-semibold">Human review required.</span> This is a draft PR only —
          InfraPilot never merges automatically. Review and merge manually.
        </p>
      </div>

      {/* Meta rows */}
      <div className="mt-3 space-y-1.5">
        {draft.branch_name && (
          <MetaRow label="Branch">
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
              {draft.branch_name}
            </code>
          </MetaRow>
        )}
        {spec?.pr_title && (
          <MetaRow label="PR title">
            <span className="text-xs">{spec.pr_title}</span>
          </MetaRow>
        )}
      </div>

      {/* Files */}
      {spec?.files && spec.files.length > 0 && (
        <div className="mt-3">
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Files changed ({spec.files.length})
          </p>
          <ul className="space-y-1">
            {spec.files.map((f) => (
              <li key={f.path} className="flex items-center gap-2">
                <FileCode className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <code className="truncate font-mono text-[11px] text-muted-foreground">
                  {f.path}
                </code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Change summary */}
      {spec?.change_summary && (
        <p className="mt-3 text-xs text-muted-foreground leading-relaxed">
          {spec.change_summary}
        </p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Small helper
// ---------------------------------------------------------------------------

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn(
          "w-14 shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground",
        )}
      >
        {label}
      </span>
      {children}
    </div>
  );
}
