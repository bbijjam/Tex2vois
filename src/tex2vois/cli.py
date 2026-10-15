"""Command line.

  tex2vois paper.pdf                        full reading -> paper.m4b
  tex2vois paper.pdf --mode summary         2-minute spoken summary (LLM)
  tex2vois paper.pdf --mode skim --script   print the skim script, no audio
  tex2vois article.txt                      pasted article saved as text
  pbpaste | tex2vois - -o article.mp3       straight from the clipboard
  tex2vois novel.epub                       audiobook, chapter by chapter; Ctrl+C and rerun to resume
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import book, pipeline
from .llm import LLM, LLMError
from .modes import MODES
from .tts import DEFAULT_VOICE, VOICES


def _bar(fraction: float, message: str) -> None:
    width = 30
    filled = int(width * fraction)
    sys.stderr.write(f"\r[{'#' * filled}{'.' * (width - filled)}] {fraction:4.0%}  {message[:50]:<50}")
    sys.stderr.flush()
    if fraction >= 1:
        sys.stderr.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tex2vois", description="Turn articles and papers into audio, offline-first.")
    ap.add_argument("input", help="a .pdf, a .txt/.md file, or - to read pasted text from stdin")
    ap.add_argument("-o", "--output", type=Path, help="output .m4b (chapters), .mp3 or .wav [default: <input>.m4b]")
    ap.add_argument("--kind", default="auto", choices=["auto", "article", "paper", "book"], help="input kind [default: auto from file type]")
    ap.add_argument("--chapters", help="book chapters to generate, e.g. 1-3,7 [default: all]")
    ap.add_argument("--mode", default="full", choices=MODES, help="full reading, skim, or spoken summary [default: full]")
    ap.add_argument("-v", "--voice", default=DEFAULT_VOICE, choices=VOICES, help=f"voice [default: {DEFAULT_VOICE}]")
    ap.add_argument("-s", "--speed", type=float, default=1.0, help="speaking rate, 0.5-2.0 [default: 1.0]")
    ap.add_argument("--title", help="title for pasted text")
    ap.add_argument("--rewrite", action="store_true", help="LLM rewrite for listening (fact-checked)")
    ap.add_argument("--provider", choices=["auto", "openrouter", "ollama"], help="LLM provider [default: env TEX2VOIS_LLM or auto]")
    ap.add_argument("--model", help="LLM model id(s), comma-separated, tried in order")
    ap.add_argument("--no-llm", action="store_true", help="never call an LLM (skim/summary become purely extractive)")
    ap.add_argument("--pages", type=int, help="only the first N pages of a PDF")
    ap.add_argument("--script", action="store_true", help="print the text that would be spoken and exit (no audio)")
    ap.add_argument("--list-voices", action="store_true", help="list voices and exit")
    args = ap.parse_args(argv)

    if args.list_voices:
        for name, desc in VOICES.items():
            print(f"{name:12} {desc}")
        return 0

    source: str | Path
    if args.input == "-":
        source = sys.stdin.read()
        default_out = Path("article.m4b")
    else:
        source = Path(args.input)
        if not source.exists():
            ap.error(f"file not found: {source}")
        default_out = source.with_suffix(".m4b")

    try:
        llm = None
        if not args.no_llm and (args.rewrite or args.mode != "full"):
            try:
                llm = LLM.from_env(args.provider, args.model)
            except LLMError as e:
                if args.rewrite:
                    raise
                print(f"note: no LLM ({e}); using extractive {args.mode}", file=sys.stderr)

        if args.script:
            script, stats = pipeline.prepare(source, args.kind, args.mode, args.rewrite, llm, args.title, args.pages)
            print(f"# {script.title}  [{script.kind} / {script.mode}, {script.words:,} words]\n")
            print(script.to_markdown())
            if llm and llm.last_model:
                print(f"\n(LLM: {llm.last_model})", file=sys.stderr)
            for note in script.notes:
                print(f"note: {note}", file=sys.stderr)
            return 0

        out = args.output or default_out
        script = pipeline.load(source, args.kind, args.title, args.pages) if isinstance(source, Path) else None
        if script is not None and script.kind == "book" and not args.script:
            return _book(script, out, args)

        report = pipeline.convert(
            source, out, kind=args.kind, mode=args.mode, voice=args.voice, speed=args.speed,
            use_llm=args.rewrite, llm=llm, title=args.title, max_pages=args.pages, progress=_bar,
        )
    except (ValueError, RuntimeError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    for note in report.script.notes:
        print(f"note: {note}")
    return 0


def _parse_chapters(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(n))
    picked: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        picked.update(range(int(a), int(b or a) + 1))
    return [i - 1 for i in sorted(picked) if 1 <= i <= n]


def _book(script, out: Path, args) -> int:
    plan = book.chapter_plan(script)
    chosen = _parse_chapters(args.chapters, len(plan))
    folder = out.with_suffix(".parts")
    folder.mkdir(parents=True, exist_ok=True)
    done = book.finished(folder)
    hours = sum(plan[i]["minutes"] for i in chosen) / 60
    print(f"{script.title}: {len(chosen)} chapters, ~{hours:.1f} h of audio; {len([i for i in chosen if i in done])} already done")
    try:
        book.generate(script, folder, chosen, args.voice, args.speed, progress=_bar)
    except KeyboardInterrupt:
        print(f"\nPaused. Finished chapters are kept in {folder}; run the same command again to resume.")
        return 130
    final = book.assemble(folder, out.with_suffix(".m4b"), script.title)
    print(f"Audiobook: {final}  ({len(book.finished(folder))} chapters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
