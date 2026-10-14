"""Plain-English names for phones, so explanations don't require knowing IPA."""

from __future__ import annotations

from collections.abc import Iterable

from .align import AlignOp

PHONE_HINTS = {
    # consonants
    "p": "'p' as in pen", "b": "'b' as in bad", "t": "'t' as in top", "d": "'d' as in dog",
    "k": "'k' as in cat", "ɡ": "'g' as in go", "f": "'f' as in fish", "v": "'v' as in very",
    "θ": "'th' as in think", "ð": "'th' as in this", "s": "'s' as in see", "z": "'z' as in zoo",
    "ʃ": "'sh' as in she", "ʒ": "'s' as in measure", "h": "'h' as in hat", "tʃ": "'ch' as in chair",
    "dʒ": "'j' as in jump", "m": "'m' as in man", "n": "'n' as in no", "ŋ": "'ng' as in sing",
    "l": "'l' as in look", "ɹ": "'r' as in red", "w": "'w' as in we", "j": "'y' as in yes",
    # vowels
    "i": "'ee' as in see", "ɪ": "'i' as in sit", "eɪ": "'ay' as in say", "ɛ": "'e' as in bed",
    "æ": "'a' as in cat", "ɑ": "'a' as in father", "ɔ": "'aw' as in law", "oʊ": "'o' as in go",
    "ʊ": "'oo' as in book", "u": "'oo' as in food", "ʌ": "'u' as in cup", "ə": "the weak 'uh' in about",
    "ɚ": "'er' as in her", "aɪ": "'i' as in my", "aʊ": "'ow' as in now", "ɔɪ": "'oy' as in boy",
}  # fmt: skip


def describe(phone: str) -> str:
    return PHONE_HINTS.get(phone, f"/{phone}/")


def errors_of(ops: Iterable[AlignOp]) -> list[AlignOp]:
    return [op for op in ops if op.op != "match" and op.cost > 0]


def category(ops: Iterable[AlignOp]) -> str:
    """Short label of the most serious error: "θ→s", "-ɹ" (missing) or "+ə" (extra)."""
    errs = sorted(errors_of(ops), key=lambda op: -op.cost)
    if not errs:
        return "unclear"
    op = errs[0]
    if op.op == "sub":
        return f"{op.expected}→{op.heard}"
    if op.op == "del":
        return f"-{op.expected}"
    return f"+{op.heard}"


def explain(ops: Iterable[AlignOp], limit: int = 3) -> str:
    sentences = []
    for op in sorted(errors_of(ops), key=lambda op: -op.cost)[:limit]:
        if op.op == "sub":
            sentences.append(f"You said {describe(op.heard)} instead of {describe(op.expected)}.")
        elif op.op == "del":
            sentences.append(f"The {describe(op.expected)} sound was missing.")
        else:
            sentences.append(f"An extra {describe(op.heard)} sound was added.")
    return " ".join(sentences) or "This word was not pronounced clearly."


# How to physically make the sounds learners most often get wrong.
MOUTH_TIPS = {
    "θ": "Put your tongue tip lightly between your teeth and blow air out, without using your voice.",
    "ð": "Tongue tip lightly between your teeth, like 'th' in think, but use your voice (feel a buzz).",
    "v": "Rest your top teeth on your bottom lip and use your voice; don't round your lips.",
    "w": "Round your lips into a small 'o' and open them; your teeth shouldn't touch your lip.",
    "ɹ": "Pull your tongue back without touching the roof of your mouth; round your lips a little.",
    "l": "Press your tongue tip on the ridge just behind your top teeth.",
    "ʃ": "Round your lips and pull your tongue a bit further back than for 's'.",
    "z": "Like 's', but use your voice — you should feel your throat buzz.",
    "s": "Tongue close to the ridge behind your top teeth, push air out, no voice.",
    "æ": "Open your mouth wide and spread your lips, like the 'a' in cat.",
    "i": "Spread your lips like a smile and hold the sound a little longer than 'i' in sit.",
    "ɪ": "Short and relaxed — your lips and tongue are looser than for 'ee'.",
    "ŋ": "Raise the back of your tongue to touch the soft palate; air goes through your nose. Don't add 'g'.",
    "f": "Top teeth on your bottom lip, blow air out without voice.",
    "dʒ": "Start like 'd' and release into a buzzing 'zh' sound, as in jump.",
    "tʃ": "Start like 't' and release into 'sh', as in chair.",
}


def tip(ops: Iterable[AlignOp]) -> str:
    """Mouth tip for the most serious missed/replaced sound, if we have one."""
    for op in sorted(errors_of(ops), key=lambda op: -op.cost):
        if op.expected and op.expected in MOUTH_TIPS:
            return MOUTH_TIPS[op.expected]
    return ""
