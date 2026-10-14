import { AlertTriangle, FileText } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { FindingCard } from "@/components/FindingCard";
import { EmptyState, PageHead, SectionLabel } from "@/components/PageHead";
import { Transcript } from "@/components/Transcript";
import { api } from "@/api";
import { useAction, useEngine } from "@/engine";
import { fmtDate, fmtDuration, plural } from "@/format";
import { navigate } from "@/router";
import type { AnalysisResult, Feedback, Span } from "@/types";

function summary(pron: number, gram: number): string {
  const total = pron + gram;
  if (total === 0) return "Nothing to fix. Nicely done.";
  const parts = [pron && plural(pron, "sound"), gram && plural(gram, "sentence")].filter(Boolean);
  return `${parts.join(" and ")} to work on.`;
}

export function Report({ id }: { id?: string }) {
  const { state } = useEngine();
  const run = useAction();
  const [sessionId, setSessionId] = useState<string | undefined>(id);
  const [data, setData] = useState<{ result: AnalysisResult; feedback: Feedback } | null>(null);
  const [missing, setMissing] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const cards = useRef(new Map<number, HTMLElement>());

  // No id → show the latest session.
  useEffect(() => {
    if (id) setSessionId(id);
    else run(api.sessions).then((s) => {
      const done = s?.filter((x) => !x.pending && !x.unanalyzed) ?? [];
      if (done.length) setSessionId(done[0].id);
      else setMissing(true);
    });
  }, [id, state.lastAnalysis?.seq]);

  useEffect(() => {
    if (!sessionId) return;
    setData(null);
    run(() => api.session(sessionId)).then((d) => {
      if (!d) return setMissing(true);
      setData(d);
      const first = d.result.findings.findIndex((_, i) => d.feedback[String(i)] !== "dismissed");
      setSelected(first >= 0 ? first : null);
    });
  }, [sessionId]);

  const groups = useMemo(() => {
    if (!data) return [];
    const order = ["pronunciation", "grammar"];
    const names = Array.from(new Set(data.result.findings.map((f) => f.analyzer))).sort(
      (a, b) => (order.indexOf(a) + 1 || 9) - (order.indexOf(b) + 1 || 9),
    );
    return names.map((name) => ({
      name,
      items: data.result.findings.map((f, i) => ({ f, i })).filter(({ f }) => f.analyzer === name),
    }));
  }, [data]);

  if (missing && !data) {
    return (
      <EmptyState icon={<FileText />} title="No reports yet">
        <p className="m-0 max-w-sm text-muted-foreground">
          Press record in the sky and talk for a minute. Your report opens here when the analysis is done.
        </p>
      </EmptyState>
    );
  }
  if (!data || !sessionId) return <p className="text-muted-foreground">Loading the report…</p>;

  const { result, feedback } = data;
  const dismissed = (i: number) => feedback[String(i)] === "dismissed";
  const active = result.findings.filter((_, i) => !dismissed(i));
  const count = (name: string) => active.filter((f) => f.analyzer === name).length;

  const toggleDismiss = async (index: number) => {
    const next = await run(() => api.feedback(sessionId, index, dismissed(index) ? null : "dismissed"));
    if (next) setData({ result, feedback: next });
  };

  const pick = (index: number) => {
    setSelected(index);
    cards.current.get(index)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const practice = (index: number) => (text: string, span?: Span | null) => {
    const f = result.findings[index];
    navigate("practice", undefined, {
      w: text,
      s: sessionId,
      t: span ? `${span[0]}-${span[1]}` : undefined,
      ipa: f.analyzer === "pronunciation" ? f.expected : undefined,
    });
  };

  return (
    <>
      <PageHead
        title={summary(count("pronunciation"), count("grammar"))}
        actions={
          <>
            {result.analyzers.includes("pronunciation") && <Badge variant="alert">{plural(count("pronunciation"), "sound")}</Badge>}
            {result.analyzers.includes("grammar") && <Badge variant="mint">{plural(count("grammar"), "grammar issue")}</Badge>}
          </>
        }
      >
        {fmtDate(result.created)} · {fmtDuration(result.duration)} · {plural(result.sentences.length, "sentence")}
      </PageHead>

      <section className="surface mb-10 p-5 sm:p-7" aria-labelledby="said-title">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 id="said-title" className="eyebrow m-0">
            What you said
          </h2>
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span className="underline decoration-alert decoration-wavy underline-offset-4">sound</span>
            <span className="underline decoration-mint decoration-solid underline-offset-4">grammar</span>
          </div>
        </div>
        <Transcript result={result} feedback={feedback} selected={selected} onSelect={pick} />
        <p className="mt-4 mb-0 text-xs text-muted-foreground">Select an underlined word to jump to it below.</p>
      </section>

      {groups.map(({ name, items }) => (
        <section key={name} className="mb-10" aria-label={name}>
          <SectionLabel>
            {name === "pronunciation" ? "Sounds" : name[0].toUpperCase() + name.slice(1)} · {items.length}
          </SectionLabel>
          <div className="grid gap-4">
            {items.map(({ f, i }) => (
              <FindingCard
                key={i}
                ref={(el) => {
                  if (el) cards.current.set(i, el);
                  else cards.current.delete(i);
                }}
                finding={f}
                sessionId={sessionId}
                sentenceSpan={result.sentence_spans?.[f.segment_index]}
                selected={selected === i}
                dismissed={dismissed(i)}
                onSelect={() => setSelected(i)}
                onToggleDismiss={() => toggleDismiss(i)}
                onPractice={practice(i)}
              />
            ))}
          </div>
        </section>
      ))}

      {result.warnings.length > 0 && (
        <Collapsible className="surface p-5" defaultOpen={result.warnings.some((w) => w.includes("was skipped"))}>
          <CollapsibleTrigger className="flex w-full items-center gap-2 text-left text-sm font-semibold text-muted-foreground">
            <AlertTriangle className="size-4 text-alert-ink" /> {plural(result.warnings.length, "note")} about this analysis
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-3 mb-0 text-sm text-muted-foreground">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  );
}
