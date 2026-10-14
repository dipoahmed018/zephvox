import { Mic, Square } from "lucide-react";

interface Props {
  recording: boolean;
  level?: number;
  onClick: () => void;
  disabled?: boolean;
  small?: boolean;
  label: string;
}

export function RecordButton({ recording, level = 0, onClick, disabled, small, label }: Props) {
  const size = small ? 34 : 52;
  return (
    <button
      type="button"
      className={`rec-button${recording ? " recording" : ""}${small ? " small" : ""}`}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      aria-pressed={recording}
    >
      <span className="ring" style={{ transform: `scale(${1 + level * 0.18})` }} />
      {recording ? <Square size={size - 14} fill="currentColor" /> : <Mic size={size} strokeWidth={2.2} />}
    </button>
  );
}
