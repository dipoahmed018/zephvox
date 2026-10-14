import { useEngine } from "@/engine";
import { cn } from "@/lib/utils";

/** True when global shortcuts are registered with the system. */
export function useShortcutsActive(): boolean {
  return Boolean(useEngine().state.triggers?.active);
}

/** A key combination as keycaps, e.g. Ctrl Shift Alt R. */
export function Keys({ combo, className }: { combo: string; className?: string }) {
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1 align-middle", className)} aria-label={combo.replace(/\+/g, " ")}>
      {combo.split("+").map((k, i) => (
        <kbd key={i}>{k.trim()}</kbd>
      ))}
    </span>
  );
}

/** The user's key combination for an action, when shortcuts are active. */
export function Shortcut({ action, className }: { action: string; className?: string }) {
  const { state } = useEngine();
  const combo = state.triggers?.active ? state.triggers.bindings?.[action] : undefined;
  return combo ? <Keys combo={combo} className={className} /> : null;
}
