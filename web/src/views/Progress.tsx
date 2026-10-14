import { TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction } from "../engine";
import { navigate } from "../router";
import type { History, WeakWord } from "../types";

function Bars({ items, color }: { items: [string, number][]; color?: "amber" }) {
  const max = Math.max(1, ...items.map(([, n]) => n));
  return (
    <div className="bars">
      {items.map(([label, n]) => (
        <div className="bar" key={label}>
          <span className={color ? "" : "ipa"}>{label}</span>
          <div className="track">
            <div className={`fill${color ? ` ${color}` : ""}`} style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className="num">{n}</span>
        </div>
      ))}
    </div>
  );
}

export function Progress() {
  const run = useAction();
  const [history, setHistory] = useState<History | null>(null);
  const [weak, setWeak] = useState<WeakWord[]>([]);

  useEffect(() => {
    run(api.history).then((h) => h && setHistory(h));
    run(api.weakWords).then((w) => w && setWeak(w));
  }, []);

  if (!history) return <p className="muted">Loading…</p>;
  if (history.sessions === 0) {
    return (
      <div className="card empty">
        <TrendingUp size={36} />
        <p>Your progress shows up after your first analyzed recording.</p>
      </div>
    );
  }
  const sounds = history.categories.pronunciation ?? [];
  const grammar = history.categories.grammar ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Progress</h1>
          <p>
            Across {history.sessions} recording{history.sessions === 1 ? "" : "s"}
            {history.dismissed ? ` · ${history.dismissed} false alarm${history.dismissed === 1 ? "" : "s"} ignored` : ""}
          </p>
        </div>
      </div>
      <div className="grid-2">
        <div className="card">
          <h2 style={{ marginBottom: 14 }}>Words to practise</h2>
          {weak.length === 0 ? (
            <p className="muted">Nothing outstanding — all recent words passed.</p>
          ) : (
            <ul className="queue">
              {weak.map((w) => (
                <li key={w.target}>
                  <button onClick={() => navigate("practice", undefined, { w: w.target })}>
                    <span>{w.target}</span>
                    <span className="faint">
                      {w.mistakes}× missed{w.best !== null ? ` · best ${w.best}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="stack">
          <div className="card">
            <h2 style={{ marginBottom: 14 }}>Sounds you mix up</h2>
            {sounds.length ? <Bars items={sounds} /> : <p className="muted">No pronunciation issues yet.</p>}
          </div>
          <div className="card">
            <h2 style={{ marginBottom: 14 }}>Grammar patterns</h2>
            {grammar.length ? <Bars items={grammar} color="amber" /> : <p className="muted">No grammar issues yet.</p>}
          </div>
        </div>
      </div>
    </>
  );
}
