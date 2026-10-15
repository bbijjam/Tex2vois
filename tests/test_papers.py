"""Layout rules for research papers.

The real-paper tests use PDFs that may not be redistributed, so they live
outside the repo and are skipped unless present (set TEX2VOIS_SAMPLES).
"""

import os
import re
from pathlib import Path

import pytest

from tex2vois import extract, pipeline
from tex2vois.extract import _clean_spans, _split_run_in


def span(text, x0, x1, font="Body", flags=0, size=10):
    return {"text": text, "bbox": (x0, 0, x1, 10), "font": font, "flags": flags, "size": size}


def joined(spans):
    return "".join(s["text"] for s in spans)


def test_superscript_citations_dropped_but_exponents_kept():
    line = {"spans": [span("regulation.", 0, 40), span("4,34,35", 40, 55, flags=1), span(" These", 55, 80)]}
    assert joined(_clean_spans(line)) == "regulation. These"
    line = {"spans": [span("time O(N", 0, 40), span("3", 40, 44, flags=1), span(")", 44, 46)]}
    assert joined(_clean_spans(line)) == "time O(N^3)"
    line = {"spans": [span("about 10", 0, 40), span("4", 40, 44, flags=1), span(" cells", 44, 70)]}
    assert joined(_clean_spans(line)) == "about 10^4 cells"


def test_margin_line_number_and_footnote_marks_dropped():
    line = {"spans": [span("268", 0, 12), span("Saliva was collected", 40, 120), span("†", 120, 124, flags=1)]}
    assert joined(_clean_spans(line)) == "Saliva was collected"


def test_run_in_heading_split():
    spans = [span("1. Introduction.", 0, 60, font="Sans"), span(" ", 60, 62), span("Life is", 62, 90)]
    assert _split_run_in(spans) == 2
    assert _split_run_in([span("Plain text line", 0, 90)]) == 0


def test_preprint_layout(preprint_pdf):
    sections = extract.extract(str(preprint_pdf))
    assert [s.title for s in sections] == ["ABSTRACT", "INTRODUCTION", "RESULTS"]
    text = " ".join(s.text for s in sections)
    assert "greenhouse" not in text  # acknowledgements skipped
    assert "cited paper" not in text  # stopped at references
    assert not re.search(r"\b1\d\b", text)  # no margin line numbers


SAMPLES = Path(os.environ.get("TEX2VOIS_SAMPLES", Path.home() / "Downloads"))
PAPERS = {
    # (abstract opening, early chapter, late chapter, phrase from the acknowledgements)
    "PBsample1.pdf": ("Nucleic acid secondary structure thermodynamic models have", "Introduction", "Conclusions", "M. Gonzalvo"),
    "PBsample2.pdf": ("Fluorescent dyes are critical", "INTRODUCTION", "DISCUSSION", "Maria Kurilova"),
    "PBsample3.pdf": ("The invasive pest Halyomorpha halys", "Introduction", "Discussion", "Robert Bischoff"),
}


@pytest.mark.parametrize("name", PAPERS)
def test_real_paper(name):
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} not available locally")
    abstract, first, late, thanks = PAPERS[name]
    script, _ = pipeline.prepare(path)
    titles = [c.title for c in script.chapters]
    text = re.sub(r"\s+", " ", " ".join(p.text for c in script.chapters for p in c.paras))
    assert titles[0].lower() == "abstract" and first in titles and late in titles
    assert abstract in text
    assert thanks not in text  # acknowledgements skipped
    assert not re.search(r"Author contributions|Conflict of interest|CONFLICT OF INTEREST", text)
    assert not re.search(r"[a-z][.,]\d{1,2}(,\d{1,2})+\s", text)  # superscript citation runs
    assert len(re.findall(r"(?<=\s)\d{2,3}(?= [a-z]{3,})", text)) < 30  # margin line numbers
