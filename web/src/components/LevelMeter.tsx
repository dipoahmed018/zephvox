interface Props {
  levels: number[];
  bars?: number;
  compact?: boolean;
}

/** Scrolling bar meter of recent input levels (0–1). */
export function LevelMeter({ levels, bars = 32, compact = false }: Props) {
  const recent = levels.slice(-bars);
  const padded = [...Array(Math.max(0, bars - recent.length)).fill(0), ...recent];
  const max = compact ? 18 : 44;
  return (
    <div className={`meter${compact ? " compact" : ""}`} aria-hidden="true">
      {padded.map((l, i) => (
        <span key={i} style={{ height: Math.max(3, Math.round(l * max)) }} />
      ))}
    </div>
  );
}
