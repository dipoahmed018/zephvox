import { Check, LoaderCircle } from "lucide-react";
import { STAGE_LABELS, type Stage } from "@/engine";
import { cn } from "@/lib/utils";

export function ProgressSteps({ stages }: { stages: Stage[] }) {
  if (!stages.length) {
    return (
      <p className="flex items-center gap-2 text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" /> Getting ready…
      </p>
    );
  }
  return (
    <ol className="grid gap-2" aria-live="polite">
      {stages.map((s) => (
        <li key={s.key} className={cn("flex items-center gap-2.5", s.state === "done" ? "text-muted-foreground" : "font-semibold")}>
          <span
            className={cn(
              "grid size-6 place-items-center rounded-full",
              s.state === "done" ? "bg-success/15 text-success-ink" : "bg-primary/12 text-link",
            )}
          >
            {s.state === "done" ? <Check className="size-3.5" /> : <LoaderCircle className="size-3.5 animate-spin" />}
          </span>
          {STAGE_LABELS[s.key] ?? s.key}
        </li>
      ))}
    </ol>
  );
}
