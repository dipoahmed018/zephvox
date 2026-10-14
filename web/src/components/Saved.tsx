import { Check } from "lucide-react";
import { useRef, useState } from "react";
import { cn } from "@/lib/utils";

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
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-1 text-xs font-semibold text-success-ink transition-opacity duration-300",
        show ? "opacity-100" : "opacity-0",
      )}
    >
      {show && (
        <>
          <Check className="size-3.5" /> {text}
        </>
      )}
    </span>
  );
}
