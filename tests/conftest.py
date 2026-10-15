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
