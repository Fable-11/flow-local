"""Self-corrections said aloud: "send it to Ahmed, no no, I mean Omar" -> "send it to Omar".

These rules work without the AI model, so a correction is resolved even when the model is off,
too slow, or its answer is rejected. They are deliberately cautious: wrongly deleting words the
speaker wanted is far worse than leaving a correction in. So a correction is only resolved when

* the speaker used a clear retraction phrase ("no no", "no wait", "I meant", "make that",
  "or rather", "لا لا قصدي", ...) and there is something before it in the same sentence,
* the new part clearly replaces a part of the same kind (a name for a name, a day for a day, the
  same opening words), or the speaker restarted a whole clause after "no no",
* it is not a mention ("I say no no I mean this"), a quotation or an explanation.

Anything else is left to the AI model, and when nothing can decide, both versions stay.
"""

from __future__ import annotations

import re

_F = re.IGNORECASE
_TERMINATORS = ".!?؟\n"
_COMMA = "[,،]"
_GAP = r"[\s,.،]+"

# Retraction phrases. STRONG ones count anywhere; WEAK ones only straight after a comma.
_STRONG = [
    rf"(?:no{_GAP}){{2,}}(?:(?:i\s+mean(?:t)?|قصدي|أقصد|اقصد){_GAP})?",
    rf"no{_GAP}(?:i\s+mean(?:t)?|wait|sorry){_GAP}",
    rf"(?:wait|actually){_GAP}no{_GAP}",
    rf"sorry{_GAP}(?:i\s+)?mean(?:t)?{_GAP}",
    rf"i\s+meant{_GAP}",
    rf"make\s+that{_GAP}",
    rf"or\s+rather{_GAP}",
    rf"لا\s+لا(?:\s+لا)*{_GAP}(?:(?:قصدي|أقصد|اقصد|بل){_GAP})?",
    rf"لا\s+(?:قصدي|أقصد|اقصد|بل|انتظر|لحظة){_GAP}",
]
_WEAK = [rf"i\s+mean{_GAP}", rf"(?:قصدي|أقصد|اقصد){_GAP}"]
_MARK = re.compile(
    rf"(?<![\w])(?P<strong>{'|'.join(_STRONG)})|"
    rf"(?<={_COMMA})\s*(?<![\w])(?P<weak>{'|'.join(_WEAK)})",
    _F,
)
_REPEATED_NO = re.compile(r"(?:\bno[\s,.،]+){2,}", _F)

# words that show the speaker is talking ABOUT a correction, not making one
_META = frozenset(
    "say says said saying word words phrase phrases feature command quote called type typed "
    "mean means الكلمة أقول قلت يقول".split()
)
# a tail that starts like this is a continuation or an explanation, not a replacement
_NOT_A_REPLACEMENT = frozenset(
    "and but because so then that which meaning than this it its these those there is are was "
    "were و لكن لان لأن ثم".split()
)
_BACK_REFERENCE = frozenset("it them him her this that these those they there".split())
_QUESTION_OR_STARTER = frozenset(
    "what how why who when where which so i we let's lets please can could should would do does "
    "ماذا كيف لماذا من متى أين".split()
)
_WEEKDAYS = frozenset(
    "monday tuesday wednesday thursday friday saturday sunday january february march april may "
    "june july august september october november december "
    "السبت الأحد الاحد الاثنين الثلاثاء الأربعاء الاربعاء الخميس الجمعة".split()
)
_NUMBERISH = re.compile(r"^[\d٠-٩][\d٠-٩.:]*$")
_WORD = re.compile(r"[^\s,،.!?؟]+")
MAX_CLAUSE_WORDS = 12
MAX_SPAN_WORDS = 6


def _kind(word: str) -> str:
    w = word.strip("\"'()").lower()
    if _NUMBERISH.match(w):
        return "number"
    if w in _WEEKDAYS:
        return "day"
    if re.search(r"[؀-ۿ]", w):
        return "arabic"
    if word[:1].isupper():
        return "name"
    return "word"


def _carry_prefix(old: str, new: str) -> str:
    """"لأحمد" corrected to "عمر" is "لعمر": the one-letter preposition belongs to the sentence."""
    if len(old) >= 4 and old[0] in "لب" and not new.startswith((old[0], "ال")):
        return old[0] + new
    return new


def mentioned(before_clause: str, before_all: str) -> bool:
    words = [w.lower() for w in _WORD.findall(before_clause)][-6:]
    if any(w in _META for w in words):
        return True
    return before_all.count('"') % 2 == 1 or before_all.count("“") > before_all.count("”")


def _split_tail(tail: str) -> tuple[str, str]:
    """(the rest of the sentence, whatever comes after its end)."""
    cut = next((i for i, c in enumerate(tail) if c in _TERMINATORS), None)
    if cut is None:
        return tail, ""
    return tail[:cut], tail[cut:]


def _item(tail: str) -> tuple[str, str]:
    """The replacement (up to the next comma or "and ...") and what follows it."""
    m = re.search(rf"{_COMMA}|\s(?:and|then|but|so|because|و)\s", tail, _F)
    if not m:
        return tail.strip(), ""
    return tail[: m.start()].strip(), tail[m.start() :]


def _try_repair(text: str, m: re.Match[str]) -> str | None:
    before_all = text[: m.start()]
    clause_start = max((before_all.rfind(c) for c in _TERMINATORS), default=-1) + 1
    clause = before_all[clause_start:]
    before_words = list(_WORD.finditer(clause))
    if not before_words:
        return None  # nothing before it in this sentence: "No, I mean it", "I mean business"
    if mentioned(clause, before_all):
        return None
    strong = m.group("strong") is not None
    marker = m.group(0)
    sentence, after_sentence = _split_tail(text[m.end() :])
    sentence = sentence.strip()
    first = (_WORD.findall(sentence) or [""])[0].lower()
    head = text[:clause_start]

    if not sentence:  # "how to start, how to start, I mean": drop the marker, collapse the repeat
        words = [w.group(0) for w in before_words]
        for n in (4, 3, 2, 1):
            low = [w.lower() for w in words]
            if len(words) >= 2 * n and low[-n:] == low[-2 * n : -n]:
                cut = before_words[-n].start()
                return head + clause[:cut].rstrip(" ,،") + after_sentence
        return head + clause.rstrip(" ,،") + after_sentence
    if first in _NOT_A_REPLACEMENT:
        return None

    # (c) a restart: "no no" followed by a new clause drops the abandoned clause
    restart = len(_WORD.findall(sentence)) >= 4 and _REPEATED_NO.search(marker) is not None
    if restart and first in _QUESTION_OR_STARTER and len(before_words) <= MAX_CLAUSE_WORDS:
        return head + sentence + after_sentence

    item, rest = _item(sentence)
    item_words = list(_WORD.finditer(item))
    if not item_words or len(item_words) > 8:
        return None
    first_item = item_words[0].group(0)
    if any(w.group(0).lower() in _BACK_REFERENCE for w in item_words):
        return None  # "send it to Omar" points back at "the file": leave it to the AI model
    before_texts = [w.group(0) for w in before_words]

    # numbers are handled by the number rules that run next
    if _kind(first_item) == "number" and _kind(before_texts[-1]) == "number":
        return None

    # (a) the replacement starts with words the speaker already said: "the red one ... the blue one"
    window = before_texts[-MAX_SPAN_WORDS:]
    base = len(before_texts) - len(window)
    for i in range(len(window) - 1, -1, -1):
        if window[i].lower() == first_item.lower() and len(item_words) > 1:
            cut = before_words[base + i].start()
            return head + clause[:cut] + item + rest + after_sentence

    # (b) the replacement is the same kind of thing as the last words said: a name for a name
    # Only the swapped thing is replaced, never the words that carry on after it: a name may be
    # up to three capitalised words, a day or an Arabic word is exactly one.
    item_kind = _kind(first_item)
    if item_kind not in ("name", "day", "arabic") or _kind(before_texts[-1]) != item_kind:
        return None
    if not strong and item_kind == "arabic":
        return None  # a bare "أقصد" needs more than a same-script word to go on
    k = 1
    if item_kind == "name":
        while k < min(len(item_words), 3) and _kind(item_words[k].group(0)) == "name":
            k += 1
        k = min(k, len(before_words))
        if not all(_kind(w) == "name" for w in before_texts[-k:]):
            k = 1
    new = item[: item_words[k - 1].end()]
    rest = item[item_words[k - 1].end() :] + rest
    if item_kind == "arabic":
        new = _carry_prefix(before_texts[-1], new)
    cut = before_words[-k].start()
    return head + clause[:cut] + new + rest + after_sentence


def repair_corrections(text: str) -> str:
    """Resolve clear self-corrections; leave everything else exactly as it was."""
    if not text:
        return text
    original = text
    text += " "  # lets a retraction phrase at the very end match like any other
    pos = 0
    for _ in range(6):
        for m in _MARK.finditer(text, pos):
            fixed = _try_repair(text, m)
            if fixed is not None and fixed.strip():
                text = fixed
                pos = 0
                break
        else:
            break
    text = text.rstrip(" ") if not original.endswith(" ") else text
    return text
