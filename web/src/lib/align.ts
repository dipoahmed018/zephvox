/** One column of an alignment: the expected sound and what was heard (null = nothing there). */
export type SoundPair = [expected: string | null, heard: string | null];

/** "/θ ɪ ŋ k/" → ["θ", "ɪ", "ŋ", "k"] */
export function splitSounds(ipa: string): string[] {
  return ipa.replace(/^\/|\/$/g, "").trim().split(/\s+/).filter(Boolean);
}

/** Line up expected and heard sounds with the fewest edits, so a missing or extra sound shows as a gap. */
export function alignSounds(expected: string[], heard: string[]): SoundPair[] {
  const n = expected.length;
  const m = heard.length;
  const cost = Array.from({ length: n + 1 }, (_, i) => Array.from({ length: m + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const swap = cost[i - 1][j - 1] + (expected[i - 1] === heard[j - 1] ? 0 : 1);
      cost[i][j] = Math.min(swap, cost[i - 1][j] + 1, cost[i][j - 1] + 1);
    }
  }
  const out: SoundPair[] = [];
  let i = n;
  let j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && cost[i][j] === cost[i - 1][j - 1] + (expected[i - 1] === heard[j - 1] ? 0 : 1)) {
      out.push([expected[--i], heard[--j]]);
    } else if (i > 0 && cost[i][j] === cost[i - 1][j] + 1) {
      out.push([expected[--i], null]);
    } else {
      out.push([null, heard[--j]]);
    }
  }
  return out.reverse();
}
