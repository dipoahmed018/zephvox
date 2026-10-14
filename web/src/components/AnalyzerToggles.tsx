import { useState } from "react";
import { Switch } from "@/components/ui/switch";
import { SettingRow } from "./SettingsSection";

const CHECKS: { name: string; label: string; description: string }[] = [
  { name: "pronunciation", label: "Pronunciation", description: "Compares your sounds with the dictionary." },
  { name: "grammar", label: "Grammar", description: "Reads your sentences for mistakes." },
];

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  /** What can run (client mode: what the server offers); undefined = everything. */
  available?: string[];
  /** Shown next to the check that was just changed. */
  savedMark?: React.ReactNode;
}

/** One switch per check. At least one has to stay on. */
export function AnalyzerToggles({ value, onChange, available, savedMark }: Props) {
  const [hint, setHint] = useState<string | null>(null);
  const usable = (name: string) => !available || available.includes(name);

  const toggle = (name: string) => {
    // Always in the same order, however they were toggled.
    const next = CHECKS.map((c) => c.name).filter((n) => (n === name ? !value.includes(n) : value.includes(n)));
    if (!next.some(usable)) {
      setHint(name);
      return;
    }
    setHint(null);
    onChange(next);
  };

  return (
    <>
      {CHECKS.map((c) => {
        const ok = usable(c.name);
        const on = value.includes(c.name) && ok;
        return (
          <SettingRow
            key={c.name}
            label={c.label}
            htmlFor={`check-${c.name}`}
            description={
              !ok ? (
                <span className="text-alert-ink">{c.label} isn't available on this server, so it's skipped.</span>
              ) : hint === c.name ? (
                <span className="text-alert-ink">At least one check must stay on.</span>
              ) : (
                c.description
              )
            }
            aside={hint === null && savedMark}
          >
            <Switch id={`check-${c.name}`} checked={on} disabled={!ok} onCheckedChange={() => toggle(c.name)} />
          </SettingRow>
        );
      })}
    </>
  );
}
