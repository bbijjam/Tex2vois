"""End-to-end: PDF -> sections -> clean (-> LLM rewrite) -> speech -> audiobook."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, clean, extract, rewrite
from .tts import DEFAULT_VOICE, SAMPLE_RATE, Synthesizer, silence, split_sentences

Progress = Callable[[float, str], None]

PAUSE_SENTENCE = 0.15
PAUSE_PARAGRAPH = 0.6
PAUSE_CHAPTER = 1.5


@dataclass
class Report:
    output: Path
    chapters: list[str]
    words: int
    audio_seconds: float
    extract_seconds: float
    rewrite_seconds: float
    tts_seconds: float
    rewrite_batches: int = 0
    rewrite_rejected: int = 0
    script: list[tuple[str, list[str]]] = field(default_factory=list, repr=False)

    @property
    def rtf(self) -> float:
        """Real-time factor of speech synthesis (<1 = faster than real time)."""
        return self.tts_seconds / self.audio_seconds if self.audio_seconds else 0.0

    def summary(self) -> str:
        m, s = divmod(round(self.audio_seconds), 60)
        lines = [
            f"Output:     {self.output}",
            f"Chapters:   {len(self.chapters)}",
            f"Words:      {self.words:,}",
            f"Audio:      {m}m {s:02d}s",
            f"Extract:    {self.extract_seconds:.1f}s",
        ]
        if self.rewrite_batches:
            lines.append(
                f"LLM rewrite:{self.rewrite_seconds:6.1f}s  ({self.rewrite_batches} batches, "
                f"{self.rewrite_rejected} rejected by length guard)"
            )
        lines.append(f"Synthesis:  {self.tts_seconds:.1f}s  (RTF {self.rtf:.2f})")
        return "\n".join(lines)


def prepare(
    pdf_path: str | Path,
    use_llm: bool = False,
    llm_model: str = rewrite.DEFAULT_MODEL,
    max_pages: int | None = None,
    progress: Progress | None = None,
) -> tuple[list[tuple[str, list[str]]], dict]:
    """Extract and clean text. Returns the 'script' [(chapter title, paragraphs)] and timings."""
    say = progress or (lambda f, m: None)
    stats = {"extract_seconds": 0.0, "rewrite_seconds": 0.0, "rewrite_batches": 0, "rewrite_rejected": 0}

    t = time.perf_counter()
    say(0.0, "Extracting text")
    sections = extract.extract(str(pdf_path), max_pages=max_pages)
    script = []
    for i, sec in enumerate(sections, 1):
        paras = [clean.clean(p) for p in sec.paragraphs]
        paras = [p for p in paras if not clean.is_noise(p)]
        if paras:
            script.append((clean.clean(sec.title) or f"Part {i}", paras))
    stats["extract_seconds"] = time.perf_counter() - t
    if not script:
        raise ValueError("No readable text found. Is this a scanned PDF? (OCR is on the roadmap.)")

    if use_llm:
        rewrite.check_ollama(llm_model)
        t = time.perf_counter()
        rewritten = []
        for i, (title, paras) in enumerate(script):
            say(0.05 + 0.25 * i / len(script), f"Rewriting for listening: {title}")
            new, batches, rejected = rewrite.rewrite_paragraphs(paras, model=llm_model)
            stats["rewrite_batches"] += batches
            stats["rewrite_rejected"] += rejected
            rewritten.append((title, new))
        script = rewritten
        stats["rewrite_seconds"] = time.perf_counter() - t
    return script, stats


def convert(
    pdf_path: str | Path,
    out_path: str | Path,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    use_llm: bool = False,
    llm_model: str = rewrite.DEFAULT_MODEL,
    max_pages: int | None = None,
    synthesizer: Synthesizer | None = None,
    progress: Progress | None = None,
) -> Report:
    say = progress or (lambda f, m: None)
    script, stats = prepare(pdf_path, use_llm, llm_model, max_pages, progress)

    tts = synthesizer or Synthesizer()
    total_chars = sum(len(p) for _, paras in script for p in paras) or 1
    done_chars = 0
    synth_start = 0.3 if use_llm else 0.05

    t = time.perf_counter()
    chapters: list[tuple[str, np.ndarray]] = []
    for title, paras in script:
        parts = [tts.speak(title + ".", voice, speed), silence(PAUSE_CHAPTER * 0.6)]
        for para in paras:
            for sentence in split_sentences(para):
                parts += [tts.speak(sentence, voice, speed), silence(PAUSE_SENTENCE)]
            parts.append(silence(PAUSE_PARAGRAPH))
            done_chars += len(para)
            say(synth_start + (0.95 - synth_start) * done_chars / total_chars, f"Speaking: {title}")
        parts.append(silence(PAUSE_CHAPTER))
        chapters.append((title, np.concatenate(parts)))
    tts_seconds = time.perf_counter() - t

    say(0.96, "Encoding audio")
    name = extract.document_title(str(pdf_path)) or Path(pdf_path).stem.replace("_", " ")
    out = audio.export(chapters, out_path, title=name)
    say(1.0, "Done")

    return Report(
        output=out,
        chapters=[c for c, _ in chapters],
        words=sum(len(p.split()) for _, paras in script for p in paras),
        audio_seconds=sum(len(a) for _, a in chapters) / SAMPLE_RATE,
        tts_seconds=tts_seconds,
        script=script,
        **stats,
    )
