"""The spoken script: chapters of paragraphs, each with a stable id.

Every input kind (pasted article, PDF paper, later books) becomes a Script.
Derived versions (skim, summary) reuse paragraph ids via `source`, so a
player can jump from a skim paragraph to the same spot in the full reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import clean, extract

ROLES = {
    "abstract": r"abstract|summary",
    "introduction": r"introduction|background",
    "methods": r"methods|materials and methods|methodology|experimental( procedures| section)?",
    "results": r"results( and discussion)?",
    "discussion": r"discussion",
    "conclusion": r"conclusions?|concluding remarks|outlook",
}


def role_of(title: str) -> str:
    key = re.sub(r"[^a-z ]", "", title.lower()).strip()
    for role, pattern in ROLES.items():
        if re.fullmatch(pattern, key):
            return role
    return "body"


@dataclass
class Para:
    id: str
    text: str
    source: str | None = None  # id of the full-script paragraph this one stands for


@dataclass
class Chapter:
    title: str
    paras: list[Para] = field(default_factory=list)
    role: str = "body"


@dataclass
class Script:
    title: str
    chapters: list[Chapter]
    kind: str = "article"  # article | paper | book
    mode: str = "full"  # full | skim | summary
    notes: list[str] = field(default_factory=list)  # e.g. why an LLM step fell back

    @property
    def words(self) -> int:
        return sum(len(p.text.split()) for c in self.chapters for p in c.paras)

    def by_id(self) -> dict[str, Para]:
        return {p.id: p for c in self.chapters for p in c.paras}

    def to_markdown(self) -> str:
        return "\n\n".join(f"## {c.title}\n\n" + "\n\n".join(p.text for p in c.paras) for c in self.chapters)


def _number(chapters: list[tuple[str, list[str]]], kind: str, title: str) -> Script:
    out = []
    for ci, (name, paras) in enumerate(chapters, 1):
        out.append(Chapter(name, [Para(f"c{ci}p{pi}", t) for pi, t in enumerate(paras, 1)], role_of(name)))
    return Script(title, out, kind)


def from_pdf(path: str, max_pages: int | None = None) -> Script:
    sections = extract.extract(str(path), max_pages=max_pages)
    chapters = []
    for i, sec in enumerate(sections, 1):
        paras = [p for p in (clean.clean(x) for x in sec.paragraphs) if not clean.is_noise(p)]
        if paras:
            chapters.append((clean.clean(sec.title) or f"Part {i}", paras))
    if not chapters:
        raise ValueError("No readable text found. Is this a scanned PDF? (OCR is on the roadmap.)")
    title = extract.document_title(str(path)) or re.sub(r"[_-]+", " ", str(path).rsplit("/", 1)[-1].rsplit(".", 1)[0])
    return _number(chapters, "paper", title)


_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")


def from_text(text: str, title: str | None = None) -> Script:
    """Pasted article text. Markdown '#' headings become chapters; blank lines split paragraphs."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise ValueError("No text to read.")
    chapters: list[tuple[str, list[str]]] = [("", [])]
    for block in re.split(r"\n\s*\n", text):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        heading = _MD_HEADING.match(lines[0])
        if heading:
            chapters.append((heading.group(1), []))
            lines = lines[1:]
        if lines:
            para = clean.clean(" ".join(lines))
            if para:
                chapters[-1][1].append(para)
    chapters = [(t, p) for t, p in chapters if p]
    if not chapters:
        raise ValueError("No text to read.")
    first = chapters[0][1][0]
    if not title:
        # a short first line with no final period reads like a headline
        title = first if len(first) < 100 and not first.endswith((".", "!", "?")) else first.split(".")[0][:60]
    if not chapters[0][0]:
        if chapters[0][1][0] == title and len(chapters[0][1]) > 1:
            chapters[0] = (title, chapters[0][1][1:])
        else:
            chapters[0] = (title, chapters[0][1])
    return _number(chapters, "article", title)
