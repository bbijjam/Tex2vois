"""Rule-based cleanup so extracted text reads well aloud."""

from __future__ import annotations

import re
import unicodedata

_RULES: list[tuple[re.Pattern[str], str]] = [
    # numeric citations: [3], [1, 4], [2-5], [1–3, 7]
    (re.compile(r"\s?\[\d+(?:\s*[-–,]\s*\d+)*\]"), ""),
    # author-year citations: (Smith, 2020), (Smith et al., 2019; Lee & Park 2021a)
    (
        re.compile(
            r"\s?\((?:see\s)?(?:[A-Z][\w'-]+(?:\s(?:et al\.|and|&)\s?(?:[A-Z][\w'-]+)?)?,?\s\d{4}[a-z]?(?:;\s?)?)+\)"
        ),
        "",
    ),
    (re.compile(r"https?://\S+|www\.\S+"), ""),
    (re.compile(r"\S+@\S+\.\w+"), ""),
    # abbreviations that TTS engines mangle
    (re.compile(r"\be\.g\.,?", re.I), "for example,"),
    (re.compile(r"\bi\.e\.,?", re.I), "that is,"),
    (re.compile(r"\betc\."), "et cetera."),
    (re.compile(r"\bet al\."), "and colleagues"),
    (re.compile(r"\bvs\.?(?=\s)"), "versus"),
    (re.compile(r"\bFigs?\.\s?(?=\d)"), "Figure "),
    (re.compile(r"\bEqs?\.\s?(?=\d)"), "Equation "),
    (re.compile(r"\bSec(?:t)?\.\s?(?=\d)"), "Section "),
    (re.compile(r"\bpp?\.\s?(?=\d)"), "page "),
    # tidy
    (re.compile(r"\(\s*\)"), ""),
    (re.compile(r"\s+([,.;:!?])"), r"\1"),
    (re.compile(r"([,;:])(?=[^\s\d])"), r"\1 "),
    (re.compile(r",\s*,"), ","),
    (re.compile(r"[ \t]{2,}"), " "),
]


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")  # soft hyphen
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text.strip()


def is_noise(paragraph: str) -> bool:
    """Paragraphs that are not worth reading: figure/table captions, stray symbols."""
    p = paragraph.strip()
    if len(p) < 3:
        return True
    if re.match(r"^(figure|fig\.|table)\s*\d+[.:]", p, re.I):
        return True
    letters = sum(c.isalpha() for c in p)
    return letters / len(p) < 0.5
