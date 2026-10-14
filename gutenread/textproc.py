"""Pure text helpers (no GUI): cleaning, tokenising, pivot letter and timing."""
from __future__ import annotations

import re

_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*?\*\*\*", re.I)
_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)
_ILLUSTRATION = re.compile(r"\[Illustration[^\]]*\]", re.I)
_JOINED_DASH = re.compile(r"(?<=\w)(?:--|\u2014|\u2013)(?=\w)")


def strip_boilerplate(raw: str) -> str:
    """Remove the Project Gutenberg licence header and footer, if present."""
    start = _START.search(raw)
    if start:
        raw = raw[start.end():]
    end = _END.search(raw)
    if end:
        raw = raw[:end.start()]
    return raw


def prepare(raw: str) -> list[str]:
    """Return the book as a list of displayable words."""
    text = strip_boilerplate(raw.replace("\r\n", "\n").replace("\r", "\n"))
    text = _ILLUSTRATION.sub(" ", text)
    text = text.replace("_", "")                 # Gutenberg's italics markers
    text = _JOINED_DASH.sub(" ", text)           # "word--word" -> two words
    return [w for w in text.split() if any(ch.isalnum() for ch in w)]


def pivot_index(word: str) -> int:
    """Index of the 'optimal recognition point' letter the eye should rest on."""
    lead = 0
    while lead < len(word) and not word[lead].isalnum():
        lead += 1
    end = len(word)
    while end > lead and not word[end - 1].isalnum():
        end -= 1
    n = end - lead
    if n <= 1:
        base = 0
    elif n <= 5:
        base = 1
    elif n <= 9:
        base = 2
    elif n <= 13:
        base = 3
    else:
        base = 4
    return min(lead + base, max(len(word) - 1, 0))


def split_pivot(word: str) -> tuple[str, str, str]:
    if not word:
        return "", "", ""
    i = pivot_index(word)
    return word[:i], word[i], word[i + 1:]


def word_delay_ms(word: str, wpm: int, punctuation: bool = True) -> int:
    """Display time for one word; optionally linger on punctuation and long words."""
    mult = 1.0
    core = word.rstrip("\"'\u201d\u2019)]}")
    if punctuation:
        if core.endswith((".", "!", "?", "\u2026")):
            mult = 2.0
        elif core.endswith((",", ";", ":", "\u2014")):
            mult = 1.5
    if len(word) > 8:
        mult += min((len(word) - 8) * 0.05, 0.5)
    return max(20, int(60000 / max(wpm, 1) * mult))
