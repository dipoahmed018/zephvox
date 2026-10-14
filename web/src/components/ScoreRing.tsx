import { scoreColor } from "@/format";

export function ScoreRing({ score, size = 96, label }: { score: number; size?: number; label?: string }) {
  const stroke = Math.max(5, Math.round(size / 13));
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <div className="relative inline-grid shrink-0 place-items-center" role="img" aria-label={label ?? `Score ${clamped} out of 100`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={scoreColor(clamped)}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
          className="transition-[stroke-dashoffset] duration-700 ease-[var(--ease-breeze)]"
        />
      </svg>
      <span className="absolute font-display font-normal tabular-nums" style={{ fontSize: size * 0.32 }}>
        {clamped}
      </span>
    </div>
  );
}
