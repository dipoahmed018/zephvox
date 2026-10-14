import { AudioLines, FileAudio, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { AnalyzerToggles } from "../components/AnalyzerToggles";
import { LevelMeter } from "../components/LevelMeter";
import { MicSelect } from "../components/MicSelect";
import { ProgressSteps } from "../components/ProgressSteps";
import { RecordButton } from "../components/RecordButton";
import { Shortcut, useShortcutsActive } from "../components/Shortcut";
import { useAction, useEngine } from "../engine";
import { fmtDate, fmtDuration } from "../format";
import { navigate } from "../router";
import type { SessionSummary } from "../types";

export function Home() {
  const { state } = useEngine();
  const run = useAction();
  const shortcuts = useShortcutsActive();
  const [analyzers, setAnalyzers] = useState<string[]>(["pronunciation", "grammar"]);
  const [recent, setRecent] = useState<SessionSummary[]>([]);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, []);

  useEffect(() => {
    run(api.sessions).then((s) => s && setRecent(s.slice(0, 3)));
  }, [state.lastAnalysis?.seq]);

  const rec = state.recording;
  const recordingHere = rec?.mode === "analysis";
  const analyzing = state.job?.name === "analysis";

  const saveAnalyzers = (next: string[]) => {
    setAnalyzers(next);
    run(() => api.saveSettings({ analyzers: next }));
  };

  const onRecord = () => run(() => (recordingHere ? api.stop() : api.start("analysis", analyzers)));

  const upload = (file: File | undefined) => file && run(() => api.upload(file, analyzers));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Let's hear you speak</h1>
          <p>Talk naturally about anything. When you stop, speakcheck finds your mistakes.</p>
        </div>
      </div>

      <div className="card">
        <div className="recorder">
          <RecordButton
            recording={recordingHere}
            level={rec?.level ?? 0}
            onClick={onRecord}
            disabled={rec?.mode === "practice"}
            label={recordingHere ? "Stop recording" : "Start recording"}
          />
          {recordingHere ? (
            <>
              <div className="timer">{fmtDuration(rec.elapsed)}</div>
              <LevelMeter levels={state.levels} />
              <div className="row">
                <button className="btn ghost small" onClick={() => run(api.cancel)}>
                  Discard
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="rec-label">{analyzing ? "Analyzing your last recording…" : "Press to start recording"}</div>
              {shortcuts && (
                <div className="rec-hint row" style={{ justifyContent: "center" }}>
                  or press <Shortcut action="toggle_recording" /> anywhere, even when this page isn't open
                </div>
              )}
            </>
          )}
        </div>
        <div className="row" style={{ justifyContent: "center", marginTop: 18, gap: 14 }}>
          <MicSelect />
          <AnalyzerToggles value={analyzers} onChange={saveAnalyzers} />
        </div>
      </div>

      {state.job && state.job.name === "analysis" && (
        <div className="card">
          <div className="card-title">
            <Sparkles size={18} color="var(--accent)" />
            <h2>Analyzing</h2>
          </div>
          <ProgressSteps stages={state.job.stages} />
        </div>
      )}

      <div className="grid-2" style={{ marginTop: 18 }}>
        <div className="card">
          <div className="card-title">
            <AudioLines size={18} color="var(--accent)" />
            <h2>Recent sessions</h2>
          </div>
          {recent.length === 0 ? (
            <p className="muted">Your reports will show up here.</p>
          ) : (
            <ul className="session-list">
              {recent.map((s) => (
                <li key={s.id}>
                  <button className="finding-row" onClick={() => navigate("report", s.id)}>
                    <span className="grow" style={{ minWidth: 0 }}>
                      <span className="target">{fmtDate(s.created)}</span>
                      <span className="preview" style={{ display: "block" }}>{s.preview || "—"}</span>
                    </span>
                    <span className="meta row" style={{ gap: 6 }}>
                      <span className="chip teal">{s.counts.pronunciation ?? 0}</span>
                      <span className="chip amber">{s.counts.grammar ?? 0}</span>
                      <span className="faint">{fmtDuration(s.duration)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="card-title">
            <FileAudio size={18} color="var(--accent)" />
            <h2>Analyze a file</h2>
          </div>
          <p className="muted" style={{ marginTop: 0 }}>Already have a recording? Drop it here (mp3, wav, m4a, …).</p>
          <div
            className={`dropzone${over ? " over" : ""}`}
            role="button"
            tabIndex={0}
            onClick={() => fileInput.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              upload(e.dataTransfer.files[0]);
            }}
          >
            <FileAudio size={18} /> Choose or drop an audio file
          </div>
          <input ref={fileInput} type="file" accept="audio/*,video/*" hidden onChange={(e) => upload(e.target.files?.[0])} />
        </div>
      </div>
    </>
  );
}
