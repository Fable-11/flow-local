"""Automatic dictionary matching by sound.

A dictionary word does not need a typed "spoken form" to be used: if the speech model writes
"cuber nettys" for a word in the dictionary called "Kubernetes", the words are close enough in
sound and spelling to be replaced automatically. The matching is strict on purpose, so ordinary
words are not rewritten by accident.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[A-Za-z][A-Za-z']*")
_VOWELS = re.compile(r"[aeiouyhw]")
_SPELLED = (
    ("ph", "f"), ("ck", "k"), ("kn", "n"), ("wr", "r"), ("wh", "w"), ("gh", ""),
    ("tion", "shn"), ("sion", "shn"),
)
MIN_LETTERS = 6  # shorter dictionary words are too easy to hit by accident
MAX_WORDS = 3  # "cuber nettys" is two words; allow up to three
SOUND_RATIO = 0.74  # similarity needed when the consonant skeletons match
SPELLING_RATIO = 0.86  # similarity needed on its own (a typo-sized difference)


def letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def skeleton(text: str) -> str:
    """Consonants of how a word sounds: "cubernettys" and "kubernetes" both give "kbrnts"."""
    s = letters(text)
    for old, new in _SPELLED:
        s = s.replace(old, new)
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = s.replace("c", "k").replace("q", "k").replace("x", "ks").replace("z", "s")
    s = s[:1] + _VOWELS.sub("", s[1:])
    return re.sub(r"(.)\1+", r"\1", s)


@dataclass(frozen=True)
class Target:
    written: str
    letters: str
    skeleton: str


def make_target(written: str) -> Target | None:
    if not re.fullmatch(r"[A-Za-z][A-Za-z\- ]*", written.strip()):
        return None  # digits, symbols and non-Latin words are matched exactly only
    key = letters(written)
    if len(key) < MIN_LETTERS:
        return None
    return Target(written, key, skeleton(written))


def _score(span_letters: str, target: Target, words: int) -> float:
    """How well a run of words matches a dictionary word: 0 when it does not match at all.

    One word must be a near-typo of the dictionary word. Several words (how a speech model
    splits an unknown name, "cuber nettys") may also match by sound, but only when the consonant
    skeleton is identical.
    """
    if span_letters == target.letters:
        return 0.0  # already right: only the casing is fixed elsewhere
    if abs(len(span_letters) - len(target.letters)) > max(3, len(target.letters) // 3):
        return 0.0
    ratio = difflib.SequenceMatcher(None, span_letters, target.letters).ratio()
    if ratio >= SPELLING_RATIO:
        return ratio
    if words < 2:
        return 0.0
    same_sound = len(target.skeleton) >= 3 and skeleton(span_letters) == target.skeleton
    return ratio if ratio >= SOUND_RATIO and same_sound else 0.0


def _neighbours(text: str, span: list[re.Match[str]]) -> bool:
    """True when the words are separated by exactly one space (no punctuation between)."""
    pairs = zip(span, span[1:], strict=False)
    return all(b.start() - a.end() == 1 and text[a.end()] == " " for a, b in pairs)


def replace_similar(
    text: str,
    targets: list[Target],
    skip: set[str],
    blocked: set[tuple[str, str]] | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Replace runs of 1-3 words that sound like a dictionary word.

    ``skip`` holds lower-case words that are never replaced: the dictionary's own words, so a
    word that is already right is left alone. ``blocked`` holds (heard, written) pairs, in lower
    case, that the user told us to stop replacing. Returns the new text and the (heard, written)
    pairs that were replaced.
    """
    if not targets or not text:
        return text, []
    tokens = list(_TOKEN.finditer(text))
    out: list[str] = []
    hits: list[tuple[str, str]] = []
    pos = 0  # copy position in ``text``
    i = 0
    while i < len(tokens):
        found: tuple[int, Target] | None = None
        best = 0.0
        for n in range(1, min(MAX_WORDS, len(tokens) - i) + 1):
            span = tokens[i : i + n]
            words = [t.group(0).lower() for t in span]
            if not _neighbours(text, span) or any(w in skip for w in words):
                continue
            joined = "".join(letters(w) for w in words)
            for target in targets:
                if (" ".join(words), target.written.lower()) in (blocked or ()):
                    continue
                score = _score(joined, target, n)
                if score > best:  # the closest run wins; on a tie the shorter one
                    best, found = score, (n, target)
        if found:
            n, target = found
            out.append(text[pos : tokens[i].start()])
            out.append(target.written)
            pos = tokens[i + n - 1].end()
            hits.append((text[tokens[i].start() : tokens[i + n - 1].end()], target.written))
            i += n
        else:
            i += 1
    out.append(text[pos:])
    return "".join(out), hits
