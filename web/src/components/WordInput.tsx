import { Target } from "lucide-react";
import { useState } from "react";
import { navigate } from "../router";

const MAX_LENGTH = 100;

/** Type any word or short sentence to practice it. */
export function WordInput({ autoFocus = false }: { autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const clean = text.trim().replace(/\s+/g, " ");
  const valid = clean.length > 0 && /\p{L}/u.test(clean);

  return (
    <form
      className="word-input"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        navigate("practice", undefined, { w: clean });
        setText("");
      }}
    >
      <input
        className="input"
        aria-label="Word or sentence to practice"
        placeholder="Type a word…"
        maxLength={MAX_LENGTH}
        autoFocus={autoFocus}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button className="btn primary small" type="submit" disabled={!valid}>
        <Target size={15} /> Practice
      </button>
    </form>
  );
}
