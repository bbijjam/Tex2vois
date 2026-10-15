import pymupdf
import pytest

BODY = 11
HEADING = 16


def _page(doc, header: str, page_no: int, items: list[tuple[str, int]]):
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 30), header, fontsize=9)
    page.insert_text((290, 825), str(page_no), fontsize=9)
    y = 90
    for text, size in items:
        rect = pymupdf.Rect(72, y, 523, y + 400)
        page.insert_textbox(rect, text, fontsize=size)
        lines = max(1, len(text) * size * 0.5 // 451 + 1)
        y += int(lines * size * 1.3) + 18


@pytest.fixture
def sample_pdf(tmp_path):
    doc = pymupdf.open()
    header = "Journal of Listening Studies · Vol. 3"
    _page(doc, header, 1, [
        ("Introduction", HEADING),
        ("Reading papers aloud is hard because PDFs are full of artefacts [1, 2]. "
         "Prior work (Smith et al., 2020) focused on vision. See https://example.com for data.", BODY),
        ("Figure 1: A diagram nobody can hear.", BODY),
        ("A second paragraph explains the moti-\nvation, e.g. commuting.", BODY),
    ])
    _page(doc, header, 2, [
        ("Method", HEADING),
        ("We extract text, clean it, and synthesise speech, i.e. we build a pipeline (Lee & Park, 2021).", BODY),
    ])
    _page(doc, header, 3, [
        ("References", HEADING),
        ("[1] A. Author. A paper nobody should hear read aloud. 2019.", BODY),
    ])
    path = tmp_path / "sample.pdf"
    doc.save(path)
    return path


@pytest.fixture
def preprint_pdf(tmp_path):
    """bioRxiv-style page: margin line numbers, ALL-CAPS headings, run-in back matter."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 90
    rows = [
        ("ABSTRACT", 12, "Times-Bold"),
        ("Plants respond to light by changing their growth.", BODY, "Times-Roman"),
        ("INTRODUCTION", 12, "Times-Bold"),
        ("Arabidopsis thaliana is a model organism for plant biology.", BODY, "Times-Roman"),
        ("ACKNOWLEDGEMENTS", 12, "Times-Bold"),
        ("We thank the greenhouse staff for their help.", BODY, "Times-Roman"),
        ("RESULTS", 12, "Times-Bold"),
        ("Mutant seedlings grew longer hypocotyls in the dark.", BODY, "Times-Roman"),
        ("REFERENCES", 12, "Times-Bold"),
        ("1. A. Author. Some cited paper. 2019.", BODY, "Times-Roman"),
    ]
    for n, (text, size, font) in enumerate(rows, start=10):
        page.insert_text((40, y), str(n), fontsize=7)  # line number in the margin
        page.insert_text((90, y), text, fontsize=size, fontname=font)
        y += 40
    path = tmp_path / "preprint.pdf"
    doc.save(path)
    return path
