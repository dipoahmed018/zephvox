import { Ear, Play, RotateCcw, Target, ThumbsDown, Volume2 } from "lucide-react";
import { forwardRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { play, speak, urls } from "@/api";
import { alignSounds, splitSounds } from "@/lib/align";
import { cn } from "@/lib/utils";
import type { Finding, Span } from "@/types";

interface Props {
  finding: Finding;
  sessionId: string;
  sentenceSpan?: Span;
  selected: boolean;
  dismissed: boolean;
  onSelect: () => void;
  onToggleDismiss: () => void;
  onPractice: (text: string, span?: Span | null) => void;
}

export function correctedSentence(f: Finding): string {
  const i = f.sentence.toLowerCase().indexOf(f.said.toLowerCase());
  if (i < 0) return f.sentence;
  return f.sentence.slice(0, i) + f.expected + f.sentence.slice(i + f.said.length);
}

function Tile({ text, tone }: { text: string; tone: "same" | "good" | "bad" | "gap" }) {
  return (
    <span
      className={cn(
        "ipa grid h-9 min-w-9 place-items-center rounded-lg border px-2",
        tone === "same" && "border-border bg-background",
        tone === "good" && "border-success bg-success/10 font-semibold text-success-ink",
        tone === "bad" && "border-alert bg-alert/12 font-semibold text-alert-ink",
        tone === "gap" && "border-dashed border-alert/70 text-alert-ink",
      )}
    >
      {text}
    </span>
  );
}

/** Expected sounds above what was heard, column by column, with gaps where a sound was missing or extra. */
function SoundCompare({ expected, heard }: { expected: string; heard: string }) {
  const pairs = alignSounds(splitSounds(expected), splitSounds(heard));
  return (
    <div className="overflow-x-auto">
      <div className="inline-grid grid-flow-col grid-rows-2 items-center gap-x-1.5 gap-y-2" style={{ gridTemplateColumns: "auto" }}>
        <span className="eyebrow pr-2">Expected</span>
        <span className="eyebrow pr-2">You said</span>
        {pairs.map(([e, h], i) => {
          const same = e === h;
          return [
            <Tile key={`e${i}`} text={e ?? ""} tone={same ? "same" : e === null ? "gap" : "good"} />,
            <Tile key={`h${i}`} text={h ?? "—"} tone={same ? "same" : h === null ? "gap" : "bad"} />,
          ];
        })}
      </div>
    </div>
  );
}

export const FindingCard = forwardRef<HTMLElement, Props>(function FindingCard(
  { finding: f, sessionId, sentenceSpan, selected, dismissed, onSelect, onToggleDismiss, onPractice },
  ref,
) {
  const pron = f.analyzer === "pronunciation";
  const fixed = pron ? f.sentence : correctedSentence(f);
  return (
    <article
      ref={ref}
      onClick={onSelect}
      aria-current={selected || undefined}
      className={cn(
        "surface scroll-mt-28 p-5 transition-[box-shadow,border-color,opacity]",
        selected && (pron ? "border-alert/70 ring-1 ring-alert/40" : "border-mint/80 ring-1 ring-mint/50"),
        dismissed && "opacity-60",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <Badge variant={pron ? "alert" : "mint"}>{pron ? "Sound" : "Grammar"}</Badge>
        <span className="truncate text-xs text-muted-foreground">{dismissed ? "Marked as not a mistake" : f.category}</span>
      </div>

      {pron ? (
        <>
          <h3 className="m-0 mb-3 font-display text-2xl font-normal">
            {f.target} <span className="ipa align-middle text-sm text-muted-foreground">{f.expected}</span>
          </h3>
          <SoundCompare expected={f.expected} heard={f.said} />
        </>
      ) : (
        <div className="mb-1 grid gap-1">
          <p className="m-0 font-display text-xl font-light text-muted-foreground line-through decoration-alert/70">“{f.said}”</p>
          <p className="m-0 font-display text-xl font-normal">“{f.expected}”</p>
        </div>
      )}

      {f.explanation && <p className="mt-3 mb-0 rounded-xl bg-primary/8 px-3 py-2 text-sm">{f.explanation}</p>}
      <p className="mt-3 mb-0 text-sm text-muted-foreground italic">“{fixed}”</p>

      <div className="mt-4 flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <Button size="sm" onClick={() => onPractice(pron ? f.target : fixed, pron ? f.time_span : sentenceSpan)}>
          <Target /> Practice {pron ? "this word" : "this sentence"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => speak(pron ? f.target : fixed)}>
          <Volume2 /> Hear it
        </Button>
        {pron && f.time_span && (
          <Button size="sm" variant="ghost" onClick={() => play(urls.clip(sessionId, f.time_span![0], f.time_span![1]))}>
            <Ear /> Your word
          </Button>
        )}
        {sentenceSpan && (
          <Button size="sm" variant="ghost" onClick={() => play(urls.clip(sessionId, sentenceSpan[0], sentenceSpan[1]))}>
            <Play /> Your sentence
          </Button>
        )}
        <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground" onClick={onToggleDismiss}>
          {dismissed ? <RotateCcw /> : <ThumbsDown />}
          {dismissed ? "It is a mistake" : "Not a mistake"}
        </Button>
      </div>
    </article>
  );
});
