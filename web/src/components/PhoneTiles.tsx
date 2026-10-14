import type { Phone } from "@/types";
import { cn } from "@/lib/utils";

const LABELS: Record<Phone["status"], string> = {
  ok: "correct",
  minor: "close enough",
  wrong: "wrong sound",
  missing: "missing",
  extra: "extra sound",
};

const STYLES: Record<Phone["status"], string> = {
  ok: "border-border bg-background",
  minor: "border-primary/40 bg-primary/8",
  wrong: "border-alert bg-alert/12 text-alert-ink",
  missing: "border-dashed border-alert bg-transparent text-alert-ink",
  extra: "border-dashed border-muted-foreground/50 bg-transparent text-muted-foreground",
};

/** One tile per sound: the expected sound on top, what was heard underneath when different. */
export function PhoneTiles({ phones }: { phones: Phone[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {phones.map((p, i) => (
        <div
          key={i}
          className={cn(
            "tile grid min-w-11 place-items-center rounded-lg border px-2 py-1.5 text-center animate-in fade-in slide-in-from-bottom-1 fill-mode-both",
            p.status,
            STYLES[p.status],
          )}
          style={{ animationDelay: `${i * 45}ms` }}
          title={LABELS[p.status]}
          aria-label={`${p.expected ?? p.heard}: ${LABELS[p.status]}${p.status === "wrong" ? `, heard ${p.heard}` : ""}`}
        >
          <div className="ipa text-lg leading-tight">{p.expected ?? "+"}</div>
          <div className="ipa min-h-4 text-xs leading-tight opacity-80">
            {p.status === "ok" ? "" : p.status === "missing" ? "—" : p.status === "minor" ? "≈" : p.heard}
          </div>
        </div>
      ))}
    </div>
  );
}
