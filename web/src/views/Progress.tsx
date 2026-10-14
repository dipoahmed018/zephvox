import { ArrowRight, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHead, SectionLabel } from "@/components/PageHead";
import { api } from "@/api";
import { useAction } from "@/engine";
import { plural } from "@/format";
import { cn } from "@/lib/utils";
import { navigate } from "@/router";
import type { History, WeakWord } from "@/types";

function Bars({ items, tone }: { items: [string, number][]; tone: "alert" | "mint" }) {
  const max = Math.max(1, ...items.map(([, n]) => n));
  return (
    <ul className="m-0 grid list-none gap-3 p-0">
      {items.slice(0, 8).map(([label, n]) => (
        <li key={label} className="grid grid-cols-[minmax(4.5rem,9rem)_1fr_2rem] items-center gap-3">
          <span className={cn("truncate text-sm", tone === "alert" && "ipa")}>{label}</span>
          <span className="h-2 overflow-hidden rounded-full bg-muted">
            <span
              className={cn("block h-full rounded-full", tone === "alert" ? "bg-alert" : "bg-mint")}
              style={{ width: `${(n / max) * 100}%` }}
            />
          </span>
          <span className="text-right text-sm text-muted-foreground tabular-nums">{n}</span>
        </li>
      ))}
    </ul>
  );
}

export function Progress() {
  const run = useAction();
  const [history, setHistory] = useState<History | null>(null);
  const [weak, setWeak] = useState<WeakWord[]>([]);
  const [allWords, setAllWords] = useState(false);

  useEffect(() => {
    run(api.history).then((h) => h && setHistory(h));
    run(api.weakWords).then((w) => w && setWeak(w));
  }, []);

  if (!history) return <p className="text-muted-foreground">Loading…</p>;
  if (history.sessions === 0) {
    return (
      <>
        <PageHead title="Progress" />
        <EmptyState icon={<TrendingUp />} title="Nothing to show yet">
          <p className="m-0 max-w-sm text-muted-foreground">After your first recording, the sounds and patterns you mix up most are counted here.</p>
        </EmptyState>
      </>
    );
  }
  const sounds = history.categories.pronunciation ?? [];
  const grammar = history.categories.grammar ?? [];

  return (
    <>
      <PageHead title="Progress">
        Across {plural(history.sessions, "recording")}
        {history.dismissed ? `, not counting ${plural(history.dismissed, "false alarm")} you marked` : ""}.
      </PageHead>

      <div className="grid gap-10">
        <section aria-labelledby="queue-title">
          <SectionLabel>
            <span id="queue-title">Words to practice</span>
          </SectionLabel>
          {weak.length === 0 ? (
            <p className="m-0 text-muted-foreground">Nothing outstanding: every recent word has passed.</p>
          ) : (
            <ul className="surface m-0 list-none divide-y divide-border p-0">
              {(allWords ? weak : weak.slice(0, 6)).map((w) => (
                <li key={w.target}>
                  <button
                    type="button"
                    onClick={() => navigate("practice", undefined, { w: w.target })}
                    className="flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors first:rounded-t-[var(--radius-card)] last:rounded-b-[var(--radius-card)] hover:bg-accent"
                  >
                    <span className="min-w-0 flex-1 truncate font-display text-lg">{w.target}</span>
                    <span className="text-sm text-muted-foreground">
                      {w.mistakes}× missed{w.best !== null ? ` · best ${w.best}` : ""}
                    </span>
                    <ArrowRight className="size-4 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {weak.length > 6 && (
            <Button variant="link" className="mt-2 px-0" onClick={() => setAllWords(!allWords)}>
              {allWords ? "Show fewer" : `Show all ${weak.length} words`}
            </Button>
          )}
        </section>

        <div className="grid gap-10 md:grid-cols-2">
          <section aria-labelledby="sounds-title">
            <SectionLabel>
              <span id="sounds-title">Sounds you mix up</span>
            </SectionLabel>
            {sounds.length ? <Bars items={sounds} tone="alert" /> : <p className="m-0 text-muted-foreground">No pronunciation issues yet.</p>}
          </section>
          <section aria-labelledby="grammar-title">
            <SectionLabel>
              <span id="grammar-title">Grammar patterns</span>
            </SectionLabel>
            {grammar.length ? <Bars items={grammar} tone="mint" /> : <p className="m-0 text-muted-foreground">No grammar issues yet.</p>}
          </section>
        </div>
      </div>
    </>
  );
}
