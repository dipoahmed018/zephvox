import type { AnalysisResult, Feedback, Finding } from "@/types";

interface Props {
  result: AnalysisResult;
  feedback: Feedback;
  selected: number | null;
  onSelect: (index: number) => void;
}

interface Piece {
  text: string;
  finding: number | null;
}

/** Split one sentence into runs of plain words and runs belonging to a single finding. */
export function pieces(sentence: string, sentenceIndex: number, findings: Finding[]): Piece[] {
  const tokens = sentence.split(/\s+/).filter(Boolean);
  const owner: (number | null)[] = tokens.map(() => null);
  findings.forEach((f, i) => {
    if (f.segment_index !== sentenceIndex || !f.word_span) return;
    for (let k = f.word_span[0]; k <= f.word_span[1] && k < tokens.length; k++) {
      if (owner[k] === null) owner[k] = i;
    }
  });
  const out: Piece[] = [];
  tokens.forEach((t, k) => {
    const last = out[out.length - 1];
    if (last && last.finding === owner[k]) last.text += ` ${t}`;
    else out.push({ text: t, finding: owner[k] });
  });
  return out;
}

export function Transcript({ result, feedback, selected, onSelect }: Props) {
  if (!result.sentences.length) return <p className="text-muted-foreground">No speech was recognized in this recording.</p>;
  return (
    <div className="grid gap-3 font-display text-xl leading-[1.7] font-light">
      {result.sentences.map((sentence, si) => (
        <p key={si} className="m-0">
          {pieces(sentence, si, result.findings).map((piece, pi) => {
            const space = pi > 0 ? " " : "";
            if (piece.finding === null) return space + piece.text;
            const f = result.findings[piece.finding];
            const dismissed = feedback[String(piece.finding)] === "dismissed";
            const kind = f.analyzer === "grammar" ? "w-gram" : "w-pron";
            return (
              <span key={pi}>
                {space}
                <button
                  type="button"
                  className={`${kind}${dismissed ? " w-dismissed" : ""}${selected === piece.finding ? " selected" : ""}`}
                  onClick={() => onSelect(piece.finding!)}
                  aria-label={`${f.analyzer} mistake: ${piece.text}`}
                >
                  {piece.text}
                </button>
              </span>
            );
          })}
        </p>
      ))}
    </div>
  );
}
