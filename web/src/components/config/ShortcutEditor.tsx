import { Keyboard, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SettingRow } from "@/components/SettingsSection";
import { Keys } from "@/components/Shortcut";
import { cn } from "@/lib/utils";
import { useConfig } from "./ConfigContext";

const ACTIONS: Record<string, { label: string; description: string }> = {
  toggle_recording: { label: "Start or stop recording", description: "Works while another app is in front." },
  practice_attempt: { label: "Practice attempt", description: "Records one try at the current practice word." },
  cancel: { label: "Cancel", description: "Throws away the recording in progress." },
};

const MODIFIER_KEYS = new Set(["Control", "Shift", "Alt", "Meta", "AltGraph", "OS"]);

/** A key press as the config writes it, e.g. "Ctrl+Shift+Alt+R"; null while only modifiers are down. */
export function comboOf(e: Pick<KeyboardEvent, "key" | "code" | "ctrlKey" | "shiftKey" | "altKey" | "metaKey">): string | null {
  if (MODIFIER_KEYS.has(e.key)) return null;
  const mods = [e.ctrlKey && "Ctrl", e.shiftKey && "Shift", e.altKey && "Alt", e.metaKey && "Super"].filter(Boolean) as string[];
  // Use the physical key so Shift/Alt don't turn "R" into "®" on some layouts.
  const key = e.code.startsWith("Key")
    ? e.code.slice(3)
    : e.code.startsWith("Digit")
      ? e.code.slice(5)
      : /^F\d+$/.test(e.key)
        ? e.key
        : e.key.length === 1
          ? e.key.toUpperCase()
          : e.key;
  return [...mods, key].join("+");
}

/** Click Change, press the new keys; Escape cancels. At least one modifier keeps it from firing while typing. */
function KeyCapture({ action, value, base }: { action: string; value: string; base: string }) {
  const { save, info } = useConfig();
  const [listening, setListening] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  useEffect(() => {
    if (!listening) return;
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === "Escape") {
        setListening(false);
        setHint(null);
        return;
      }
      const combo = comboOf(e);
      if (!combo) return;
      if (!/^(Ctrl|Shift|Alt|Super)\+/.test(combo) || combo.split("+").length < 2) {
        setHint("Use at least one of Ctrl, Alt or Super with a key.");
        return;
      }
      const taken = Object.entries(info.shortcuts.values).find(([a, c]) => a !== action && c === combo);
      if (taken) {
        setHint(`Already used for “${ACTIONS[taken[0]]?.label ?? taken[0]}”.`);
        return;
      }
      setListening(false);
      setHint(null);
      if (combo !== value) save([{ path: ["shortcuts", action], value: combo }]);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [listening, value]);

  const changed = info.overlay.shortcuts?.[action] !== undefined;
  return (
    <SettingRow
      label={ACTIONS[action]?.label ?? action}
      description={hint ? <span className="text-alert-ink">{hint}</span> : ACTIONS[action]?.description}
      aside={changed && <Badge variant="sky">changed here</Badge>}
    >
      {listening ? (
        <span className="rounded-lg border border-dashed border-primary px-3 py-1.5 text-sm text-link" role="status">
          Press the new keys… (Esc to cancel)
        </span>
      ) : (
        <Keys combo={value} />
      )}
      <Button variant="outline" size="sm" onClick={() => setListening(!listening)} className={cn(listening && "invisible")}>
        <Keyboard /> Change
      </Button>
      {changed && (
        <Button variant="ghost" size="icon-sm" aria-label="Back to the default keys" title={`Back to ${base}`} onClick={() => save([{ path: ["shortcuts", action], reset: true }])}>
          <RotateCcw />
        </Button>
      )}
    </SettingRow>
  );
}

export function ShortcutEditor() {
  const { info } = useConfig();
  return (
    <>
      {Object.keys(ACTIONS).map((action) => (
        <KeyCapture key={action} action={action} value={info.shortcuts.values[action]} base={info.shortcuts.base[action]} />
      ))}
    </>
  );
}
