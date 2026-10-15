"""PDF -> chapters of plain text.

Strips running headers/footers and page numbers, rejoins hyphenated words,
detects chapter headings (from the PDF outline, or by font size), and stops at
the references section.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

MARGIN = 0.08  # top/bottom fraction of a page where headers/footers live
STOP_HEADINGS = re.compile(
    r"^\s*(\d+\.?\s*)?(references|bibliography|works cited|literature cited)\s*$", re.I
)
ABSTRACT = re.compile(r"^\s*abstract\s*$", re.I)
FOOTNOTE_SCALE = 0.92  # lines this much smaller than body text are footnotes
CAPTION = re.compile(r"^(figure|fig\.|table|algorithm)\s*\d+[.:]", re.I)
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.I)


@dataclass
class Section:
    title: str
    paragraphs: list[str] = field(default_factory=list)

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


def _norm(text: str) -> str:
    """Key for spotting repeated headers: case-folded, digits masked."""
    return re.sub(r"\d+", "#", text.strip().lower())


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
            block_lines = block.get("lines", [])
            if block_lines and CAPTION.match(text_of(block_lines[0])):
                continue  # figure/table captions mean nothing without the figure
            for line in block_lines:
                if abs(line["dir"][1]) > 0.1:  # rotated text: arXiv stamps, margin notes
                    continue
                bbox = pymupdf.Rect(line["bbox"])
                if any(_is_figure_label(bbox, text_of(line), r) for r in figures):
                    continue
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = text_of(line)
                size = max(spans, key=lambda s: len(s["text"]))["size"]
                bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
                y0, y1 = line["bbox"][1], line["bbox"][3]
                lines.append(_Line(text, round(size, 1), pno, y0, y1, height, block_id, bold))
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


def document_title(pdf_path: str) -> str:
    """PDF metadata title, else the largest text on the first page."""
    with pymupdf.open(pdf_path) as doc:
        meta = (doc.metadata or {}).get("title", "").strip()
        if meta and not meta.lower().startswith(("microsoft word", "untitled")):
            return meta
        first = [l for l in _read_lines(doc, 1) if len(l.text) > 3]
    return max(first, key=lambda l: l.size).text if first else ""


def extract(pdf_path: str, stop_at_references: bool = True, max_pages: int | None = None) -> list[Section]:
    """Return the document as a list of sections, in reading order."""
    with pymupdf.open(pdf_path) as doc:
        n_pages = min(len(doc), max_pages) if max_pages else len(doc)
        toc_titles = {_norm(title) for _, title, _ in doc.get_toc()}
        lines = _drop_headers_footers(_read_lines(doc, max_pages), n_pages)

    body = _body_size(lines)
    lines = _drop_front_matter([l for l in lines if l.size >= body * FOOTNOTE_SCALE])

    def is_heading(l: _Line) -> bool:
        if len(l.text) > 90 or len(l.text) < 2:
            return False
        if ABSTRACT.match(l.text):
            return True
        if toc_titles:
            # figure labels can repeat a heading's words; real headings stand out
            return _norm(l.text) in toc_titles and (l.bold or l.size >= body * 1.15)
        return l.size >= body * 1.15 and not l.text.endswith((".", ",", ";"))

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
            # consecutive heading lines (a title wrapped over two lines) merge
            if not toc_titles and prev is not None and is_heading(prev) and not sections[-1].paragraphs:
                sections[-1].title += " " + l.text
            else:
                sections.append(Section(title=l.text))
        else:
            new_block = prev is None or l.block != prev.block or l.page != prev.page
            # a block that continues onto the next page/column ends mid-sentence
            if new_block and para and not (l.page != prev.page and not para[-1].endswith((".", "!", "?", ":", '"'))):
                flush()
            para.append(l.text)
        prev = l
    flush()

    return [s for s in sections if s.paragraphs]
