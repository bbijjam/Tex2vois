"""End-to-end: source -> Script -> mode (full/skim/summary) -> optional LLM rewrite -> speech -> audiobook."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, book, modes
from .llm import LLM
from .rewrite import RewriteStats, rewrite_script
from .script import Script, from_pdf, from_text
from .tts import DEFAULT_VOICE, SAMPLE_RATE, Synthesizer, silence, split_sentences

Progress = Callable[[float, str], None]

PAUSE_SENTENCE = 0.15
PAUSE_PARAGRAPH = 0.6
PAUSE_CHAPTER = 1.5


@dataclass
class Report:
    output: Path
    script: Script
    audio_seconds: float
    tts_seconds: float
    prepare_seconds: float = 0.0
    rewrite: RewriteStats | None = None
    llm_model: str | None = None
    cues: list[dict] = field(default_factory=list, repr=False)
    captions: list[dict] = field(default_factory=list, repr=False)

    @property
    def rtf(self) -> float:
        """Real-time factor of speech synthesis (<1 = faster than real time)."""
        return self.tts_seconds / self.audio_seconds if self.audio_seconds else 0.0

    def summary(self) -> str:
        m, s = divmod(round(self.audio_seconds), 60)
        lines = [
            f"Output:     {self.output}",
            f"Mode:       {self.script.kind} / {self.script.mode}",
            f"Chapters:   {len(self.script.chapters)}",
            f"Words:      {self.script.words:,}",
            f"Audio:      {m}m {s:02d}s",
            f"Prepare:    {self.prepare_seconds:.1f}s" + (f"  (LLM: {self.llm_model})" if self.llm_model else ""),
        ]
        if self.rewrite and self.rewrite.batches:
            r = self.rewrite
            lines.append(
                f"Rewrite:    {r.batches} batches, kept original for {r.rejected} "
                f"(length {r.rejected_length}, facts {r.rejected_facts}, errors {r.failed})"
            )
        lines.append(f"Synthesis:  {self.tts_seconds:.1f}s  (RTF {self.rtf:.2f})")
        return "\n".join(lines)


def load(source: str | Path, kind: str = "auto", title: str | None = None, max_pages: int | None = None) -> Script:
    """A PDF path, a .txt/.md path, or raw pasted text."""
    path = Path(source) if isinstance(source, Path) or (len(str(source)) < 1024 and "\n" not in str(source)) else None
    if path is not None and path.suffix.lower() == ".epub":
        script = book.from_epub(path)
    elif path is not None and path.suffix.lower() == ".pdf":
        script = from_pdf(str(path), max_pages=max_pages)
    elif path is not None and path.suffix.lower() in (".txt", ".md") and path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        script = book.from_book_text(text, title) if kind == "book" or (kind == "auto" and book.looks_like_book(text)) \
            else from_text(text, title or path.stem)
    else:
        script = from_text(str(source), title)
    if kind != "auto":
        script.kind = kind
    return script


def prepare(
    source: str | Path,
    kind: str = "auto",
    mode: str = "full",
    use_llm: bool = False,
    llm: LLM | None = None,
    title: str | None = None,
    max_pages: int | None = None,
    progress: Progress | None = None,
) -> tuple[Script, RewriteStats | None]:
    """Build the script that will be spoken. `use_llm` enables the rewrite pass;
    skim/summary use the LLM whenever one is given."""
    say = progress or (lambda f, m: None)
    say(0.0, "Reading")
    script = load(source, kind, title, max_pages)
    if mode != "full":
        say(0.03, f"Building {mode}")
        script = modes.apply(script, mode, llm)
    stats = None
    if use_llm:
        if llm is None:
            raise ValueError("LLM rewrite requested but no LLM configured.")
        script, stats = rewrite_script(script, llm, progress=lambda f, m: say(0.05 + 0.25 * f, m))
    return script, stats


def speak(
    script: Script,
    out_path: str | Path,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    synthesizer: Synthesizer | None = None,
    progress: Progress | None = None,
    start: float = 0.3,
) -> tuple[Path, float, float, list[dict], list[dict]]:
    """Synthesise the script. Returns (file, audio seconds, synthesis seconds, paragraph cues, sentence captions).

    Captions carry the exact start/end of every spoken sentence (and chapter title),
    measured from the samples we generate, for synced on-screen captions.
    """
    say = progress or (lambda f, m: None)
    tts = synthesizer or Synthesizer()
    total = sum(len(p.text) for c in script.chapters for p in c.paras) or 1
    done, cues, captions = 0, [], []
    offset = 0  # samples written so far, across chapters
    t = time.perf_counter()
    chapters: list[tuple[str, np.ndarray]] = []

    def sec(samples: int) -> float:
        return round(samples / SAMPLE_RATE, 3)

    for ci, ch in enumerate(script.chapters):
        parts: list[np.ndarray] = []

        def add(chunk: np.ndarray) -> None:
            nonlocal offset
            parts.append(chunk)
            offset += len(chunk)

        title_audio = tts.speak(ch.title + ".", voice, speed)
        captions.append({"start": sec(offset), "end": sec(offset + len(title_audio)), "text": ch.title, "kind": "title", "chapter": ci})
        add(title_audio)
        add(silence(PAUSE_CHAPTER * 0.6))
        for para in ch.paras:
            cues.append({"id": para.id, "source": para.source, "chapter": ch.title, "start": sec(offset)})
            for sentence in split_sentences(para.text):
                say(start + (0.95 - start) * done / total, f"Speaking: {ch.title}")  # also a stop point
                spoken = tts.speak(sentence, voice, speed)
                captions.append({"start": sec(offset), "end": sec(offset + len(spoken)), "text": sentence, "kind": "text", "chapter": ci, "para": para.id})
                add(spoken)
                add(silence(PAUSE_SENTENCE))
            add(silence(PAUSE_PARAGRAPH))
            done += len(para.text)
            say(start + (0.95 - start) * done / total, f"Speaking: {ch.title}")
        add(silence(PAUSE_CHAPTER))
        chapters.append((ch.title, np.concatenate(parts)))
    tts_seconds = time.perf_counter() - t

    say(0.96, "Encoding audio")
    out = audio.export(chapters, out_path, title=script.title)
    out.with_suffix(".cues.json").write_text(
        json.dumps({"title": script.title, "mode": script.mode, "cues": cues, "captions": captions}, indent=1)
    )
    say(1.0, "Done")
    return out, offset / SAMPLE_RATE, tts_seconds, cues, captions


def convert(
    source: str | Path,
    out_path: str | Path,
    kind: str = "auto",
    mode: str = "full",
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    use_llm: bool = False,
    llm: LLM | None = None,
    title: str | None = None,
    max_pages: int | None = None,
    synthesizer: Synthesizer | None = None,
    progress: Progress | None = None,
) -> Report:
    t = time.perf_counter()
    script, stats = prepare(source, kind, mode, use_llm, llm, title, max_pages, progress)
    prepare_seconds = time.perf_counter() - t
    out, audio_seconds, tts_seconds, cues, captions = speak(
        script, out_path, voice, speed, synthesizer, progress, start=0.3 if (use_llm or mode != "full") else 0.05
    )
    return Report(out, script, audio_seconds, tts_seconds, prepare_seconds, stats, llm.last_model if llm else None, cues, captions)
