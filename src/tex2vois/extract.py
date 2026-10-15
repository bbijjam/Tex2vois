"""PDF -> chapters of plain text.

Strips running headers/footers, page and line numbers, superscript citation
markers and back matter; rejoins hyphenated words; detects chapter headings
(PDF outline, font size, ALL-CAPS, run-in "1. Introduction." headings and
standard section names); and stops at the references section.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

MARGIN = 0.08  # top/bottom fraction of a page where headers/footers live
NUMBERING = r"^\s*(?:(?:\d+\.)*\d+\.?|[IVX]+\.)?\s*"
STOP_HEADINGS = re.compile(
    NUMBERING + r"(references|bibliography|works cited|literature cited|references and notes)[.:]?\s*$", re.I
)
BACK_MATTER = re.compile(
    NUMBERING + r"(acknowledge?ments?|funding( information)?|author contributions?|contributions"
    r"|conflicts? of interests?|competing interests?|declarations?( of competing interests?)?"
    r"|data availability( statement)?|supplementary (data|materials?|information)|supporting information"
    r"|key ?words|abbreviations|notation|graphical abstract|tables|figures|figure legends)[.:]?\s*$",
    re.I,
)
SECTION_NAMES = re.compile(
    NUMBERING + r"(abstract|summary|introduction|background|results( and discussion)?|discussion"
    r"|conclusions?|methods|materials and methods|methodology|experimental( procedures| section)?"
    r"|limitations|outlook|future work)[.:]?\s*$",
    re.I,
)
ABSTRACT = re.compile(r"^\s*abstract[.:]?\s*$", re.I)
LINE_NUMBER = re.compile(r"^\d{1,4}$")
SECTION_NUMBER = re.compile(r"^(?:\d+\.)+\d*$")  # "3.1" printed on its own above a heading
SUPERSCRIPT_CITATION = re.compile(r"^[\d\s,–-]+$")
FOOTNOTE_MARKS = re.compile(r"^[∗*†‡§¶#]+$")
FOOTNOTE_SCALE = 0.92  # lines this much smaller than body text are footnotes
CAPTION = re.compile(r"^(figure|fig\.|table|algorithm)\s*\d+[.:]", re.I)
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    skip: bool = False  # back matter: acknowledgements, funding, ...

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


@dataclass
class _Line:
    text: str
    size: float
    page: int
    y0: float
    y1: float
    page_height: float
    block: int
    bold: bool = False
    first: bool = False  # first line of its text block
    run_in: bool = False  # heading split off the start of a paragraph line


def _norm(text: str) -> str:
    """Key for spotting repeated headers: case-folded, digits masked."""
    return re.sub(r"\d+", "#", text.strip().lower())


def _key(text: str) -> str:
    """Key for matching headings to the PDF outline: no numbering or end punctuation."""
    text = re.sub(NUMBERING, "", text.strip()).rstrip(".: ")
    return re.sub(r"\s+", " ", text).lower()


def _figure_regions(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Areas covered by images or vector drawings (diagrams, plots, tables)."""
    page_area = page.rect.width * page.rect.height
    regions = [pymupdf.Rect(b["bbox"]) for b in page.get_text("dict")["blocks"] if b["type"] == 1]
    try:
        regions += page.cluster_drawings()
    except (AttributeError, ValueError):
        pass
    # ignore hairlines (rules, underlines) and page-wide borders
    return [r for r in regions if r.height > 20 and r.width > 20 and r.width * r.height < page_area * 0.6]


def _is_figure_label(bbox: pymupdf.Rect, text: str, fig: pymupdf.Rect, gap: float = 15) -> bool:
    """Text inside a figure, or a short title hugging its top/bottom edge."""
    if fig.contains(bbox) or (fig & bbox).get_area() > 0.6 * bbox.get_area():
        return True
    overlaps_x = bbox.x0 < fig.x1 and bbox.x1 > fig.x0
    hugs = 0 <= fig.y0 - bbox.y1 <= gap or 0 <= bbox.y0 - fig.y1 <= gap
    return overlaps_x and hugs and len(text) < 60 and not text.rstrip().endswith((".", ":", "?", "!"))


def text_of(line: dict) -> str:
    return "".join(s["text"] for s in line["spans"]).strip()


def _clean_spans(line: dict) -> list[dict]:
    """Drop margin line numbers, superscript citations and footnote marks."""
    spans = list(line["spans"])  # keep whitespace-only spans: they carry word spacing
    visible = [s for s in spans if s["text"].strip()]
    # bioRxiv-style line numbers: a short number set apart from the text
    if len(visible) > 1 and LINE_NUMBER.match(visible[0]["text"].strip()) and visible[1]["bbox"][0] - visible[0]["bbox"][2] > 4:
        spans = spans[spans.index(visible[0]) + 1 :]
    out: list[dict] = []
    for s in spans:
        t = s["text"].strip()
        if not t:
            out.append(s)
            continue
        if FOOTNOTE_MARKS.match(t):
            continue
        if s["flags"] & 1 and SUPERSCRIPT_CITATION.match(t):
            prev = "".join(o["text"] for o in out)
            last_word = re.split(r"[\s(]", prev.rstrip())[-1] if prev.strip() else ""
            # "10"+"4" and "N"+"3" are exponents; "regulation."+"4,34" is a citation
            if prev[-1:].isspace() or not (last_word[-1:].isdigit() or len(last_word) == 1 and last_word.isalpha()):
                continue
            s = {**s, "text": "^" + t}
        out.append(s)
    return out


def _split_run_in(spans: list[dict]) -> int:
    """Index where a run-in heading ("1. Introduction. Life is...") ends, or 0.

    The heading is a leading run of spans in a different font from the rest,
    ending with a period or colon.
    """
    visible = [i for i, s in enumerate(spans) if s["text"].strip()]
    if len(visible) < 2:
        return 0
    font = spans[visible[0]]["font"]
    n = 0
    for i in visible:
        if spans[i]["font"] != font:
            n = i
            break
    head = "".join(s["text"] for s in spans[:n]).strip()
    if not n or len(head) > 90 or not head.endswith((".", ":")):
        return 0
    return n


def _make_line(spans, pno, height, block_id, first, run_in=False) -> _Line:
    text = "".join(s["text"] for s in spans).strip()
    spans = [s for s in spans if s["text"].strip()] or spans
    size = max(spans, key=lambda s: len(s["text"]))["size"]
    bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)
    return _Line(text, round(size, 1), pno, y0, y1, height, block_id, bold, first, run_in)


def _read_lines(doc: pymupdf.Document, max_pages: int | None) -> list[_Line]:
    lines: list[_Line] = []
    block_id = 0
    for pno, page in enumerate(doc):
        if max_pages is not None and pno >= max_pages:
            break
        height = page.rect.height
        figures = _figure_regions(page)
        for block in page.get_text("dict", sort=True)["blocks"]:
            block_id += 1
            first = True
            for line in block.get("lines", []):
                if abs(line["dir"][1]) > 0.1:  # rotated text: arXiv stamps, margin notes
                    continue
                spans = _clean_spans(line)
                text = "".join(s["text"] for s in spans).strip()
                if not text or LINE_NUMBER.match(text) or SECTION_NUMBER.match(text):
                    continue
                if first and CAPTION.match(text):
                    break  # figure/table captions mean nothing without the figure
                bbox = pymupdf.Rect(line["bbox"])
                if any(_is_figure_label(bbox, text, r) for r in figures):
                    continue
                cut = _split_run_in(spans) if first else 0
                if cut:
                    lines.append(_make_line(spans[:cut], pno, height, block_id, True, run_in=True))
                    spans, first = spans[cut:], False
                lines.append(_make_line(spans, pno, height, block_id, first))
                first = False
    return lines


def _in_margin(line: _Line) -> bool:
    return line.y1 < line.page_height * MARGIN or line.y0 > line.page_height * (1 - MARGIN)


def _drop_headers_footers(lines: list[_Line], n_pages: int) -> list[_Line]:
    margin_counts = Counter(_norm(l.text) for l in lines if _in_margin(l))
    threshold = max(2, int(n_pages * 0.3))
    repeated = {k for k, c in margin_counts.items() if c >= threshold}
    return [
        l
        for l in lines
        if not (_in_margin(l) and (_norm(l.text) in repeated or PAGE_NUMBER.match(l.text)))
    ]


def _body_size(lines: list[_Line]) -> float:
    weights: Counter[float] = Counter()
    for l in lines:
        weights[l.size] += len(l.text)
    return weights.most_common(1)[0][0] if weights else 10.0


def _join_lines(parts: list[str]) -> str:
    out = ""
    for part in parts:
        if not out:
            out = part
        elif out.endswith("-") and part[:1].islower():
            last_word = out.rsplit(" ", 1)[-1]
            # re-join "exam-" + "ple", but keep real compounds like "English-" + "to"
            out = out + part if last_word[:1].isupper() else out[:-1] + part
        else:
            out += " " + part
    return out


def _drop_front_matter(lines: list[_Line]) -> list[_Line]:
    """Authors, affiliations and emails sit above the abstract: skip them."""
    for i, l in enumerate(lines):
        if l.page > 1:
            break
        if ABSTRACT.match(l.text):
            return lines[i:]
    return lines


def _drop_footnotes(lines: list[_Line], body: float) -> list[_Line]:
    """Drop small-print lines, except an abstract set in a smaller font."""
    kept, in_abstract = [], False
    for l in lines:
        if ABSTRACT.match(l.text):
            in_abstract = True
        elif l.run_in or l.size >= body * 1.15 or (l.first and SECTION_NAMES.match(l.text)):
            in_abstract = False
        if in_abstract or l.size >= body * FOOTNOTE_SCALE:
            kept.append(l)
    return kept


def document_title(pdf_path: str) -> str:
    """PDF metadata title, else the largest text on the first page."""
    with pymupdf.open(pdf_path) as doc:
        meta = (doc.metadata or {}).get("title", "").strip()
        if meta and not meta.lower().startswith(("microsoft word", "untitled")):
            return meta
        first = [l for l in _read_lines(doc, 1) if len(l.text) > 3]
    if not first:
        return ""
    # the title is the largest text, often wrapped over consecutive lines
    top = max(l.size for l in first)
    start = next(i for i, l in enumerate(first) if l.size == top)
    parts = []
    for l in first[start:]:
        if l.size != top or len(parts) == 4:
            break
        parts.append(l.text)
    return re.sub(r"[∗*†‡]+$", "", " ".join(parts)).strip()


def extract(pdf_path: str, stop_at_references: bool = True, max_pages: int | None = None) -> list[Section]:
    """Return the document as a list of sections, in reading order."""
    with pymupdf.open(pdf_path) as doc:
        n_pages = min(len(doc), max_pages) if max_pages else len(doc)
        toc_titles = {_key(title) for _, title, _ in doc.get_toc()}
        lines = _drop_headers_footers(_read_lines(doc, max_pages), n_pages)

    body = _body_size(lines)
    lines = _drop_footnotes(_drop_front_matter(lines), body)

    def is_heading(l: _Line) -> bool:
        if len(l.text) > 90 or len(l.text) < 2 or not (l.first or l.run_in):
            return False
        standard = any(r.match(l.text) for r in (SECTION_NAMES, STOP_HEADINGS, BACK_MATTER))
        if ABSTRACT.match(l.text) or standard:
            return True
        stands_out = l.bold or l.run_in or l.size >= body * 1.15
        if toc_titles:
            # figure labels can repeat a heading's words; real headings stand out
            return _key(l.text) in toc_titles and stands_out
        if l.run_in:
            return False  # bold lead-ins like "Mass spectrometry." read fine as text
        caps = l.text.isupper() and sum(c.isalpha() for c in l.text) >= 4 and len(l.text) <= 60
        return (l.size >= body * 1.15 or caps) and not l.text.endswith((".", ",", ";"))

    sections = [Section(title="")]
    para: list[str] = []
    prev: _Line | None = None

    def flush() -> None:
        if para:
            sections[-1].paragraphs.append(_join_lines(para))
            para.clear()

    for l in lines:
        if is_heading(l):
            flush()
            if stop_at_references and STOP_HEADINGS.match(l.text):
                break
            skip = BACK_MATTER.match(l.text) is not None
            # consecutive heading lines (a title wrapped over two lines) merge
            if not toc_titles and prev is not None and is_heading(prev) and not sections[-1].paragraphs:
                sections[-1].title += " " + l.text
            else:
                sections.append(Section(title=re.sub(NUMBERING, "", l.text).rstrip(".: ")))
                sections[-1].skip = skip
        else:
            new_block = prev is None or l.block != prev.block or l.page != prev.page
            # a block that continues onto the next page/column ends mid-sentence
            if new_block and para and not (l.page != prev.page and not para[-1].endswith((".", "!", "?", ":", '"'))):
                flush()
            para.append(l.text)
        prev = l
    flush()

    return [s for s in sections if s.paragraphs and not s.skip]
