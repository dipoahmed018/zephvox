import { Ear, Play, RotateCcw, Target, ThumbsDown, Volume2 } from "lucide-react";
import { play, speak, urls } from "../api";
import type { Finding, Span } from "../types";

interface Props {
  finding: Finding;
  sessionId: string;
  sentenceSpan?: Span;
  dismissed: boolean;
  onToggleDismiss: () => void;
  onPractice: (text: string, span?: Span | null) => void;
}

export function correctedSentence(f: Finding): string {
  const i = f.sentence.toLowerCase().indexOf(f.said.toLowerCase());
  if (i < 0) return f.sentence;
  return f.sentence.slice(0, i) + f.expected + f.sentence.slice(i + f.said.length);
}

export function FindingCard({ finding: f, sessionId, sentenceSpan, dismissed, onToggleDismiss, onPractice }: Props) {
  const pron = f.analyzer === "pronunciation";
  const fixed = pron ? f.sentence : correctedSentence(f);
  return (
    <div className="card fcard">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className={`chip ${pron ? "teal" : "amber"}`}>{pron ? "Pronunciation" : "Grammar"}</span>
        <span className="chip">{f.category}</span>
      </div>
      <h3 style={{ marginTop: 14 }}>{pron ? f.target : <span className="strike">{f.said}</span>}</h3>

      <div className="compare">
        <div className="compare-row bad">
          <span className="label">You said</span>
          <span className={`value${pron ? " ipa" : ""}`}>{f.said}</span>
        </div>
        <div className="compare-row good">
          <span className="label">Correct</span>
          <span className={`value${pron ? " ipa" : ""}`}>{f.expected}</span>
        </div>
      </div>

      {f.explanation && <p style={{ margin: 0 }}>{f.explanation}</p>}
      <p className="quote">“{pron ? f.sentence : fixed}”</p>

      <div className="actions">
        {pron && f.time_span && (
          <button className="btn small" onClick={() => play(urls.clip(sessionId, f.time_span![0], f.time_span![1]))}>
            <Ear size={15} /> Your word
          </button>
        )}
        {sentenceSpan && (
          <button className="btn small" onClick={() => play(urls.clip(sessionId, sentenceSpan[0], sentenceSpan[1]))}>
            <Play size={15} /> Your sentence
          </button>
        )}
        <button className="btn small" onClick={() => speak(pron ? f.target : fixed)}>
          <Volume2 size={15} /> Hear it correctly
        </button>
      </div>
      <div className="actions">
        <button className="btn primary small" onClick={() => onPractice(pron ? f.target : fixed, pron ? f.time_span : sentenceSpan)}>
          <Target size={15} /> Practise {pron ? "this word" : "this sentence"}
        </button>
        <button className="btn ghost small" onClick={onToggleDismiss}>
          {dismissed ? <RotateCcw size={15} /> : <ThumbsDown size={15} />}
          {dismissed ? "Undo — it is a mistake" : "Not a mistake"}
        </button>
      </div>
    </div>
  );
}
