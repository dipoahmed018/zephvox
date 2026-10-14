"""The canonical phone set every G2P and phoneme-recognizer driver converts into.

Canonical form is broad IPA without stress, length or diacritics, with US-style symbols
(ɹ, ɚ, oʊ). Mixing drivers is only safe because they all meet here.
"""

from __future__ import annotations

from collections.abc import Iterable

# Marks that carry no phonemic contrast we want to judge.
_STRIP = str.maketrans("", "", "ˈˌːˑ̩̯͡ʲ̃")

# Whole-symbol rewrites applied after stripping.
_REWRITE = {
    "ɐ": "ə",
    "ᵻ": "ɪ",
    "ɾ": "t",  # flap: "water" — not a mistake
    "ʔ": "t",  # glottal stop for /t/
    "ɝ": "ɚ",
    "ɜ": "ɚ",
    "g": "ɡ",
    "r": "ɹ",
    "ɫ": "l",
    "ɒ": "ɑ",
    "a": "æ",  # en-gb "trap"
    "e": "ɛ",
    "o": "ɔ",  # en-us espeak "more" /moːɹ/
    "əʊ": "oʊ",  # en-gb "go"
}

ARPABET_TO_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ",
    "ER": "ɚ", "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ",
    "UW": "u", "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ",
    "HH": "h", "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v",
    "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}  # fmt: skip

# The canonical English inventory: what CMUdict can produce, plus schwa.
ENGLISH_PHONES = frozenset(ARPABET_TO_IPA.values()) | {"ə"}

_VOWEL_CHARS = set("iɪeɛæaɑɒɔoʊuʌəɚɜɐᵻy")

# Pairs that differ by accent or casual speech rather than by mistake.
MINOR_PAIRS = {
    frozenset(p)
    for p in [("ə", "ʌ"), ("ə", "ɪ"), ("ɑ", "ɔ"), ("ə", "ʊ")]
}

# Real but smaller errors: final s/z voicing is hard to hear and rarely hurts understanding.
HALF_PAIRS = {frozenset(("s", "z"))}


def normalize_phone(phone: str) -> str:
    p = phone.strip().translate(_STRIP)
    return _REWRITE.get(p, p)


def normalize(phones: Iterable[str]) -> list[str]:
    out = []
    for phone in phones:
        p = normalize_phone(phone)
        if p and p != "|":
            out.append(p)
    return out


# Two symbols that make one English phone when a driver writes IPA as single characters.
_PAIRS = {"aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "əʊ", "tʃ", "dʒ"}
_MARKS = set("ˈˌːˑ͡")


def split_ipa(text: str | Iterable[str]) -> list[str]:
    """IPA written as one character per symbol ("tʃeɪn") → canonical phones (tʃ eɪ n).

    Ambiguous on purpose in rare cases: "drawing" /dɹɔɪŋ/ reads as ɔɪ, like most IPA readers would.
    """
    chars = [c for c in text if c not in _MARKS and not c.isspace() and c not in "-."]
    out, i = [], 0
    while i < len(chars):
        pair = "".join(chars[i : i + 2])
        if pair in _PAIRS:
            out.append(pair)
            i += 2
        else:
            out.append(chars[i])
            i += 1
    return normalize(out)


def arpabet_to_ipa(arpabet: Iterable[str]) -> list[str]:
    out = []
    for token in arpabet:
        base, stress = token.rstrip("012"), token[len(token.rstrip("012")) :]
        if base == "AH" and stress == "0":
            out.append("ə")  # unstressed AH is schwa
        elif base not in ARPABET_TO_IPA:
            raise ValueError(f"Unknown ARPAbet symbol {token!r}")
        else:
            out.append(ARPABET_TO_IPA[base])
    return out


def is_vowel(phone: str) -> bool:
    return any(c in _VOWEL_CHARS for c in phone)


def substitution_cost(expected: str, heard: str) -> float:
    if expected == heard:
        return 0.0
    if frozenset((expected, heard)) in MINOR_PAIRS:
        return 0.25
    if frozenset((expected, heard)) in HALF_PAIRS or (is_vowel(expected) and is_vowel(heard)):
        return 0.5
    return 1.0


def deletion_cost(expected: str) -> float:
    # Dropping a schwa ("fam(i)ly", "choc(o)late") is normal in fluent speech.
    return 0.25 if expected == "ə" else 1.0


def insertion_cost(heard: str) -> float:
    return 0.5
