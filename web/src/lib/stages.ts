// The engine reports fine-grained stages; the sky shows them as up to three gates.
import type { Gate } from "@/components/wind/WindCanvas";
import type { Stage } from "@/engine";

const GROUPS: { label: string; keys: string[]; analyzer?: string }[] = [
  { label: "Transcribe", keys: ["upload", "transcript"] },
  { label: "Sounds", keys: ["expected_phonemes", "heard_phonemes", "analyzer:pronunciation"], analyzer: "pronunciation" },
  { label: "Grammar", keys: ["analyzer:grammar"], analyzer: "grammar" },
];

/** Gates for an analysis: the checks that will run, each waiting, running or done. */
export function gatesFor(stages: Stage[], analyzers: string[]): Gate[] {
  const seen = new Map(stages.map((s) => [s.key, s.state]));
  const groups = GROUPS.filter(
    (g) => !g.analyzer || analyzers.includes(g.analyzer) || g.keys.some((k) => seen.has(k)),
  );
  return groups.map((g, i) => {
    const states = g.keys.filter((k) => seen.has(k)).map((k) => seen.get(k));
    const later = groups.slice(i + 1).some((n) => n.keys.some((k) => seen.has(k)));
    if (states.includes("running")) return { label: g.label, state: "running" };
    if (states.length && (later || i === groups.length - 1)) return { label: g.label, state: "done" };
    return { label: g.label, state: states.length ? "running" : "waiting" };
  });
}
