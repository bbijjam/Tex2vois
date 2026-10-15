import json

import pytest

from tex2vois import clean, extract, pipeline, rewrite
from tex2vois.tts import split_sentences


def test_extract_sections_and_drops_artefacts(sample_pdf):
    sections = extract.extract(str(sample_pdf))
    assert [s.title for s in sections] == ["Introduction", "Method"]
    text = " ".join(s.text for s in sections)
    assert "Journal of Listening Studies" not in text  # running header
    assert "nobody should hear" not in text  # stopped at References
    assert "motivation" in text  # hyphenation re-joined


def test_extract_keeps_references_when_asked(sample_pdf):
    sections = extract.extract(str(sample_pdf), stop_at_references=False)
    assert sections[-1].title == "References"


def test_prepare_script(sample_pdf):
    script, _ = pipeline.prepare(sample_pdf)
    text = " ".join(p for _, paras in script for p in paras)
    assert "[1, 2]" not in text
    assert "Smith et al" not in text and "Lee & Park" not in text
    assert "https://" not in text
    assert "for example" in text and "that is" in text
    assert "Figure 1" not in text  # caption dropped as noise


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Shown in prior work [3].", "Shown in prior work."),
        ("As argued (Smith, 2020), it works.", "As argued, it works."),
        ("See Fig. 2 and Eq. 3.", "See Figure 2 and Equation 3."),
        ("Cats vs. dogs", "Cats versus dogs"),
        ("Data at https://x.org/a?b=1 today.", "Data at today."),
    ],
)
def test_clean_rules(raw, expected):
    assert clean.clean(raw) == expected


def test_is_noise():
    assert clean.is_noise("Table 2: Results")
    assert clean.is_noise("∑ ∫ 3.14 = 42 + 7")
    assert not clean.is_noise("A perfectly ordinary sentence.")


def test_split_sentences_respects_limit():
    text = "Short one. Word " + ("word " * 200).strip() + ". End here."
    chunks = split_sentences(text, max_chars=100)
    assert chunks[0] == "Short one."
    assert chunks[-1] == "End here."
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks).split() == text.split()


def test_rewrite_length_guard(monkeypatch):
    replies = iter(["A faithful spoken version of the passage, roughly the same length.", "Too short."])
    monkeypatch.setattr(rewrite, "_generate", lambda *a, **k: next(replies))
    paras = ["A faithful written version of the passage, roughly the same length.", "x" * 1600]
    out, batches, rejected = rewrite.rewrite_paragraphs(paras, max_chars=100)
    assert batches == 2 and rejected == 1
    assert out == ["A faithful spoken version of the passage, roughly the same length.", "x" * 1600]
