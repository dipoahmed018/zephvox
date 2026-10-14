import type { Phone } from "../types";

const LABELS: Record<Phone["status"], string> = {
  ok: "correct",
  minor: "close enough",
  wrong: "wrong sound",
  missing: "missing",
  extra: "extra sound",
};

/** One tile per sound: the expected sound on top, what was heard underneath when different. */
export function PhoneTiles({ phones }: { phones: Phone[] }) {
  return (
    <div className="tiles">
      {phones.map((p, i) => (
        <div
          key={i}
          className={`tile ${p.status}`}
          style={{ animationDelay: `${i * 45}ms` }}
          title={LABELS[p.status]}
          aria-label={`${p.expected ?? p.heard}: ${LABELS[p.status]}${p.status === "wrong" ? `, heard ${p.heard}` : ""}`}
        >
          <div className="exp">{p.expected ?? "+"}</div>
          <div className="heard">
            {p.status === "ok" ? "" : p.status === "missing" ? "—" : p.status === "minor" ? "≈" : p.heard}
          </div>
        </div>
      ))}
    </div>
  );
}
