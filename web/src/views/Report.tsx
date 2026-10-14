import { AlertTriangle, FileText, MousePointerClick } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { FindingCard } from "../components/FindingCard";
import { Transcript } from "../components/Transcript";
import { useAction, useEngine } from "../engine";
import { fmtDate, fmtDuration, plural } from "../format";
import { navigate } from "../router";
import type { AnalysisResult, Feedback, Span } from "../types";

export function Report({ id }: { id?: string }) {
  const { state } = useEngine();
  const run = useAction();
  const [sessionId, setSessionId] = useState<string | undefined>(id);
  const [data, setData] = useState<{ result: AnalysisResult; feedback: Feedback } | null>(null);
  const [missing, setMissing] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  // No id → show the latest session.
  useEffect(() => {
    if (id) setSessionId(id);
    else run(api.sessions).then((s) => (s && s.length ? setSessionId(s[0].id) : setMissing(true)));
  }, [id, state.lastAnalysis?.seq]);

  useEffect(() => {
    if (!sessionId) return;
    setData(null);
    run(() => api.session(sessionId)).then((d) => {
      if (!d) return setMissing(true);
      setData(d);
      setSelected(d.result.findings.findIndex((_, i) => d.feedback[String(i)] !== "dismissed"));
    });
  }, [sessionId]);

  const groups = useMemo(() => {
    if (!data) return [];
    const names = Array.from(new Set(data.result.findings.map((f) => f.analyzer)));
    return names.map((name) => ({
      name,
      items: data.result.findings.map((f, i) => ({ f, i })).filter(({ f }) => f.analyzer === name),
    }));
  }, [data]);

  if (missing && !data) {
    return (
      <div className="card empty">
        <FileText size={36} />
        <p>No reports yet. Record yourself on the Home page first.</p>
        <button className="btn primary" onClick={() => navigate("home")}>
          Start recording
        </button>
      </div>
    );
  }
  if (!data || !sessionId) return <p className="muted">Loading report…</p>;

  const { result, feedback } = data;
  const dismissed = (i: number) => feedback[String(i)] === "dismissed";
  const active = result.findings.filter((_, i) => !dismissed(i));
  const count = (name: string) => active.filter((f) => f.analyzer === name).length;
  const current = selected !== null && selected >= 0 ? result.findings[selected] : null;
  const sentenceSpan: Span | undefined = current ? result.sentence_spans?.[current.segment_index] : undefined;

  const toggleDismiss = async (index: number) => {
    const next = await run(() => api.feedback(sessionId, index, dismissed(index) ? null : "dismissed"));
    if (next) setData({ result, feedback: next });
  };

  const practise = (text: string, span?: Span | null) =>
    navigate("practice", undefined, {
      w: text,
      s: sessionId,
      t: span ? `${span[0]}-${span[1]}` : undefined,
      ipa: current?.analyzer === "pronunciation" ? current.expected : undefined,
    });

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Your report</h1>
          <p>
            {fmtDate(result.created)} · {fmtDuration(result.duration)} · {plural(result.sentences.length, "sentence")}
          </p>
        </div>
        <div className="row">
          {result.analyzers.includes("pronunciation") && (
            <span className="chip teal">{plural(count("pronunciation"), "pronunciation issue")}</span>
          )}
          {result.analyzers.includes("grammar") && (
            <span className="chip amber">{plural(count("grammar"), "grammar issue")}</span>
          )}
        </div>
      </div>

      <div className="report">
        <div className="stack">
          <div className="card">
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
              <h2>What you said</h2>
              <div className="legend">
                <span>
                  <i style={{ background: "var(--teal)" }} />
                  Pronunciation
                </span>
                <span>
                  <i style={{ background: "var(--amber)" }} />
                  Grammar
                </span>
              </div>
            </div>
            <Transcript result={result} feedback={feedback} selected={selected} onSelect={setSelected} />
          </div>

          {groups.map(({ name, items }) => (
            <div className="card" key={name}>
              <h2 style={{ marginBottom: 12 }}>{name[0].toUpperCase() + name.slice(1)}</h2>
              <ul className="finding-list">
                {items.map(({ f, i }) => (
                  <li key={i}>
                    <button
                      className={`finding-row${selected === i ? " selected" : ""}${dismissed(i) ? " dismissed" : ""}`}
                      onClick={() => setSelected(i)}
                    >
                      <span className="target">{name === "grammar" ? `“${f.said}”` : f.target}</span>
                      <span className={name === "grammar" ? "" : "ipa muted"}>
                        {name === "grammar" ? `→ “${f.expected}”` : `${f.said} → ${f.expected}`}
                      </span>
                      <span className="meta chip">{dismissed(i) ? "dismissed" : f.category}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {active.length === 0 && (
            <div className="card empty">
              <p>No mistakes found — nicely done!</p>
            </div>
          )}

          {result.warnings.length > 0 && (
            <details className="card">
              <summary className="row muted" style={{ cursor: "pointer" }}>
                <AlertTriangle size={16} color="var(--amber)" /> {plural(result.warnings.length, "note")} about this analysis
              </summary>
              <ul className="muted">
                {result.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <aside className="side-panel">
          {current ? (
            <FindingCard
              finding={current}
              sessionId={sessionId}
              sentenceSpan={sentenceSpan}
              dismissed={dismissed(selected!)}
              onToggleDismiss={() => toggleDismiss(selected!)}
              onPractice={practise}
            />
          ) : (
            <div className="card empty">
              <MousePointerClick size={30} />
              <p>Click a highlighted word to see what went wrong and practise it.</p>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
