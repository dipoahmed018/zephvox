import { AudioWaveform, FileText, History as HistoryIcon, Mic, Settings, Target, TrendingUp, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { api } from "./api";
import { LevelMeter } from "./components/LevelMeter";
import { Notices } from "./components/Notices";
import { Shortcut, useShortcutsActive } from "./components/Shortcut";
import { useAction, useEngine } from "./engine";
import { fmtDuration } from "./format";
import { navigate, useRoute, type View } from "./router";
import { History } from "./views/History";
import { Home } from "./views/Home";
import { Practice } from "./views/Practice";
import { Progress } from "./views/Progress";
import { Report } from "./views/Report";
import { Status } from "./views/Status";

const NAV: { view: View; label: string; icon: typeof Mic }[] = [
  { view: "home", label: "Record", icon: Mic },
  { view: "report", label: "Report", icon: FileText },
  { view: "practice", label: "Practice", icon: Target },
  { view: "history", label: "History", icon: HistoryIcon },
  { view: "progress", label: "Progress", icon: TrendingUp },
  { view: "status", label: "Settings", icon: Settings },
];

export function App() {
  const route = useRoute();
  const { state } = useEngine();
  const run = useAction();
  const shortcuts = useShortcutsActive();
  const seen = useRef(state.lastAnalysis?.seq ?? 0);

  // A finished analysis (started from here, a shortcut or the CLI) opens its report.
  useEffect(() => {
    const a = state.lastAnalysis;
    if (a && a.seq !== seen.current) {
      seen.current = a.seq;
      if (route.view !== "practice") navigate("report", a.sessionId);
    }
  }, [state.lastAnalysis]);

  const rec = state.recording;

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">
          <span className="brand-mark">
            <AudioWaveform size={20} strokeWidth={2.4} />
          </span>
          speakcheck
        </div>
        {NAV.map(({ view, label, icon: Icon }) => (
          <button
            key={view}
            className={`nav-item${route.view === view ? " active" : ""}`}
            aria-current={route.view === view ? "page" : undefined}
            onClick={() => navigate(view)}
          >
            <Icon size={19} />
            <span className="nav-label">{label}</span>
          </button>
        ))}
        <div className="sidebar-foot">Runs on your computer. Nothing leaves it.</div>
      </nav>

      <div className="main">
        <header className="topbar">
          <span className="conn" title={state.connected ? "Connected to the engine" : "Reconnecting to the engine…"}>
            <span className={`dot${state.connected ? " on" : ""}`} />
            {state.connected ? "Engine ready" : "Connecting…"}
          </span>
          <span className="spacer" />
          {rec ? (
            <span className="rec-pill" role="status">
              <span className="rec-dot" />
              {rec.mode === "practice" ? "Practice" : "Recording"} {fmtDuration(rec.elapsed)}
              <LevelMeter levels={state.levels} bars={12} compact />
              <button className="btn ghost small" aria-label="Cancel recording" onClick={() => run(api.cancel)}>
                <X size={14} />
              </button>
            </span>
          ) : (
            shortcuts && (
            <span className="shortcut-hint row muted" style={{ fontSize: "0.85rem" }}>
              Record <Shortcut action="toggle_recording" />
              <span style={{ width: 8 }} />
              Practice <Shortcut action="practice_attempt" />
            </span>
            )
          )}
        </header>

        <main className="content">
          {route.view === "home" && <Home />}
          {route.view === "report" && <Report id={route.id} />}
          {route.view === "practice" && <Practice route={route} />}
          {route.view === "history" && <History />}
          {route.view === "progress" && <Progress />}
          {route.view === "status" && <Status />}
        </main>
      </div>
      <Notices />
    </div>
  );
}
