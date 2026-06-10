import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Activity } from "lucide-react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border/60 bg-background/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Activity className="h-4 w-4" strokeWidth={2.5} />
            </div>
            <div className="flex items-baseline gap-1.5">
              <span className="font-semibold tracking-tight">InfraPilot</span>
              <span className="text-xs font-mono text-muted-foreground">AI</span>
            </div>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            <Link
              to="/"
              className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              activeOptions={{ exact: true }}
              activeProps={{ className: "rounded-md px-3 py-1.5 bg-muted text-foreground" }}
            >
              New incident
            </Link>
            <a
              href="https://github.com/kavithadee/infrapilot-ai"
              target="_blank"
              rel="noreferrer"
              className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              GitHub
            </a>
          </nav>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              On-call
            </span>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
