import { AlertTriangle, Info, X, XCircle } from "lucide-react";
import { useEffect } from "react";
import { useEngine } from "../engine";

export function Notices() {
  const { state, dispatch } = useEngine();

  useEffect(() => {
    // Warnings and info fade away on their own; errors stay until dismissed.
    const timers = state.notices
      .filter((n) => n.kind !== "error")
      .map((n) => setTimeout(() => dispatch({ type: "dismiss_notice", id: n.id }), 8000));
    return () => timers.forEach(clearTimeout);
  }, [state.notices, dispatch]);

  return (
    <div className="notices" role="status" aria-live="polite">
      {state.notices.map((n) => (
        <div key={n.id} className={`notice ${n.kind}`}>
          {n.kind === "error" ? (
            <XCircle size={18} color="var(--error)" />
          ) : n.kind === "warning" ? (
            <AlertTriangle size={18} color="var(--amber)" />
          ) : (
            <Info size={18} color="var(--teal)" />
          )}
          <p>{n.text}</p>
          <button className="btn ghost small" aria-label="Dismiss" onClick={() => dispatch({ type: "dismiss_notice", id: n.id })}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
