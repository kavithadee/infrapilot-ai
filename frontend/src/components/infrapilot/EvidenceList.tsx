import type { Evidence } from "@/lib/infrapilot-api";
import { ExternalLink, FileSearch } from "lucide-react";

export function EvidenceList({ items }: { items: Evidence[] }) {
  if (!items || items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/60 p-6 text-center">
        <FileSearch className="mx-auto h-5 w-5 text-muted-foreground" />
        <p className="mt-2 text-sm text-muted-foreground">Gathering evidence…</p>
      </div>
    );
  }
  return (
    <ul className="space-y-3">
      {items.map((e, i) => (
        <li
          key={i}
          className="rounded-md border border-border/60 bg-card p-4 transition-colors hover:border-foreground/20"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              {/* tool name as the label */}
              <h4 className="truncate text-sm font-medium">{e.tool}</h4>
              {e.significance && (
                <p className="mt-0.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  {e.significance}
                </p>
              )}
            </div>
            {(e as any).link && (
              <a
                href={(e as any).link as string}
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground transition-colors hover:text-foreground"
              >
                <ExternalLink className="h-4 w-4" />
              </a>
            )}
          </div>
          {e.finding && (
            <pre className="mt-2.5 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted/60 p-2.5 font-mono text-xs leading-relaxed">
              {e.finding}
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}
