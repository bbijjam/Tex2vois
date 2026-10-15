"""Command line.

  tex2vois paper.pdf                        full reading -> paper.m4b
  tex2vois paper.pdf --mode summary         2-minute spoken summary (LLM)
  tex2vois paper.pdf --mode skim --script   print the skim script, no audio
  tex2vois article.txt                      pasted article saved as text
  pbpaste | tex2vois - -o article.mp3       straight from the clipboard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
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
    ap.add_argument("--kind", default="auto", choices=["auto", "article", "paper"], help="input kind [default: auto from file type]")
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

        report = pipeline.convert(
            source, args.output or default_out, kind=args.kind, mode=args.mode, voice=args.voice, speed=args.speed,
            use_llm=args.rewrite, llm=llm, title=args.title, max_pages=args.pages, progress=_bar,
        )
    except (ValueError, RuntimeError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    for note in report.script.notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
