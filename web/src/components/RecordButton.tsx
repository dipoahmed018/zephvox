import { Mic, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  recording: boolean;
  level?: number;
  onClick: () => void;
  disabled?: boolean;
  size?: "lg" | "sm";
  label: string;
}

/** The one primary control: a round button that breathes with the voice while recording. */
export function RecordButton({ recording, level = 0, onClick, disabled, size = "lg", label }: Props) {
  const lg = size === "lg";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={recording}
      className={cn(
        "group relative grid shrink-0 place-items-center rounded-full text-primary-foreground transition-[background-color,transform] duration-200 ease-[var(--ease-breeze)]",
        "focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50",
        "active:scale-95",
        lg ? "size-22" : "size-11",
        recording ? "bg-alert" : "bg-primary hover:bg-primary/90",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute rounded-full border-2 transition-transform duration-150",
          lg ? "-inset-2.5" : "-inset-1.5",
          recording ? "border-alert/40" : "border-primary/25",
        )}
        style={{ transform: `scale(${1 + level * 0.22})` }}
      />
      {lg && !recording && (
        <span aria-hidden="true" className="absolute -inset-5 rounded-full bg-primary/8 blur-md" />
      )}
      {recording ? (
        <Square className={lg ? "size-7" : "size-4"} fill="currentColor" />
      ) : (
        <Mic className={lg ? "size-9" : "size-5"} strokeWidth={2.1} />
      )}
    </button>
  );
}
