# Tex2vois

**Listen to articles and research papers in a natural voice — speech runs on your laptop; the optional AI parts use free models.**

Most "PDF to speech" tools read everything on the page: running headers, page numbers, `[12]`-style citations,
author emails, figure labels, table cells. Tex2vois treats it as a pipeline problem: understand the page layout,
keep only what a human narrator would read, optionally let a local LLM make it speakable, then synthesise it
with a small, high-quality neural voice and package it as an audiobook with chapters.

```
PDF ──► layout-aware extraction ──► rule-based cleanup ──► (optional) local LLM rewrite ──► Kokoro-82M TTS ──► M4B / MP3
         PyMuPDF                     regex                  Ollama + length guard            on-device        ffmpeg, loudnorm, chapters
```

## Three ways to listen

| | Input | What you get | AI needed? |
|---|---|---|---|
| **Article** | pasted text | the whole text, read naturally | no |
| **Research paper** | PDF | **Summary** (~2 min) → **Skim** (key parts, ~⅙–⅓) → **Full** reading | summary/skim: yes (free); full: no |
| **Book** | EPUB/PDF | chapter-by-chapter audiobook | *coming next* |

Every paragraph has a stable id, and each skim paragraph records which full-text paragraph it came from;
a `.cues.json` file next to the audio gives each paragraph's start time, so a player can jump from the
skim straight into the full reading at the same point.

## Features

- **Layout-aware extraction.** Drops repeated headers/footers and page numbers, author blocks above the
  abstract, footnotes (by font size), rotated margin text (e.g. arXiv stamps), text inside or hugging
  figures, figure/table captions, and everything after *References*. Re-joins words hyphenated across lines
  while keeping real compounds (`English-to-German`).
- **Chapters.** Taken from the PDF outline when present (matched against bold/large lines so figure labels
  can't fake a heading), else detected by font size. Exported as real chapter markers in `.m4b`.
- **Speakable text.** Removes numeric and author-year citations, URLs and emails; expands `e.g.`, `i.e.`,
  `Fig. 3`, `vs.` and friends.
- **Free AI, fact-checked.** Summaries, methods recaps and the optional "rewrite for listening" pass use free
  OpenRouter models (falling back through a list when one is rate-limited) or a local Ollama model. Two guards:
  a **length guard** (rewrite must stay within 0.6–1.6× the original) and a **fact guard** — every number,
  gene/protein-style name (`HhCHC`, `dsRNA-CHC`, `AtMYB75`) and abbreviated species (`A. thaliana`) must survive a
  rewrite, and a summary may not mention any number or name that is not in the paper. Anything that fails falls
  back to the paper's own words (e.g. the abstract), and the app says so.
- **Research-paper layouts.** Run-in headings ("1. Introduction. Life is…"), ALL-CAPS headings, bioRxiv margin line
  numbers, superscript citation markers (exponents like N³ are kept and read as "N cubed"), and back matter
  (acknowledgements, funding, author contributions, conflicts of interest) are all handled.
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

**AI features (summary, skim, rewrite)**

Option A — free cloud models via [OpenRouter](https://openrouter.ai) (no cost; free models are rate-limited):

```bash
cp .env.example .env            # then put your key in .env:  OPENROUTER_API_KEY=sk-or-v1-...
```

Only `:free` models are used unless you set `TEX2VOIS_ALLOW_PAID=1`. Override the model list with
`TEX2VOIS_MODELS="model-a:free,model-b:free"` (the free catalogue changes often).

Option B — fully local with [Ollama](https://ollama.com):

```bash
ollama pull qwen2.5:7b          # 16 GB RAM; use llama3.2:3b on 8 GB machines
export TEX2VOIS_LLM=ollama
```

```bash
tex2vois paper.pdf --mode summary           # ~2 minute spoken summary
tex2vois paper.pdf --mode skim --script     # print the skim, no audio
tex2vois paper.pdf --rewrite                # full reading, smoothed for listening (slow)
tex2vois paper.pdf --mode skim --no-llm     # skim from the paper's own words only
pbpaste | tex2vois - -o article.mp3         # an article from the clipboard
```

## Project layout

```
src/tex2vois/
  extract.py    PDF -> sections (layout heuristics)
  clean.py      rule-based cleanup for speech
  script.py     Script/Chapter/Para model; from_pdf, from_text (articles)
  modes.py      paper modes: full, skim, summary
  llm.py        OpenRouter (free models, fallback) / Ollama client, .env loading
  rewrite.py    optional LLM rewrite + length and fact guards
  tts.py        Kokoro synthesis, sentence chunking, voices
  audio.py      ffmpeg assembly: loudnorm, chapters, M4B/MP3/WAV
  pipeline.py   load -> mode -> rewrite -> speech; timing report and .cues.json
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
- [ ] Book mode: EPUB input, background generation that can pause and resume
- [ ] Player that switches between skim and full at the same paragraph (uses `.cues.json`)
- [ ] "Paste a DOI": fetch open full-text XML from Europe PMC / bioRxiv before falling back to the PDF
- [ ] Pronunciation lexicon for species, genes and reagents (plant and molecular biology first)

## License

MIT. Kokoro-82M weights are Apache-2.0.
