import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { navigate } from "@/router";

const MAX_LENGTH = 100;

/** Type any word or short sentence to practice it. */
export function WordInput({ autoFocus = false }: { autoFocus?: boolean }) {
  const [text, setText] = useState("");
  const clean = text.trim().replace(/\s+/g, " ");
  const valid = clean.length > 0 && /\p{L}/u.test(clean);
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        navigate("practice", undefined, { w: clean });
        setText("");
      }}
    >
      <Input
        aria-label="Word or sentence to practice"
        placeholder="Type any word or sentence"
        maxLength={MAX_LENGTH}
        autoFocus={autoFocus}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="h-10 bg-card"
      />
      <Button type="submit" variant="outline" disabled={!valid}>
        Practice <ArrowRight />
      </Button>
    </form>
  );
}
