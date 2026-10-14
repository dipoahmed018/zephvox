import { ArrowRight, CheckCircle2, Ear, LoaderCircle, Lightbulb, Play, Target, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, play, speak, urls } from "../api";
import { LevelMeter } from "../components/LevelMeter";
import { PhoneTiles } from "../components/PhoneTiles";
import { RecordButton } from "../components/RecordButton";
import { ScoreRing } from "../components/ScoreRing";
import { Shortcut, useShortcutsActive } from "../components/Shortcut";
import { useAction, useEngine } from "../engine";
import { navigate, type Route } from "../router";
import type { PracticeAttempt, PracticeStats, WeakWord } from "../types";

export function Practice({ route }: { route: Route }) {
  const { state } = useEngine();
  const run = useAction();
  const shortcuts = useShortcutsActive();
  const [weak, setWeak] = useState<WeakWord[] | null>(null);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null);

  const sessionId = route.params.get("s") ?? undefined;
  const span = route.params.get("t");
  const target = route.params.get("w") ?? weak?.[0]?.target ?? null;

  const refresh = (t: string | null) => {
    run(api.weakWords).then((w) => w && setWeak(w));
    if (t) run(() => api.practiceStats(t)).then((s) => s && setStats(s));
  };

  useEffect(() => {
    setAttempt(null);
    setStats(null);
    if (target) run(() => api.setPracticeTarget(target, sessionId));
    refresh(target);
  }, [target]);

  // A new result for this word arrived from the engine (button or shortcut).
  useEffect(() => {
    const a = state.lastAttempt;
    if (a && target && a.target.toLowerCase() === target.toLowerCase()) {
      setAttempt(a);
      refresh(target);
    }
  }, [state.lastAttempt]);

  const recording = state.recording?.mode === "practice";
  const scoring = state.job?.name === "practice";
  const ipa = route.params.get("ipa") ?? (attempt?.words[0] ? `/${attempt.words[0].accepted[0]}/` : null);
  const queue = weak ?? [];
  const next = queue.find((w) => w.target.toLowerCase() !== target?.toLowerCase());

  if (!target) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>Practice</h1>
            <p>Pick a mistaken word from a report, or record a session first.</p>
          </div>
        </div>
        <div className="card empty">
          <Target size={36} />
          <p>{weak === null ? "Loading…" : "No words to practise yet — your weak words appear here after a recording."}</p>
          <button className="btn primary" onClick={() => navigate("home")}>
            Record yourself
          </button>
        </div>
      </>
    );
  }

  const onSpeak = () => run(() => (recording ? api.stop() : api.start("practice")));
  const words = attempt?.words ?? [];
  const firstIssue = words.find((w) => !w.passed);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Practice</h1>
          <p>Listen, then say it. Keep going until it turns teal.</p>
        </div>
      </div>

      <div className="practice">
        <div className="card">
          <div className="target-word">{target}</div>
          {ipa && <div className="target-ipa ipa">{ipa}</div>}
          <div className="actions" style={{ justifyContent: "center" }}>
            <button className="btn small" onClick={() => speak(target)}>
              <Volume2 size={15} /> Hear it
            </button>
            {sessionId && span && (
              <button
                className="btn small"
                onClick={() => {
                  const [a, b] = span.split("-").map(Number);
                  play(urls.clip(sessionId, a, b));
                }}
              >
                <Ear size={15} /> Your original
              </button>
            )}
          </div>

          <div className="practice-stage">
            <div style={{ justifySelf: "end" }}>{recording && <LevelMeter levels={state.levels} bars={16} />}</div>
            <div style={{ display: "grid", justifyItems: "center", gap: 10 }}>
              <RecordButton
                small
                recording={recording}
                level={state.recording?.level ?? 0}
                onClick={onSpeak}
                disabled={state.recording?.mode === "analysis" || scoring}
                label={recording ? "Stop" : "Speak"}
              />
              <div className="rec-hint">
                {scoring ? (
                  <span className="row">
                    <LoaderCircle size={15} className="spin" /> Scoring…
                  </span>
                ) : recording ? (
                  "Listening — it stops when you stop talking"
                ) : (
                  <span className="row" style={{ justifyContent: "center" }}>
                    {shortcuts ? (
                      <>
                        Click or press <Shortcut action="practice_attempt" />
                      </>
                    ) : (
                      "Click to speak"
                    )}
                  </span>
                )}
              </div>
            </div>
            <div>{attempt && attempt.status === "ok" && <ScoreRing score={attempt.score} size={112} />}</div>
          </div>

          {attempt && (
            <div style={{ marginTop: 10 }}>
              {attempt.status !== "ok" ? (
                <p className="tip">
                  <Lightbulb size={18} />
                  {attempt.status === "no_speech"
                    ? "I didn't hear anything. Try again a little louder or closer to the microphone."
                    : "That sounded like a different word. Listen to the example and try again."}
                </p>
              ) : (
                <>
                  {attempt.passed && (
                    <div className="row" style={{ justifyContent: "center" }}>
                      <span className="passed-badge">
                        <CheckCircle2 size={18} /> Passed — great pronunciation!
                      </span>
                    </div>
                  )}
                  {words.map((w, i) => (
                    <div key={i}>
                      {words.length > 1 && <div className="faint" style={{ textAlign: "center", marginTop: 8 }}>{w.word}</div>}
                      <PhoneTiles phones={w.phones} />
                    </div>
                  ))}
                  {firstIssue && (
                    <div className="stack">
                      <p style={{ textAlign: "center", margin: 0 }}>{firstIssue.explanation}</p>
                      {firstIssue.tip && (
                        <p className="tip">
                          <Lightbulb size={18} /> {firstIssue.tip}
                        </p>
                      )}
                    </div>
                  )}
                </>
              )}
              <div className="actions" style={{ justifyContent: "center" }}>
                <button className="btn small" onClick={() => play(urls.latestAttempt(target))}>
                  <Play size={15} /> Your attempt
                </button>
                <button className="btn small" onClick={onSpeak} disabled={recording || scoring}>
                  Try again
                </button>
                {next && (
                  <button className="btn primary small" onClick={() => navigate("practice", undefined, { w: next.target })}>
                    Next word <ArrowRight size={15} />
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        <aside className="stack">
          <div className="card">
            <h2 style={{ marginBottom: 6 }}>Your attempts</h2>
            {stats && stats.attempts > 0 ? (
              <>
                <p className="muted" style={{ margin: 0 }}>
                  {stats.attempts} tries · best {stats.best}
                </p>
                <div className="attempts" aria-label="Attempt scores">
                  {stats.history.slice(-14).map((h, i) => (
                    <span key={i} className={h.passed ? "pass" : ""} style={{ height: `${Math.max(6, h.score)}%` }} title={`${h.score}`} />
                  ))}
                </div>
              </>
            ) : (
              <p className="muted" style={{ margin: 0 }}>No attempts yet.</p>
            )}
          </div>
          <div className="card">
            <h2 style={{ marginBottom: 10 }}>Words to work on</h2>
            {weak === null ? (
              <p className="muted" style={{ margin: 0 }}>Loading…</p>
            ) : queue.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>Nothing left — everything recent has passed.</p>
            ) : (
              <ul className="queue">
                {queue.map((w) => (
                  <li key={w.target}>
                    <button
                      className={w.target.toLowerCase() === target.toLowerCase() ? "current" : ""}
                      onClick={() => navigate("practice", undefined, { w: w.target })}
                    >
                      <span>{w.target}</span>
                      <span className="faint">{w.best === null ? `${w.mistakes}×` : `best ${w.best}`}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
