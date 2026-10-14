import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useEngine } from "@/engine";

/** Engine notices become toasts: warnings fade after a while, errors stay until dismissed. */
export function Notices() {
  const { state, dispatch } = useEngine();
  const shown = useRef(new Set<number>());

  useEffect(() => {
    const live = new Set(state.notices.map((n) => n.id));
    for (const n of state.notices) {
      if (shown.current.has(n.id)) continue;
      shown.current.add(n.id);
      const dismiss = () => dispatch({ type: "dismiss_notice", id: n.id });
      const options = {
        id: n.id,
        duration: n.kind === "error" ? Infinity : 8000,
        closeButton: true,
        onDismiss: dismiss,
        onAutoClose: dismiss,
      };
      if (n.kind === "error") toast.error(n.text, options);
      else if (n.kind === "warning") toast.warning(n.text, options);
      else toast.info(n.text, options);
    }
    // Notices pushed out of the engine's short list close here too.
    for (const id of shown.current) {
      if (!live.has(id)) {
        toast.dismiss(id);
        shown.current.delete(id);
      }
    }
  }, [state.notices, dispatch]);

  return null;
}
