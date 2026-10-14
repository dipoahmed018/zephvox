import { Check } from "lucide-react";

const LABELS: Record<string, string> = { pronunciation: "Pronunciation", grammar: "Grammar" };

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
}

export function AnalyzerToggles({ value, onChange }: Props) {
  const toggle = (name: string) => {
    const next = value.includes(name) ? value.filter((v) => v !== name) : [...value, name];
    if (next.length) onChange(next); // at least one ability must stay on
  };
  return (
    <div className="row" role="group" aria-label="What to check">
      {Object.entries(LABELS).map(([name, label]) => (
        <button key={name} type="button" className="toggle-chip" aria-pressed={value.includes(name)} onClick={() => toggle(name)}>
          {value.includes(name) && <Check size={14} />} {label}
        </button>
      ))}
    </div>
  );
}
