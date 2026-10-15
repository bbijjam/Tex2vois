"""Command line: tex2vois paper.pdf -o paper.m4b"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline, rewrite
from .tts import DEFAULT_VOICE, VOICES


def _bar(fraction: float, message: str) -> None:
    width = 30
    filled = int(width * fraction)
    sys.stderr.write(f"\r[{'#' * filled}{'.' * (width - filled)}] {fraction:4.0%}  {message[:50]:<50}")
    sys.stderr.flush()
    if fraction >= 1:
        sys.stderr.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tex2vois", description="Turn a PDF into an audiobook, fully offline.")
    ap.add_argument("pdf", type=Path, help="input PDF")
    ap.add_argument("-o", "--output", type=Path, help="output file: .m4b (chapters), .mp3 or .wav [default: <pdf>.m4b]")
    ap.add_argument("-v", "--voice", default=DEFAULT_VOICE, choices=VOICES, help=f"voice [default: {DEFAULT_VOICE}]")
    ap.add_argument("-s", "--speed", type=float, default=1.0, help="speaking rate, 0.5-2.0 [default: 1.0]")
    ap.add_argument("--llm", action="store_true", help="rewrite text for listening with a local LLM (Ollama)")
    ap.add_argument("--model", default=rewrite.DEFAULT_MODEL, help=f"Ollama model for --llm [default: {rewrite.DEFAULT_MODEL}]")
    ap.add_argument("--pages", type=int, help="only convert the first N pages")
    ap.add_argument("--script", action="store_true", help="print the text that would be spoken and exit (no audio)")
    ap.add_argument("--list-voices", action="store_true", help="list voices and exit")
    args = ap.parse_args(argv)

    if args.list_voices:
        for name, desc in VOICES.items():
            print(f"{name:12} {desc}")
        return 0
    if not args.pdf.exists():
        ap.error(f"file not found: {args.pdf}")

    try:
        if args.script:
            script, _ = pipeline.prepare(args.pdf, args.llm, args.model, args.pages)
            for title, paras in script:
                print(f"\n## {title}\n")
                print("\n\n".join(paras))
            return 0

        out = args.output or args.pdf.with_suffix(".m4b")
        report = pipeline.convert(
            args.pdf, out, voice=args.voice, speed=args.speed, use_llm=args.llm,
            llm_model=args.model, max_pages=args.pages, progress=_bar,
        )
    except (ValueError, RuntimeError, rewrite.OllamaError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
