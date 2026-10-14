import { Moon, Sun, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/api";
import { STAGE_LABELS, useAction, useEngine } from "@/engine";
import { fmtDuration } from "@/format";
import { explainError } from "@/lib/errors";
import { gatesFor } from "@/lib/stages";
import { setTheme, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import type { Route } from "@/router";
import type { PracticeAttempt } from "@/types";
import { RecordButton } from "./RecordButton";
import { Shortcut } from "./Shortcut";
import { WindCanvas, type WindMode } from "./wind/WindCanvas";

function hostOf(url: string | null): string {
  try {
    return url ? new URL(url).host : "your server";
  } catch {
    return url ?? "your server";
  }
}

interface SkyState {
  mode: WindMode;
  title: string;
  detail: string;
  tone: "idle" | "busy" | "rec" | "good" | "bad" | "off";
}

/** One sentence about the attempt, for the status line. */
function attemptDetail(a: PracticeAttempt): string {
  if (a.status === "no_speech") return "Didn't hear anything";
  if (a.status === "different_word") return "Sounded like a different word";
  if (a.passed) return "Passed";
  return a.words.find((w) => !w.passed)?.explanation || "Try again";
}

/**
 * The persistent sky: what the app is doing right now (wind, status and the one primary control),
 * visible from every page. `pane` is the tall left column; `strip` is the compact bar on phones.
 */
export function Sky({ route, variant, className }: { route: Route; variant: "pane" | "strip"; className?: string }) {
  const { state } = useEngine();
  const run = useAction();
  const { dark } = useTheme();
  const [analyzers, setAnalyzers] = useState<string[]>(["pronunciation", "grammar"]);
  const [attempt, setAttempt] = useState<PracticeAttempt | null>(null);

  const rec = state.recording;
  const job = state.job;
  const waiting = Math.max(0, state.pending - (job ? 1 : 0)); // analyses queued behind the running one
  const practicing = route.view === "practice";
  const target = practicing ? state.practiceTarget?.text ?? null : null;

  // The checks that will run decide which gates the analysis shows.
  useEffect(() => {
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, [job?.name === "analysis"]);

  // A practice result colours the sky until the word changes or the page does.
  useEffect(() => {
    const a = state.lastAttempt;
    setAttempt(a && target && a.target.toLowerCase() === target.toLowerCase() ? a : null);
  }, [state.lastAttempt]);
  useEffect(() => {
    setAttempt(null);
  }, [target, practicing]);

  const s: SkyState = (() => {
    if (!state.connected) return { mode: "offline", title: "Connecting", detail: "Waiting for the engine…", tone: "off" };
    // Recording again while the last one is still being analyzed is fine: it joins the queue.
    const behind = state.pending > 0 ? ` · ${state.pending === 1 ? "last one is analyzing" : `${state.pending} analyzing`}` : "";
    if (rec?.mode === "analysis") return { mode: "recording", title: "Recording", detail: fmtDuration(rec.elapsed) + behind, tone: "rec" };
    if (rec?.mode === "practice")
      return { mode: "recording", title: "Listening", detail: "Stops when you stop talking", tone: "rec" };
    if (job?.name === "analysis") {
      const running = [...job.stages].reverse().find((st) => st.state === "running");
      const step = running ? STAGE_LABELS[running.key] ?? running.key : "Getting ready";
      return { mode: "analyzing", title: "Analyzing", detail: step + (waiting ? ` · ${waiting} waiting` : ""), tone: "busy" };
    }
    if (job?.name === "practice") return { mode: "analyzing", title: "Scoring", detail: "One moment", tone: "busy" };
    if (attempt) {
      const ok = attempt.status === "ok";
      return {
        mode: attempt.passed ? "pass" : "miss",
        title: ok ? `“${attempt.target}” ${attempt.score}` : `“${attempt.target}”`,
        detail: attemptDetail(attempt),
        tone: attempt.passed ? "good" : "bad",
      };
    }
    if (target) return { mode: "idle", title: "Ready", detail: `Say “${target}”`, tone: "idle" };
    if (state.analysisError) return { mode: "idle", title: "Couldn't analyze", detail: explainError(state.analysisError).title, tone: "bad" };
    return { mode: "idle", title: "Ready", detail: state.triggers?.active ? "Record from any app" : "Press record to start", tone: "idle" };
  })();

  const gates = job?.name === "analysis" ? gatesFor(job.stages, analyzers) : [];
  const recording = Boolean(rec);
  // Only a lost connection blocks recording: an analysis in progress never does.
  const busy = !state.connected;
  const practiceAction = Boolean(target) && !recording;
  const action = recording
    ? { label: "Stop", run: api.stop, shortcut: rec?.mode === "practice" ? "practice_attempt" : "toggle_recording" }
    : practiceAction
      ? { label: attempt ? "Try again" : "Say it", run: () => api.start("practice"), shortcut: "practice_attempt" }
      : { label: "Record", run: () => api.start("analysis", analyzers), shortcut: "toggle_recording" };
  const onAction = () => run(action.run);
  const remote = state.engineMode?.mode === "remote";

  const pill = (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex max-w-full min-w-0 items-center gap-2 rounded-full border border-border bg-card/85 px-3 py-1.5 text-sm shadow-xs backdrop-blur",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-2 shrink-0 rounded-full",
          s.tone === "rec" && "animate-pulse bg-alert",
          s.tone === "busy" && "animate-pulse bg-primary",
          s.tone === "good" && "bg-success",
          s.tone === "bad" && "bg-alert",
          s.tone === "idle" && "bg-muted-foreground/60",
          s.tone === "off" && "animate-pulse bg-muted-foreground/40",
        )}
      />
      <b className="shrink-0 font-bold whitespace-nowrap">{s.title}</b>
      <span className="truncate text-muted-foreground tabular-nums">{s.detail}</span>
    </div>
  );

  if (variant === "strip") {
    return (
      <div className={cn("relative flex h-16 items-center gap-3 border-b border-border bg-linear-to-b from-sky-a to-sky-b px-4", className)}>
        <div className="absolute inset-0 overflow-hidden">
          <WindCanvas mode={s.mode} level={rec?.level ?? 0} gates={gates} compact />
        </div>
        <div className="relative min-w-0 flex-1">{pill}</div>
        {recording && (
          <Button variant="ghost" size="icon" className="relative" aria-label="Cancel recording" onClick={() => run(api.cancel)}>
            <X />
          </Button>
        )}
        <div className="relative">
          <RecordButton size="sm" recording={recording} level={rec?.level ?? 0} onClick={onAction} disabled={busy && !recording} label={action.label} />
        </div>
      </div>
    );
  }

  return (
    <aside
      aria-label="Recording"
      className={cn("relative flex flex-col overflow-hidden border-r border-border bg-linear-to-b from-sky-a to-sky-b", className)}
    >
      <WindCanvas mode={s.mode} level={rec?.level ?? 0} gates={gates} />

      <div className="relative flex items-center justify-between px-7 pt-6">
        <span className="font-display text-2xl font-light italic">speakcheck</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={dark ? "Use light theme" : "Use dark theme"} onClick={() => setTheme(dark ? "light" : "dark")}>
              {dark ? <Sun /> : <Moon />}
            </Button>
          </TooltipTrigger>
          <TooltipContent>{dark ? "Light theme" : "Dark theme"}</TooltipContent>
        </Tooltip>
      </div>

      <div className="relative flex justify-center px-6 pt-10">{pill}</div>

      <div className="relative grid flex-1 content-center justify-items-center gap-2 px-6 text-center">
        {target && !job && (
          <div className="grid gap-1 animate-in fade-in">
            <span className={cn("font-display text-5xl font-light italic", s.tone === "bad" && "text-alert-ink", s.tone === "good" && "text-success-ink")}>
              {target}
            </span>
          </div>
        )}
        {rec?.mode === "analysis" && (
          <span className="font-display text-6xl font-extralight tabular-nums">{fmtDuration(rec.elapsed)}</span>
        )}
      </div>

      <div className="relative grid justify-items-center gap-3 px-6 pb-8">
        <RecordButton recording={recording} level={rec?.level ?? 0} onClick={onAction} disabled={busy && !recording} label={action.label} />
        <span className="text-base font-bold">{busy && !recording ? s.title : action.label}</span>
        <Shortcut action={action.shortcut} />
        {recording && (
          <Button variant="ghost" size="sm" onClick={() => run(api.cancel)} className="text-muted-foreground">
            Cancel <Shortcut action="cancel" />
          </Button>
        )}
        <p className="m-0 mt-2 max-w-64 text-center text-xs text-muted-foreground">
          {remote ? `Analyzed on ${hostOf(state.engineMode!.url)}. Your history stays here too.` : "Runs on your computer. Nothing leaves it."}
        </p>
      </div>
    </aside>
  );
}
