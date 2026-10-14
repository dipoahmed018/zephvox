import { Cpu, Keyboard, Mic, Puzzle } from "lucide-react";
import { useEffect, useState } from "react";
import { LICENSE_NAME, SOURCE_URL } from "../about";
import { api } from "../api";
import { AnalyzerToggles } from "../components/AnalyzerToggles";
import { EngineCard } from "../components/EngineCard";
import { MicSelect } from "../components/MicSelect";
import { ProfileCard } from "../components/ProfileCard";
import { VoiceSelect } from "../components/VoiceSelect";
import { useAction, useEngine } from "../engine";
import type { Status as StatusData } from "../types";

const ACTION_LABELS: Record<string, string> = {
  toggle_recording: "Start / stop recording",
  practice_attempt: "Record a practice attempt",
  cancel: "Cancel recording",
};

const KIND_LABELS: Record<string, string> = {
  capture: "Microphone",
  stt: "Speech-to-text",
  g2p: "Expected sounds",
  phonemes: "Heard sounds",
  llm: "Grammar model",
  tts: "Reference voice",
  triggers: "Shortcuts",
};

export function Status() {
  const { state } = useEngine();
  const run = useAction();
  const [status, setStatus] = useState<StatusData | null>(null);
  const [analyzers, setAnalyzers] = useState<string[]>([]);

  useEffect(() => {
    run(api.status).then((s) => s && setStatus(s));
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, []);

  const triggers = state.triggers ?? status?.triggers;
  const gpu = status?.doctor.system.gpu;
  const remote = state.engineMode?.mode === "remote";
  // In client mode the server does the analysis: only this computer's own drivers matter here.
  const kinds = remote ? ["capture", "triggers"] : Object.keys(KIND_LABELS);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings & status</h1>
          <p>
            {state.engineMode?.mode === "remote"
              ? "This computer records; a speakcheck server does the analysis."
              : "What speakcheck is using on this computer."}
          </p>
        </div>
      </div>
      <div className="grid-2">
        <div className="stack">
          <div className="card">
            <div className="card-title">
              <Mic size={18} color="var(--accent)" />
              <h2>Recording</h2>
            </div>
            <dl className="kv">
              <dt>Microphone</dt>
              <dd>
                <MicSelect />
              </dd>
              <dt>Reference voice</dt>
              <dd>
                <VoiceSelect />
              </dd>
              <dt>Check for</dt>
              <dd>
                <AnalyzerToggles
                  value={analyzers}
                  onChange={(next) => {
                    setAnalyzers(next);
                    run(() => api.saveSettings({ analyzers: next }));
                  }}
                />
              </dd>
            </dl>
          </div>
          <div className="card">
            <div className="card-title">
              <Keyboard size={18} color="var(--accent)" />
              <h2>Shortcuts</h2>
            </div>
            {triggers ? (
              <>
                <dl className="kv">
                  {Object.entries(triggers.bindings ?? {}).map(([action, combo]) => (
                    <div key={action} style={{ display: "contents" }}>
                      <dt>{ACTION_LABELS[action] ?? action}</dt>
                      <dd className="row" style={{ gap: 4 }}>
                        {combo.split("+").map((k, i) => (
                          <kbd key={i}>{k.trim()}</kbd>
                        ))}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className={triggers.active ? "muted" : ""} style={{ marginBottom: 0 }}>
                  {triggers.active ? (
                    <>
                      <span className="chip success">active</span> via <b>{triggers.driver}</b>. {triggers.description}
                    </>
                  ) : triggers.error ? (
                    <>
                      <span className="chip error">not active</span> {triggers.error}. You can still bind{" "}
                      <code>speakcheck toggle</code> and <code>speakcheck practice</code> in your system's shortcut settings.
                    </>
                  ) : (
                    <span className="muted">Registering shortcuts…</span>
                  )}
                </p>
              </>
            ) : (
              <p className="muted">Loading…</p>
            )}
          </div>
        </div>
        <div className="stack">
          <EngineCard />
          {state.engineMode?.mode !== "remote" && <ProfileCard />}
          <div className="card">
            <div className="card-title">
              <Cpu size={18} color="var(--accent)" />
              <h2>Hardware</h2>
            </div>
            <dl className="kv">
              <dt>Graphics card</dt>
              <dd>{status ? (gpu ? `${gpu.name} (${gpu.backend.toUpperCase()}, ${gpu.vram_gb.toFixed(0)} GB)` : "none — using CPU") : "…"}</dd>
              <dt>Memory</dt>
              <dd>{status ? `${status.doctor.system.ram_gb.toFixed(0)} GB` : "…"}</dd>
            </dl>
          </div>
          <div className="card">
            <div className="card-title">
              <Puzzle size={18} color="var(--accent)" />
              <h2>Drivers</h2>
            </div>
            {status ? (
              <table className="driver-table">
                <tbody>
                  {kinds.map((kind) => {
                    const drivers = status.doctor.providers.filter((p) => p.kind === kind);
                    return (
                      <tr key={kind}>
                        <td>{KIND_LABELS[kind]}</td>
                        <td>
                          <div className="row" style={{ gap: 6 }}>
                            {drivers.map((d) => (
                              <span
                                key={d.name}
                                className={`chip${d.selected ? " teal" : d.available ? "" : " error"}`}
                                title={d.reason || (d.selected ? "in use" : "available")}
                              >
                                {d.selected ? "★ " : d.available ? "" : "✗ "}
                                {d.name}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <p className="muted">Checking drivers…</p>
            )}
            {remote && (
              <p className="muted" style={{ marginBottom: 0, fontSize: "0.85rem" }}>
                Speech recognition, sounds, grammar and voices run on the server.
              </p>
            )}
            <p className="faint" style={{ marginBottom: 0, fontSize: "0.85rem" }}>
              ★ in use · ✗ unavailable (hover for why). Change drivers in <code>config.toml</code> in the speakcheck
              folder (see <code>config.example.toml</code>).
            </p>
            <p className="faint" style={{ marginBottom: 0, fontSize: "0.85rem" }}>
              speakcheck is free software under the {LICENSE_NAME} license:{" "}
              <a href={SOURCE_URL} target="_blank" rel="noreferrer">
                source code
              </a>
              .
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
