import json
import subprocess
import zipfile

import numpy as np
import pytest

from tex2vois import book
from tex2vois.tts import SAMPLE_RATE


class FakeSynth:
    def __init__(self):
        self.calls = 0

    def speak(self, text, voice=None, speed=1.0):
        self.calls += 1
        return np.zeros(int(len(text) * 0.02 * SAMPLE_RATE), dtype=np.float32)


def make_epub(path):
    chapter = lambda title, body: (
        f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head><body>'
        f"<h2>{title}</h2>{body}</body></html>"
    )
    long = " ".join(["The fox ran through the quiet forest at night."] * 6)
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "OEBPS/content.opf": '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>The Fox</dc:title></metadata><manifest>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest><spine><itemref idref="toc"/><itemref idref="c1"/><itemref idref="c2"/></spine></package>',
        "OEBPS/nav.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol><li><a href="toc.xhtml">Contents</a></li>'
        '<li><a href="c1.xhtml#x">CHAPTER I. Night</a></li><li><a href="c2.xhtml">CHAPTER II. Morning</a></li></ol></nav></body></html>',
        "OEBPS/toc.xhtml": chapter("Contents", '<p><a href="c1.xhtml">Chapter I</a></p><p><a href="c2.xhtml">Chapter II</a></p>'),
        "OEBPS/c1.xhtml": chapter("CHAPTER I. Night", f"<p>{long}<sup>1</sup></p><p>It was cold.</p>"
                                  '<aside epub:type="footnote">1. A footnote nobody wants read aloud.</aside>'),
        "OEBPS/c2.xhtml": chapter("CHAPTER II. Morning", f"<p>{long}</p><p>The sun rose.</p>"),
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_epub_chapters_and_cleanup(tmp_path):
    s = book.from_epub(make_epub(tmp_path / "fox.epub"))
    assert s.title == "The Fox" and s.kind == "book"
    assert [c.title for c in s.chapters] == ["Chapter 1. Night", "Chapter 2. Morning"]  # contents page skipped
    text = " ".join(p.text for c in s.chapters for p in c.paras)
    assert "footnote" not in text and "night.1" not in text


def test_gutenberg_text():
    text = """Header junk
*** START OF THE PROJECT GUTENBERG EBOOK THE FOX ***

Contents
CHAPTER I.     Night
CHAPTER II.    Morning

CHAPTER I.
Night

The fox ran through the quiet forest. It was
cold and dark.

[Illustration]

CHAPTER II.
Morning

The sun rose over the hill.

*** END OF THE PROJECT GUTENBERG EBOOK THE FOX ***
License text."""
    s = book.from_book_text(text)
    assert s.title == "The Fox"
    assert [c.title for c in s.chapters] == ["Chapter 1. Night", "Chapter 2. Morning"]
    assert s.chapters[0].paras[0].text == "The fox ran through the quiet forest. It was cold and dark."
    assert "License" not in s.chapters[-1].paras[-1].text


def test_stop_and_resume_then_assemble(tmp_path):
    s = book.from_epub(make_epub(tmp_path / "fox.epub"))
    folder = tmp_path / "work"
    folder.mkdir()

    class Stop(Exception):
        pass

    def stop_in_chapter_two(fraction, message):
        if message.startswith("Chapter 2"):
            raise Stop

    synth = FakeSynth()
    with pytest.raises(Stop):
        book.generate(s, folder, [0, 1], "af_heart", 1.0, synth, stop_in_chapter_two)
    assert list(book.finished(folder)) == [0]  # chapter 1 kept, chapter 2 not marked done

    synth2 = FakeSynth()
    done = book.generate(s, folder, [0, 1], "af_heart", 1.0, synth2)
    assert sorted(done) == [0, 1]
    assert synth2.calls < synth.calls + 20  # chapter 1 was not regenerated
    assert json.loads(book.chapter_file(folder, 0).with_suffix(".cues.json").read_text())["captions"]

    out = book.assemble(folder, tmp_path / "fox.m4b", s.title)
    probe = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_chapters", str(out)],
                                      capture_output=True, text=True, check=True).stdout)
    assert [c["tags"]["title"] for c in probe["chapters"]] == ["Chapter 1. Night", "Chapter 2. Morning"]


def test_work_dir_is_stable(tmp_path):
    f = make_epub(tmp_path / "fox.epub")
    assert book.work_dir(tmp_path, f, "af_heart", 1.0) == book.work_dir(tmp_path, f, "af_heart", 1.0)
    assert book.work_dir(tmp_path, f, "af_heart", 1.0) != book.work_dir(tmp_path, f, "bm_fable", 1.0)
