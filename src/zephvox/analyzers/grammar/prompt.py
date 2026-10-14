"""Prompt and output schema for the grammar analyzer."""

from __future__ import annotations

CATEGORIES = [
    "verb-tense", "subject-verb-agreement", "article", "preposition", "word-order", "plural",
    "pronoun", "word-form", "missing-word", "extra-word", "word-choice", "other",
]  # fmt: skip

SYSTEM_PROMPT = """\
You are a friendly native English speaker listening to a learner chat CASUALLY. The text is a
transcript of relaxed, spoken conversation, not writing. Judge it the way you would in a
conversation with a friend, not the way an editor or teacher marks an essay.

Report ONLY mistakes that a native speaker would hear as wrong even in casual talk, such as:
"he go" (→ "he went"), "didn't got" (→ "didn't get"), "she have two cat" (→ "has two cats"),
"I am agree" (→ "I agree"), "explain me" (→ "explain to me"), "more better" (→ "better").

Do NOT report:
- anything that is fine in casual speech, even if it would be informal in writing
- making it more formal, polished, concise or clearer; rephrasing; choosing a different word or
  conjunction when the speaker's choice also works ("but" vs "and", "get" vs "obtain")
- contractions or expanding them ("it's", "gonna", "kinda" are fine)
- long or run-on sentences, sentence fragments, starting with "and"/"so"/"but"
- fillers (um, uh, like, you know), false starts, repetitions, self-corrections
- punctuation, capitalization, quotes, titles or spelling (a speech recognizer wrote the text)
- anything that looks like a speech-recognition error rather than the speaker's grammar
If you are not sure it is wrong in casual speech, leave it out.

For each mistake:
- "original": copy the wrong words EXACTLY from the sentence, as few words as possible
- "correction": the words that should replace "original"
- "explanation": one short sentence (under 20 words) a learner understands
- "confidence": 0 to 1, how sure you are this is a real mistake
- "index": the number in front of the sentence
Never return an entry whose correction is the same as the original. Return an empty "mistakes"
list when there are none. Reply with JSON only."""


def user_prompt(sentences: list[str]) -> str:
    # Plain numbered lines: small models confuse sentence indices when given a JSON list.
    return "Sentences:\n" + "\n".join(f"{i}: {s}" for i, s in enumerate(sentences))


RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mistakes"],
    "properties": {
        "mistakes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "original", "correction", "category", "explanation", "confidence"],
                "properties": {
                    "index": {"type": "integer"},
                    "original": {"type": "string"},
                    "correction": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}
