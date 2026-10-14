import { ArrowRight, AudioLines, FileAudio, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, PageHead, SectionLabel } from "@/components/PageHead";
import { ProgressSteps } from "@/components/ProgressSteps";
import { Shortcut, useShortcutsActive } from "@/components/Shortcut";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { fmtDate, fmtDuration, plural } from "@/format";
import { cn } from "@/lib/utils";
import { navigate } from "@/router";
import type { SessionSummary, WeakWord } from "@/types";

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Counts({ s }: { s: SessionSummary }) {
  const pron = s.counts.pronunciation ?? 0;
  const gram = s.counts.grammar ?? 0;
  return (
    <span className="flex flex-wrap gap-1.5">
      <Badge variant={pron ? "alert" : "muted"}>{plural(pron, "sound")}</Badge>
      <Badge variant={gram ? "mint" : "muted"}>{plural(gram, "grammar issue")}</Badge>
    </span>
  );
}

export function Home() {
  const { state } = useEngine();
  const run = useAction();
  const shortcuts = useShortcutsActive();
  const [analyzers, setAnalyzers] = useState<string[]>(["pronunciation", "grammar"]);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [weak, setWeak] = useState<WeakWord[]>([]);
  const [over, setOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    run(api.settings).then((s) => s && setAnalyzers(s.analyzers.filter((a) => a !== "practice")));
  }, []);
  useEffect(() => {
    run(api.sessions).then((s) => s && setSessions(s));
    run(api.weakWords).then((w) => w && setWeak(w));
  }, [state.lastAnalysis?.seq, state.sessionsVersion]);

  const upload = (file: File | undefined) => file && run(() => api.upload(file, analyzers));
  const analyzing = state.job?.name === "analysis";
  const done = sessions?.filter((s) => !s.pending) ?? [];
  const waiting = sessions?.filter((s) => s.pending).length ?? 0;
  const [last, ...recent] = done;

  return (
    <>
      <PageHead title={<>{greeting()}.</>}>
        {shortcuts ? (
          <>
            Press record in the sky, or <Shortcut action="toggle_recording" /> from any app, and talk for a minute or two.
          </>
        ) : (
          "Press record in the sky and talk for a minute or two. When you stop, speakcheck finds what to work on."
        )}
      </PageHead>

      {analyzing && (
        <section className="surface mb-8 p-5" aria-label="Analyzing">
          <SectionLabel>Analyzing your recording</SectionLabel>
          <ProgressSteps stages={state.job!.stages} />
        </section>
      )}

      {waiting > 0 && (
        <p className="mb-8 rounded-xl border border-dashed border-primary/40 bg-primary/5 px-4 py-3 text-sm">
          {plural(waiting, "recording")} waiting for the server. {waiting === 1 ? "It's" : "They're"} analyzed as soon as it's back.
        </p>
      )}

      {sessions !== null && done.length === 0 && !analyzing ? (
        <EmptyState icon={<AudioLines />} title="Your first recording">
          <p className="m-0 max-w-sm text-muted-foreground">
            Read a few sentences aloud or talk about your day. Your report, with the sounds and sentences to work on, appears
            here.
          </p>
        </EmptyState>
      ) : (
        last && (
          <section className="mb-10" aria-labelledby="last-title">
            <SectionLabel>Last session</SectionLabel>
            <button
              type="button"
              id="last-title"
              onClick={() => navigate("report", last.id)}
              className="surface group grid w-full gap-3 p-5 text-left transition-shadow hover:shadow-md sm:grid-cols-[1fr_auto] sm:items-center"
            >
              <span className="min-w-0">
                <span className="block text-sm text-muted-foreground">
                  {fmtDate(last.created)} · {fmtDuration(last.duration ?? 0)}
                </span>
                <span className="mt-1 block truncate font-display text-xl font-light">“{last.preview || "…"}”</span>
                <span className="mt-3 block">
                  <Counts s={last} />
                </span>
              </span>
              <span className="inline-flex items-center gap-1 font-semibold text-link">
                Open report <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
              </span>
            </button>
          </section>
        )
      )}

      {weak.length > 0 && (
        <section className="mb-10" aria-labelledby="weak-title">
          <SectionLabel aside={<Button variant="link" size="sm" onClick={() => navigate("practice")}>Practice all</Button>}>
            <span id="weak-title">Words to work on</span>
          </SectionLabel>
          <ul className="surface m-0 list-none divide-y divide-border p-0">
            {weak.slice(0, 5).map((w) => (
              <li key={w.target}>
                <button
                  type="button"
                  onClick={() => navigate("practice", undefined, { w: w.target })}
                  className="flex w-full items-center gap-4 px-5 py-3.5 text-left transition-colors first:rounded-t-[var(--radius-card)] last:rounded-b-[var(--radius-card)] hover:bg-accent"
                >
                  <span className="min-w-0 flex-1 truncate font-display text-lg">{w.target}</span>
                  <span className="text-sm text-muted-foreground">
                    {w.mistakes}× missed{w.best !== null ? ` · best ${w.best}` : ""}
                  </span>
                  <ArrowRight className="size-4 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {recent.length > 0 && (
        <section className="mb-10" aria-labelledby="recent-title">
          <SectionLabel aside={<Button variant="link" size="sm" onClick={() => navigate("history")}>All sessions</Button>}>
            <span id="recent-title">Earlier</span>
          </SectionLabel>
          <ul className="m-0 grid list-none gap-2 p-0">
            {recent.slice(0, 3).map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => navigate("report", s.id)}
                  className="flex w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-accent"
                >
                  <span className="w-32 shrink-0 text-sm text-muted-foreground">{fmtDate(s.created)}</span>
                  <span className="min-w-0 flex-1 basis-40 truncate">{s.preview || "…"}</span>
                  <Counts s={s} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="file-title">
        <SectionLabel>
          <span id="file-title">Analyze a file</span>
        </SectionLabel>
        <div
          role="button"
          tabIndex={0}
          aria-label="Choose or drop an audio file to analyze"
          onClick={() => fileInput.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), fileInput.current?.click())}
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
          className={cn(
            "flex cursor-pointer flex-wrap items-center justify-center gap-3 rounded-[var(--radius-card)] border-2 border-dashed px-6 py-7 text-center text-muted-foreground transition-colors",
            over ? "border-primary bg-primary/8 text-foreground" : "border-border hover:border-primary/50 hover:bg-card",
          )}
        >
          {over ? <Upload className="size-5" /> : <FileAudio className="size-5" />}
          <span>
            <b className="text-foreground">Choose an audio file</b> or drop it here (mp3, wav, m4a…)
          </span>
        </div>
        <input ref={fileInput} type="file" accept="audio/*,video/*" hidden onChange={(e) => upload(e.target.files?.[0])} />
      </section>
    </>
  );
}
