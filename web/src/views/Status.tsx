import { ChevronRight, Cpu, Keyboard, Mic, Puzzle } from "lucide-react";
import { useEffect, useState } from "react";
import { LICENSE_NAME, SOURCE_URL } from "../about";
import { api } from "../api";
import { AnalyzerToggles } from "../components/AnalyzerToggles";
import { EngineCard } from "../components/EngineCard";
import { MicSelect } from "../components/MicSelect";
import { ProfileCard } from "../components/ProfileCard";
import { SavedMark, useSaved } from "../components/Saved";
import { VoiceSelect } from "../components/VoiceSelect";
import { useAction, useEngine } from "../engine";
import type { ServerInfo, Status as StatusData } from "../types";

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

function LocalChip({ show }: { show: boolean }) {
  return show ? <span className="chip">on this computer</span> : null;
}

export function Status() {
  const { state } = useEngine();
  const run = useAction();
  const saved = useSaved();
  const [status, setStatus] = useState<StatusData | null>(null);
  const [analyzers, setAnalyzers] = useState<string[]>([]);
  const [server, setServer] = useState<ServerInfo | null>(null);

  const remote = state.engineMode?.mode === "remote";

  useEffect(() => {
    run(api.status).then((s) => s && setStatus(s));
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, []);
  // In client mode, offer only the checks the server can run.
  useEffect(() => {
    if (remote) run(() => api.remote(true)).then((r) => r && setServer(r.server));
    else setServer(null);
  }, [remote]);

  const triggers = state.triggers ?? status?.triggers;
  const hw = status?.hardware;
  // In client mode the server does the analysis: only this computer's own drivers matter.
  const kinds = remote ? ["capture", "triggers"] : Object.keys(KIND_LABELS);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>
            {remote
              ? "This computer records; a speakcheck server does the analysis."
              : "Recording, models, and where analysis runs."}{" "}
            <span className="faint">Changes are saved and applied right away.</span>
          </p>
        </div>
      </div>
      <div className="grid-2">
        <div className="stack">
          <div className="card">
            <div className="card-title">
              <Mic size={18} color="var(--accent)" />
              <h2>Recording</h2>
              <LocalChip show={remote} />
            </div>
            <dl className="kv">
              <dt>Microphone</dt>
              <dd className="field-row">
                <MicSelect onSaved={() => saved.flash("mic")} />
                <SavedMark show={saved.is("mic")} />
              </dd>
              <dt>Reference voice</dt>
              <dd className="field-row">
                <VoiceSelect onSaved={() => saved.flash("voice")} />
                <SavedMark show={saved.is("voice")} />
              </dd>
              <dt>Check for</dt>
              <dd className="field-row" style={{ alignItems: "flex-start" }}>
                <AnalyzerToggles
                  value={analyzers}
                  available={remote && server ? server.analyzers : undefined}
                  onChange={async (next) => {
                    setAnalyzers(next);
                    if (await run(() => api.saveSettings({ analyzers: next }))) saved.flash("analyzers");
                  }}
                />
                <SavedMark show={saved.is("analyzers")} />
              </dd>
            </dl>
          </div>
          <div className="card">
            <div className="card-title">
              <Keyboard size={18} color="var(--accent)" />
              <h2>Shortcuts</h2>
              <LocalChip show={remote} />
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
          {!remote && <ProfileCard />}
        </div>
      </div>

      <details className="card diagnostics">
        <summary>
          <ChevronRight size={18} className="diagnostics-chevron" />
          <h2>Diagnostics</h2>
          <span className="faint">{remote ? "drivers on this computer" : "hardware and drivers"}</span>
        </summary>
        <div className="grid-2" style={{ marginTop: 14 }}>
          {!remote && (
            <div>
              <div className="card-title">
                <Cpu size={18} color="var(--accent)" />
                <h3>Hardware</h3>
              </div>
              <dl className="kv">
                <dt>Graphics card</dt>
                <dd>
                  {hw
                    ? hw.gpu
                      ? `${hw.gpu.name}${hw.gpu.vram_gb ? `, ${hw.gpu.vram_gb.toFixed(0)} GB` : ""}` +
                        (hw.gpu.backend ? ` (${hw.gpu.backend.toUpperCase()})` : " (not usable for the models here)")
                      : "none: models run on the CPU"
                    : "…"}
                </dd>
                <dt>Processor</dt>
                <dd>{hw ? `${hw.cpu} (${hw.cores} threads)` : "…"}</dd>
                <dt>Memory</dt>
                <dd>{hw ? `${hw.ram_gb.toFixed(0)} GB` : "…"}</dd>
              </dl>
              {hw?.notes.map((n) => (
                <p key={n} className="error-text">
                  {n}
                </p>
              ))}
            </div>
          )}
          <div>
            <div className="card-title">
              <Puzzle size={18} color="var(--accent)" />
              <h3>Drivers</h3>
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
              <p className="muted" style={{ fontSize: "0.85rem" }}>
                Speech recognition, sounds, grammar and voices run on the server.
              </p>
            )}
            <p className="faint" style={{ fontSize: "0.85rem" }}>
              ★ in use · ✗ unavailable (hover for why). Change drivers in <code>config.toml</code> in the speakcheck
              folder (see <code>config.example.toml</code>).
            </p>
          </div>
        </div>
        <p className="faint" style={{ marginBottom: 0, fontSize: "0.85rem" }}>
          speakcheck is free software under the {LICENSE_NAME} license:{" "}
          <a href={SOURCE_URL} target="_blank" rel="noreferrer">
            source code
          </a>
          .
        </p>
      </details>
    </>
  );
}
