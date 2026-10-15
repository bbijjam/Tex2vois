# Tex2vois

**Turn any PDF into a natural-sounding audiobook — fully offline, on a laptop.**

Most "PDF to speech" tools read everything on the page: running headers, page numbers, `[12]`-style citations,
author emails, figure labels, table cells. Tex2vois treats it as a pipeline problem: understand the page layout,
keep only what a human narrator would read, optionally let a local LLM make it speakable, then synthesise it
with a small, high-quality neural voice and package it as an audiobook with chapters.

```
PDF ──► layout-aware extraction ──► rule-based cleanup ──► (optional) local LLM rewrite ──► Kokoro-82M TTS ──► M4B / MP3
         PyMuPDF                     regex                  Ollama + length guard            on-device        ffmpeg, loudnorm, chapters
```

## Features

- **Layout-aware extraction.** Drops repeated headers/footers and page numbers, author blocks above the
  abstract, footnotes (by font size), rotated margin text (e.g. arXiv stamps), text inside or hugging
  figures, figure/table captions, and everything after *References*. Re-joins words hyphenated across lines
  while keeping real compounds (`English-to-German`).
- **Chapters.** Taken from the PDF outline when present (matched against bold/large lines so figure labels
  can't fake a heading), else detected by font size. Exported as real chapter markers in `.m4b`.
- **Speakable text.** Removes numeric and author-year citations, URLs and emails; expands `e.g.`, `i.e.`,
  `Fig. 3`, `vs.` and friends.
- **Optional LLM rewrite** with any Ollama model: verbalises math and symbols, smooths list/table fragments.
  A **length guard** rejects any batch whose rewrite drifts outside 0.6–1.6× the original length, so the model
  can never silently summarise or invent content — it can only fall back to the rule-cleaned text.
- **Kokoro-82M** voices (Apache-2.0), 9 curated US/UK voices, adjustable speed.
- **Audiobook output.** Loudness-normalised (−18 LUFS) M4B with chapters, MP3, or WAV; natural pauses between
  sentences, paragraphs and chapters.
- **CLI and web UI** (Gradio), with a "what was read aloud" view of the exact script.

## Benchmarks

MacBook Air M4, 16 GB, *Attention Is All You Need* (15 pages):

| Stage | Result |
|---|---|
| Extraction + cleanup | 0.4 s → 22 chapters, 4,678 words |
| Speech synthesis (Kokoro, CPU) | 248 s for 43 min of audio → **RTF 0.10 (≈10× faster than real time)** |
| Output | 21 MB M4B, mean −18.9 dB, only gaps > 2 s are the 22 chapter breaks |

**CPU vs Apple GPU for Kokoro-82M** (warm, same 36 s passage):

| Device | Synthesis time | RTF |
|---|---|---|
| CPU | 3.7 s | **0.10** |
| MPS (Apple GPU) | 6.0 s | 0.17 |

For a model this small, kernel-launch overhead outweighs the GPU's throughput, so Tex2vois defaults to CPU.

## Quickstart (macOS, Apple Silicon)

```bash
brew install ffmpeg espeak-ng
git clone https://github.com/bbijjam/Tex2vois.git && cd Tex2vois
uv venv --python 3.11 && uv pip install -e '.[dev]'     # or: python3.11 -m venv .venv && pip install -e '.[dev]'
source .venv/bin/activate
```

The Kokoro weights (~330 MB) download from Hugging Face on first run.

**Web UI**

```bash
python app.py        # http://127.0.0.1:7860
```

**CLI**

```bash
tex2vois paper.pdf                          # -> paper.m4b with chapters
tex2vois paper.pdf -o paper.mp3 -v bm_george -s 1.1
tex2vois paper.pdf --pages 5 --script       # print exactly what would be read, no audio
tex2vois --list-voices
```

**Optional: LLM rewrite**

```bash
ollama pull qwen2.5:7b          # 16 GB RAM; use llama3.2:3b on 8 GB machines
tex2vois paper.pdf --llm        # or --llm --model llama3.2:3b
```

Small models (1–3B) handle symbols like `√dk` → "the square root of dk" but struggle with full equations; 7B+
is noticeably better.

## Project layout

```
src/tex2vois/
  extract.py    PDF -> sections (layout heuristics)
  clean.py      rule-based cleanup for speech
  rewrite.py    optional Ollama rewrite + length guard
  tts.py        Kokoro synthesis, sentence chunking, voices
  audio.py      ffmpeg assembly: loudnorm, chapters, M4B/MP3/WAV
  pipeline.py   end-to-end orchestration + timing report
  cli.py        `tex2vois` command
app.py          Gradio web UI
tests/          pytest suite (generated PDFs, ffprobe-verified chapters)
```

```bash
pytest
```

## Roadmap

- [ ] OCR for scanned PDFs (Tesseract / Docling)
- [ ] TTS model shoot-out: Kokoro vs Piper vs Chatterbox (RTF + listening test)
- [ ] Ablation: raw vs rule-cleaned vs LLM-rewritten text (Whisper WER + listener ratings)
- [ ] Word-level highlighting in the UI via Whisper alignment
- [ ] MLX backend for Apple Silicon
- [ ] Docker image + Hugging Face Space demo
- [ ] EPUB and web-article input

## License

MIT. Kokoro-82M weights are Apache-2.0.
