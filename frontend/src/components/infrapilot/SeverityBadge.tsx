import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Severity } from "@/lib/infrapilot-api";

const styles: Record<Severity, string> = {
  low: "bg-muted text-muted-foreground border-border",
  medium: "bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400",
  high: "bg-orange-500/15 text-orange-600 border-orange-500/30 dark:text-orange-400",
  critical: "bg-red-500/15 text-red-600 border-red-500/30 dark:text-red-400",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge variant="outline" className={cn("font-mono text-[10px] uppercase tracking-wider", styles[severity])}>
      {severity}
    </Badge>
  );
}
