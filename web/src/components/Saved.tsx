import { Check } from "lucide-react";
import { useRef, useState } from "react";

/** Settings save as soon as they change; this briefly confirms which one just did. */
export function useSaved() {
  const [key, setKey] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  return {
    is: (k: string) => key === k,
    flash: (k: string) => {
      setKey(k);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setKey(null), 2000);
    },
  };
}

export function SavedMark({ show, text = "Saved" }: { show: boolean; text?: string }) {
  return (
    <span className={`saved-mark${show ? " show" : ""}`} role="status" aria-live="polite">
      {show && (
        <>
          <Check size={14} /> {text}
        </>
      )}
    </span>
  );
}
