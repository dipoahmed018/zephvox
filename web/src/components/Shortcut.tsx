import { useEngine } from "../engine";

/** True when global shortcuts are registered with the system. */
export function useShortcutsActive(): boolean {
  return Boolean(useEngine().state.triggers?.active);
}

/** Renders the user's key combo for an action as keycaps, e.g. Ctrl + Alt + R. */
export function Shortcut({ action }: { action: string }) {
  const { state } = useEngine();
  const combo = state.triggers?.active ? state.triggers.bindings?.[action] : undefined;
  if (!combo) return null;
  const parts = combo.split("+").map((p) => p.trim());
  return (
    <span className="row" style={{ gap: 4, display: "inline-flex" }}>
      {parts.map((p, i) => (
        <kbd key={i}>{p}</kbd>
      ))}
    </span>
  );
}
