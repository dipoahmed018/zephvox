"""Prompt and output schema for the grammar analyzer."""

from __future__ import annotations

import json

CATEGORIES = [
    "verb-tense", "subject-verb-agreement", "article", "preposition", "word-order", "plural",
    "pronoun", "word-form", "missing-word", "extra-word", "word-choice", "other",
]  # fmt: skip

SYSTEM_PROMPT = """\
You are an English teacher reviewing a transcript of a learner's SPOKEN English.
Find genuine grammar mistakes: verb tense, subject-verb agreement, articles, prepositions,
word order, plurals, pronouns, wrong word form, missing or extra words, wrong word choice.

Do NOT report:
- natural spoken style: contractions, normal sentence fragments, starting with "and"/"so"/"but"
- filler words (um, uh, like, you know), false starts, repetitions and self-corrections
- punctuation, capitalization or spelling (a speech recognizer wrote the text, not the speaker)
- anything that looks like a speech-recognition error rather than the speaker's own grammar

For each mistake:
- "original": copy the wrong words EXACTLY from the sentence, as few words as possible
- "correction": the words that should replace "original"
- "explanation": one short sentence a learner understands
- "confidence": 0 to 1, how sure you are this is a real mistake
Return an empty "mistakes" list when there are none. Reply with JSON only."""


def user_prompt(sentences: list[str]) -> str:
    items = [{"index": i, "text": s} for i, s in enumerate(sentences)]
    return "Sentences:\n" + json.dumps(items, ensure_ascii=False, indent=1)


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
