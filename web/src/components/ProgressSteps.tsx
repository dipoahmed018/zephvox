import { Check, LoaderCircle } from "lucide-react";
import { STAGE_LABELS, type Stage } from "../engine";

export function ProgressSteps({ stages }: { stages: Stage[] }) {
  if (!stages.length) {
    return (
      <p className="row muted">
        <LoaderCircle size={18} className="spin" /> Getting ready…
      </p>
    );
  }
  return (
    <ol className="steps" aria-live="polite">
      {stages.map((s) => (
        <li key={s.key} className={`step ${s.state}`}>
          <span className="icon">
            {s.state === "done" ? <Check size={15} /> : <LoaderCircle size={15} className="spin" />}
          </span>
          {STAGE_LABELS[s.key] ?? s.key}
        </li>
      ))}
    </ol>
  );
}
