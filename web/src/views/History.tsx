import { History as HistoryIcon, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAction, useEngine } from "../engine";
import { fmtDate, fmtDuration } from "../format";
import { navigate } from "../router";
import type { SessionSummary } from "../types";

export function History() {
  const { state } = useEngine();
  const run = useAction();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);

  const load = () => run(api.sessions).then((s) => s && setSessions(s));
  useEffect(() => {
    load();
  }, [state.lastAnalysis?.seq, state.sessionsVersion]);

  const remove = async (s: SessionSummary) => {
    if (!window.confirm(`Delete the recording from ${fmtDate(s.created)}? This can't be undone.`)) return;
    await run(() => api.deleteSession(s.id));
    load();
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>History</h1>
          <p>Every recording you've analyzed.</p>
        </div>
      </div>
      {sessions === null ? (
        <p className="muted">Loading…</p>
      ) : sessions.length === 0 ? (
        <div className="card empty">
          <HistoryIcon size={36} />
          <p>No recordings yet.</p>
        </div>
      ) : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.id} className="session-item">
              <div className="grow">
                <div style={{ fontWeight: 600 }}>{fmtDate(s.created)}</div>
                <div className="preview">{s.preview || "—"}</div>
              </div>
              {s.pending ? (
                <span className="chip amber" title="Recorded while the server was unreachable">waiting for the server</span>
              ) : (
                <>
                  <div className="row" style={{ gap: 6 }}>
                    <span className="chip teal" title="Pronunciation issues">{s.counts.pronunciation ?? 0}</span>
                    <span className="chip amber" title="Grammar issues">{s.counts.grammar ?? 0}</span>
                    <span className="faint" style={{ minWidth: 40, textAlign: "right" }}>{fmtDuration(s.duration ?? 0)}</span>
                  </div>
                  <button className="btn small" onClick={() => navigate("report", s.id)}>
                    Open
                  </button>
                </>
              )}
              <button className="btn ghost small danger" aria-label="Delete" onClick={() => remove(s)}>
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
