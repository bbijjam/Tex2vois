"""Books: EPUB / plain-text (e.g. Project Gutenberg) input, and resumable generation.

A novel is 8-12 hours of audio, so books are generated chapter by chapter into
a work folder with a manifest. Stopping keeps finished chapters; running again
resumes with the next one. Finished chapters can be played (with captions)
while later ones are still being generated, and `assemble` joins them into a
single .m4b with chapter markers.
"""

from __future__ import annotations

import hashlib
import html
import json
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from . import clean
from .audio import _escape, ffmpeg
from .script import Chapter, Para, Script

WORDS_PER_MINUTE = 155  # measured with Kokoro at speed 1.0, including pauses

SKIP_TITLES = re.compile(
    r"^\s*(cover|title ?page|half ?title|copyright|contents|table of contents|index|colophon|imprint"
    r"|also by .*|about the (author|publisher)|praise for .*|dedication|epigraph"
    r"|.*project gutenberg.*license.*|the full project gutenberg.*)\s*$",
    re.I,
)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman(s: str) -> int | None:
    s = s.upper()
    if not s or any(c not in ROMAN for c in s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN[a]
        total += -v if b != " " and ROMAN.get(b, 0) > v else v
    return total


def _capwords(text: str) -> str:
    """'ALICE'S ADVENTURES' -> "Alice's Adventures" (str.title() would give "Alice'S")."""
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split())


def _same(a: str, b: str) -> bool:
    norm = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())
    return norm(a) == norm(b)


def speakable_title(title: str) -> str:
    """'CHAPTER XII. Alice's Evidence' -> 'Chapter 12. Alice's Evidence'."""
    title = re.sub(r"\s+", " ", title).strip()

    def fix(m: re.Match) -> str:
        n = _roman(m.group(2))
        return f"{m.group(1).capitalize()} {n if n else m.group(2)}"

    title = re.sub(r"\b(chapter|part|book|volume)\s+([IVXLCDM]+|\d+)\b", fix, title, flags=re.I)
    if title.isupper():
        title = _capwords(title)
    return title.rstrip(".") if title.count(".") == 1 and title.endswith(".") else title


# ---------------------------------------------------------------- EPUB

class _Text(HTMLParser):
    """XHTML -> paragraphs; first heading kept separately."""

    BLOCK = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "dd", "dt", "pre", "section"}
    SKIP = {"script", "style", "head", "nav", "aside", "figcaption", "table", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paras: list[str] = []
        self.heading: str | None = None
        self.link_chars = 0
        self.skip = 0
        self.sup = 0
        self.link = 0
        self.buf: list[str] = []
        self.in_heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP or "footnote" in (attrs.get("epub:type") or "") or attrs.get("role") == "doc-footnote":
            self.skip += 1
        elif tag == "sup":
            self.sup += 1
        elif tag == "a":
            self.link += 1
        elif tag == "br":
            self.buf.append(" ")
        elif tag in self.BLOCK:
            self._flush()
            self.in_heading = tag in ("h1", "h2", "h3")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "sup":
            self.sup = max(0, self.sup - 1)
        elif tag == "a":
            self.link = max(0, self.link - 1)
        elif tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self.skip or (self.sup and re.fullmatch(r"\s*[\d*†‡]+\s*", data)):
            return  # footnotes and note markers
        if self.link:
            self.link_chars += len(data.strip())
        self.buf.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if text:
            if self.in_heading and self.heading is None:
                self.heading = text
            else:
                self.paras.append(text)
        self.in_heading = False

    def close(self):
        super().close()
        self._flush()


def _epub_toc(z: zipfile.ZipFile, opf_dir: str, manifest: dict[str, tuple[str, str]], nav_id: str | None, ncx_id: str | None) -> dict[str, str]:
    """file path -> first title the table of contents gives it."""
    titles: dict[str, str] = {}
    if nav_id:
        href = posixpath.join(opf_dir, manifest[nav_id][0])
        nav_dir = posixpath.dirname(href)
        for m in re.finditer(r'<a[^>]+href="([^"#]+)[^"]*"[^>]*>(.*?)</a>', z.read(href).decode("utf-8", "replace"), re.S):
            path = posixpath.normpath(posixpath.join(nav_dir, m.group(1)))
            titles.setdefault(path, html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))))
    elif ncx_id:
        href = posixpath.join(opf_dir, manifest[ncx_id][0])
        ncx_dir = posixpath.dirname(href)
        root = ET.fromstring(z.read(href))
        for point in root.iter():
            if point.tag.endswith("navPoint"):
                label = next((t.text for t in point.iter() if t.tag.endswith("text")), None)
                src = next((c.get("src") for c in point.iter() if c.tag.endswith("content")), None)
                if label and src:
                    titles.setdefault(posixpath.normpath(posixpath.join(ncx_dir, src.split("#")[0])), label)
    return titles


def from_epub(path: str | Path) -> Script:
    with zipfile.ZipFile(path) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
        opf_dir = posixpath.dirname(opf_path)
        opf = ET.fromstring(z.read(opf_path))
        book_title = next((e.text for e in opf.iter() if e.tag.endswith("}title") and e.text), Path(path).stem)
        manifest, nav_id, ncx_id = {}, None, None
        for item in opf.iter():
            if item.tag.endswith("item"):
                manifest[item.get("id")] = (item.get("href"), item.get("media-type", ""))
                if "nav" in (item.get("properties") or "").split():
                    nav_id = item.get("id")
                if item.get("media-type") == "application/x-dtbncx+xml":
                    ncx_id = item.get("id")
        spine = [i.get("idref") for i in opf.iter() if i.tag.endswith("itemref") and i.get("linear", "yes") != "no"]
        toc = _epub_toc(z, opf_dir, manifest, nav_id, ncx_id)

        chapters: list[tuple[str, list[str]]] = []
        for idref in spine:
            href, mtype = manifest.get(idref, (None, ""))
            if not href or "html" not in mtype:
                continue
            file = posixpath.normpath(posixpath.join(opf_dir, href))
            parser = _Text()
            parser.feed(z.read(file).decode("utf-8", "replace"))
            parser.close()
            words = sum(len(p.split()) for p in parser.paras)
            total_chars = sum(len(p) for p in parser.paras) or 1
            title = toc.get(file) or parser.heading or ""
            if SKIP_TITLES.match(title) or parser.link_chars / total_chars > 0.5 or words < 20:
                continue  # cover, contents, copyright, licence, near-empty pages
            if words < 300 and _same(title, book_title):
                continue  # title page
            if words < 600 and any("project gutenberg" in p.lower() for p in parser.paras[:3]):
                continue  # Gutenberg header/footer pages
            paras = [p for p in (clean.clean(x) for x in parser.paras) if p and not clean.is_noise(p)]
            if paras:
                chapters.append((speakable_title(title or parser.heading or f"Part {len(chapters) + 1}"), paras))
    if not chapters:
        raise ValueError("No readable chapters found in this EPUB (is it DRM-protected?).")
    return _script(book_title, chapters)


# ---------------------------------------------------------------- plain text

CHAPTER_LINE = re.compile(r"^\s*(chapter|book|part)\s+([IVXLCDM]+|\d+|[a-z]+)\b.*$", re.I)


def from_book_text(text: str, title: str | None = None) -> Script:
    """Plain-text books: strips Project Gutenberg boilerplate, splits on 'CHAPTER ...' lines."""
    text = text.replace("\r\n", "\n")
    start = re.search(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*$", text, re.M | re.I)
    end = re.search(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG.*$", text, re.M | re.I)
    if start and not title:
        m = re.search(r"EBOOK (.+?) \*\*\*", start.group(0), re.I)
        title = _capwords(m.group(1)) if m else None
    text = text[start.end() if start else 0 : end.start() if end else len(text)]

    lines = text.split("\n")
    chapters: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    para: list[str] = []

    def flush():
        if para and current is not None:
            current[1].append(" ".join(para))
        para.clear()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if CHAPTER_LINE.match(line):
            flush()
            heading = line
            # a short title line right after "CHAPTER I." belongs to the heading
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and len(lines[j].strip()) < 70 and not lines[j].strip().endswith((".", ",", ";", '"', "”")) \
                    and not CHAPTER_LINE.match(lines[j].strip()) and re.match(r"\w", lines[j].strip()):
                heading += " " + lines[j].strip()
                i = j
            current = (speakable_title(heading), [])
            chapters.append(current)
        elif not line:
            flush()
        elif not re.fullmatch(r"[\*\s]+|\[Illustration[^\]]*\]", line):
            para.append(line)
        i += 1
    flush()
    chapters = [(t, [p for p in (clean.clean(x) for x in ps) if p and not clean.is_noise(p)]) for t, ps in chapters]
    chapters = [(t, ps) for t, ps in chapters if ps]  # the contents list leaves empty chapters
    if len(chapters) < 2:
        raise ValueError("Could not find chapter headings (lines like 'CHAPTER I').")
    return _script(title or "Untitled book", chapters)


def looks_like_book(text: str) -> bool:
    return len([l for l in text.splitlines() if CHAPTER_LINE.match(l.strip())]) >= 3


def _script(title: str, chapters: list[tuple[str, list[str]]]) -> Script:
    out = [Chapter(t, [Para(f"c{ci}p{pi}", p) for pi, p in enumerate(ps, 1)], "chapter") for ci, (t, ps) in enumerate(chapters, 1)]
    return Script(title, out, kind="book")


def load(path: str | Path) -> Script:
    from .script import from_pdf

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return from_epub(path)
    if suffix in (".txt", ".md"):
        return from_book_text(path.read_text(encoding="utf-8", errors="replace"), None)
    if suffix == ".pdf":
        script = from_pdf(str(path))
        script.kind = "book"
        return script
    raise ValueError(f"Unsupported book format '{suffix}'. Use .epub, .txt or .pdf.")


# ---------------------------------------------------------------- resumable generation

def chapter_plan(script: Script) -> list[dict]:
    plan = []
    for i, ch in enumerate(script.chapters):
        words = sum(len(p.text.split()) for p in ch.paras)
        plan.append({"index": i, "title": ch.title, "words": words, "minutes": round(words / WORDS_PER_MINUTE, 1)})
    return plan


def work_dir(root: Path, source: Path, voice: str, speed: float) -> Path:
    """Same book + voice + speed -> same folder, so a rerun resumes."""
    digest = hashlib.sha1(source.read_bytes() + f"|{voice}|{speed:.2f}".encode()).hexdigest()[:10]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", source.stem).strip("-")[:40] or "book"
    path = root / f"{slug}-{digest}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest(folder: Path) -> dict:
    f = folder / "manifest.json"
    return json.loads(f.read_text()) if f.exists() else {"done": {}}


def _save_manifest(folder: Path, data: dict) -> None:
    tmp = folder / "manifest.json.tmp"
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(folder / "manifest.json")  # atomic: a stop mid-write never corrupts it


def chapter_file(folder: Path, index: int) -> Path:
    return folder / f"chapter-{index + 1:03d}.mp3"


def finished(folder: Path) -> dict[int, dict]:
    """index -> {title, seconds} for chapters whose audio exists."""
    done = _manifest(folder)["done"]
    return {int(k): v for k, v in done.items() if chapter_file(folder, int(k)).exists()}


def generate(script: Script, folder: Path, chapters: list[int], voice: str, speed: float,
             synthesizer=None, progress=None, on_chapter=None) -> dict[int, dict]:
    """Generate the selected chapters that are not finished yet. Safe to stop and rerun."""
    from .pipeline import speak

    say = progress or (lambda f, m: None)
    data = _manifest(folder)
    data.update({"title": script.title, "voice": voice, "speed": speed})
    todo = [i for i in chapters if i not in finished(folder)]
    total_words = sum(sum(len(p.text.split()) for p in script.chapters[i].paras) for i in todo) or 1
    words_done = 0
    for i in todo:
        ch = script.chapters[i]
        words = sum(len(p.text.split()) for p in ch.paras)
        base, share = words_done / total_words, words / total_words

        def chapter_progress(f, m, base=base, share=share, title=ch.title):
            say(base + share * min(f, 1.0) * 0.98, f"{title}: {m}")

        one = Script(script.title, [ch], "book")
        out, seconds, _, _, _ = speak(one, chapter_file(folder, i), voice, speed, synthesizer, chapter_progress, start=0.0)
        data["done"][str(i)] = {"title": ch.title, "seconds": round(seconds, 2)}
        _save_manifest(folder, data)
        words_done += words
        if on_chapter:
            on_chapter(i)
    say(1.0, "Done")
    return finished(folder)


def assemble(folder: Path, out_path: Path, title: str) -> Path:
    """Join finished chapters (in order) into one .m4b with chapter markers."""
    done = finished(folder)
    if not done:
        raise ValueError("No finished chapters yet.")
    order = sorted(done)
    with tempfile.TemporaryDirectory() as tmp:
        listing, meta = Path(tmp) / "list.txt", Path(tmp) / "meta.txt"
        listing.write_text("".join(f"file '{chapter_file(folder, i).resolve()}'\n" for i in order))
        lines, start = [";FFMETADATA1", f"title={_escape(title)}", "artist=Tex2vois", "genre=Audiobook"], 0
        for i in order:
            end = start + round(done[i]["seconds"] * 1000)
            lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_escape(done[i]['title'])}"]
            start = end
        meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
               "-i", str(meta), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
               "-c:a", "aac", "-b:a", "64k", "-f", "mp4", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()}")
    return out_path
