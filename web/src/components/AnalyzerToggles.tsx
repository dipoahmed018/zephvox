import { Check } from "lucide-react";
import { useState } from "react";

const LABELS: Record<string, string> = { pronunciation: "Pronunciation", grammar: "Grammar" };

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  /** What can run (client mode: what the server offers); undefined = everything. */
  available?: string[];
}

export function AnalyzerToggles({ value, onChange, available }: Props) {
  const [hint, setHint] = useState("");
  const usable = (name: string) => !available || available.includes(name);
  const toggle = (name: string) => {
    const next = value.includes(name) ? value.filter((v) => v !== name) : [...value, name];
    if (!next.some(usable)) {
      setHint("At least one check must stay on.");
      return;
    }
    setHint("");
    onChange(next);
  };
  const missing = value.filter((v) => !usable(v)).map((v) => LABELS[v] ?? v);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row" role="group" aria-label="What to check">
        {Object.entries(LABELS).map(([name, label]) => {
          const on = value.includes(name) && usable(name);
          return (
            <button key={name} type="button" className="toggle-chip" aria-pressed={on} disabled={!usable(name)}
                    title={usable(name) ? undefined : "Not available on this server"} onClick={() => toggle(name)}>
              {on && <Check size={14} />} {label}
            </button>
          );
        })}
      </div>
      {hint && <span className="faint">{hint}</span>}
      {missing.length > 0 && (
        <span className="faint">{missing.join(" and ")} isn't available on this server, so it's skipped.</span>
      )}
    </div>
  );
}
