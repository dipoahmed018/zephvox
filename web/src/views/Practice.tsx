import { ArrowRight, CheckCircle2, Ear, Lightbulb, LoaderCircle, Play, RotateCcw, Target, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHead, SectionLabel } from "@/components/PageHead";
import { PhoneTiles } from "@/components/PhoneTiles";
import { ScoreRing } from "@/components/ScoreRing";
import { Shortcut, useShortcutsActive } from "@/components/Shortcut";
import { WordInput } from "@/components/WordInput";
import { api, play, speak, urls } from "@/api";
import { useAction, useEngine } from "@/engine";
import { cn } from "@/lib/utils";
import { navigate, type Route } from "@/router";
import type { PracticeAttempt, PracticeStats, WeakWord } from "@/types";

function headline(a: PracticeAttempt): string {
  if (a.status === "no_speech") return "I didn't hear anything.";
  if (a.status === "different_word") return "That sounded like a different word.";
  if (a.passed) return "Passed. Great pronunciation!";
  return a.score >= 60 ? "Close. One sound came out differently." : "Not yet. Listen once more and try again.";
}

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
  const ipa = route.params.get("ipa") ?? (attempt?.words[0]?.accepted[0] ? `/${attempt.words[0].accepted[0]}/` : null);
  const queue = weak ?? [];
  const next = queue.find((w) => w.target.toLowerCase() !== target?.toLowerCase());

  if (!target) {
    return (
      <>
        <PageHead title="Practice">Type any word or sentence, or record yourself first: the words you miss show up here.</PageHead>
        <EmptyState icon={<Target />} title={weak === null ? "Loading…" : "Nothing to practice yet"}>
          <div className="w-full max-w-md">
            <WordInput autoFocus />
          </div>
        </EmptyState>
      </>
    );
  }

  const speakNow = () => run(() => (recording ? api.stop() : api.start("practice")));
  const words = attempt?.words ?? [];
  const firstIssue = words.find((w) => !w.passed);

  return (
    <>
      <PageHead title="Practice">
        Listen, then say it. {shortcuts ? <>Press Say it, or <Shortcut action="practice_attempt" /> from any app.</> : "Press Say it when you're ready."}
      </PageHead>

      <section className="mb-8" aria-label="Choose a word">
        {queue.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2" role="list" aria-label="Words to work on">
            {queue.slice(0, 8).map((w) => {
              const current = w.target.toLowerCase() === target.toLowerCase();
              return (
                <button
                  key={w.target}
                  role="listitem"
                  type="button"
                  aria-current={current || undefined}
                  onClick={() => navigate("practice", undefined, { w: w.target })}
                  className={cn(
                    "h-9 rounded-full border px-4 text-sm font-semibold transition-colors",
                    current ? "border-foreground bg-foreground text-background" : "border-border bg-card hover:bg-accent",
                  )}
                >
                  {w.target}
                </button>
              );
            })}
          </div>
        )}
        <WordInput />
      </section>

      <section className="surface mb-8 grid justify-items-center gap-2 px-6 py-10 text-center" aria-label="The word">
        <h2 className="m-0 font-display text-5xl font-light break-words sm:text-6xl">{target}</h2>
        {ipa && <p className="ipa m-0 text-lg text-muted-foreground">{ipa}</p>}
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Button variant="outline" onClick={() => speak(target)}>
            <Volume2 /> Hear it
          </Button>
          {sessionId && span && (
            <Button
              variant="ghost"
              onClick={() => {
                const [a, b] = span.split("-").map(Number);
                play(urls.clip(sessionId, a, b));
              }}
            >
              <Ear /> How you said it
            </Button>
          )}
          <Button className="lg:hidden" onClick={speakNow} disabled={scoring || state.recording?.mode === "analysis"}>
            {recording ? "Stop" : "Say it"}
          </Button>
        </div>
        {(recording || scoring) && (
          <p className="mt-2 mb-0 flex items-center gap-2 text-sm text-muted-foreground" role="status">
            {scoring ? <LoaderCircle className="size-4 animate-spin" /> : <span className="size-2 animate-pulse rounded-full bg-alert" />}
            {scoring ? "Scoring…" : "Listening. It stops when you stop talking."}
          </p>
        )}
      </section>

      {attempt && (
        <section className="surface mb-8 p-5 sm:p-7 animate-in fade-in slide-in-from-bottom-2" aria-label="Your attempt">
          <div className="mb-5 flex items-center gap-5">
            {attempt.status === "ok" && <ScoreRing score={attempt.score} size={84} />}
            <div className="min-w-0">
              <h2 className="m-0 flex items-center gap-2 font-display text-2xl font-normal">
                {attempt.passed && <CheckCircle2 className="size-6 text-success-ink" />}
                {headline(attempt)}
              </h2>
              {firstIssue?.explanation && attempt.status === "ok" && (
                <p className="mt-1 mb-0 text-muted-foreground">{firstIssue.explanation}</p>
              )}
            </div>
          </div>

          {attempt.status === "ok" &&
            words.map((w, i) => (
              <div key={i} className="mb-3">
                {words.length > 1 && <div className="eyebrow mb-1.5">{w.word}</div>}
                <PhoneTiles phones={w.phones} />
              </div>
            ))}

          {(attempt.status !== "ok" || firstIssue?.tip) && (
            <p className="mt-4 mb-0 flex gap-2.5 rounded-xl bg-primary/8 px-4 py-3 text-sm">
              <Lightbulb className="mt-0.5 size-4 shrink-0 text-link" />
              {attempt.status === "no_speech"
                ? "Try again a little louder or closer to the microphone."
                : attempt.status === "different_word"
                  ? "Listen to the example and try again."
                  : firstIssue?.tip}
            </p>
          )}

          <div className="mt-5 flex flex-wrap gap-2">
            <Button onClick={speakNow} disabled={recording || scoring}>
              <RotateCcw /> Try again
            </Button>
            <Button variant="outline" onClick={() => play(urls.latestAttempt(target))}>
              <Play /> Your attempt
            </Button>
            {next && (
              <Button variant="ghost" onClick={() => navigate("practice", undefined, { w: next.target })}>
                Next: {next.target} <ArrowRight />
              </Button>
            )}
          </div>
        </section>
      )}

      <section aria-labelledby="tries-title">
        <SectionLabel>
          <span id="tries-title">Your tries</span>
        </SectionLabel>
        {stats && stats.attempts > 0 ? (
          <div className="flex flex-wrap items-end gap-6">
            <div className="flex h-16 items-end gap-1" role="img" aria-label={`Last ${Math.min(14, stats.history.length)} scores`}>
              {stats.history.slice(-14).map((h, i) => (
                <span
                  key={i}
                  title={`${h.score}`}
                  className={cn("w-2.5 rounded-full", h.passed ? "bg-success" : "bg-primary/40")}
                  style={{ height: `${Math.max(8, h.score)}%` }}
                />
              ))}
            </div>
            <p className="m-0 text-sm text-muted-foreground">
              {stats.attempts} {stats.attempts === 1 ? "try" : "tries"} · best <b className="text-foreground">{stats.best}</b>
              {stats.passed && " · passed"}
            </p>
          </div>
        ) : (
          <p className="m-0 text-sm text-muted-foreground">No tries yet. Your scores show up here.</p>
        )}
      </section>
    </>
  );
}
