"""Gradio UI: paste an article or upload a paper, pick a voice and a mode, listen.

Run:  python app.py   (then open http://127.0.0.1:7860)
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import gradio as gr

from tex2vois import pipeline
from tex2vois.llm import LLM, LLMError
from tex2vois.tts import DEFAULT_VOICE, VOICES, Synthesizer

synth = Synthesizer()  # loaded once, shared across requests
OUT_DIR = Path(tempfile.gettempdir()) / "tex2vois"
PREVIEW_TEXT = "Hi! I'll be reading for you today. Sit back and enjoy."
MODE_LABELS = {
    "Summary (about 2 minutes)": "summary",
    "Skim (key parts, about a third)": "skim",
    "Full reading": "full",
}


def _llm() -> LLM | None:
    try:
        return LLM.from_env()
    except LLMError:
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:50] or "tex2vois"


def preview(voice: str, speed: float):
    return 24_000, synth.speak(PREVIEW_TEXT, voice, speed)


def _run(source, kind, mode, voice, speed, rewrite, fmt, max_pages, progress):
    llm = _llm() if (rewrite or mode != "full") else None
    if rewrite and llm is None:
        raise gr.Error("LLM rewrite needs OPENROUTER_API_KEY in .env, or a running Ollama.")
    stem = _slug(Path(source).stem if isinstance(source, Path) else str(source).split("\n", 1)[0])
    out = OUT_DIR / f"{stem}-{mode}-{int(time.time())}.{fmt}"
    try:
        report = pipeline.convert(
            source, out, kind=kind, mode=mode, voice=voice, speed=speed, use_llm=rewrite, llm=llm,
            max_pages=int(max_pages) or None, synthesizer=synth, progress=lambda f, m: progress(f, desc=m),
        )
    except (ValueError, RuntimeError) as e:
        raise gr.Error(str(e))
    notes = "".join(f"\n> ⚠️ {n}" for n in report.script.notes)
    stats = f"```\n{report.summary()}\n```{notes}"
    return str(report.output), str(report.output), stats, report.script.to_markdown()


def run_article(text, voice, speed, rewrite, fmt, progress=gr.Progress()):
    if not text or not text.strip():
        raise gr.Error("Paste some text first.")
    return _run(text, "article", "full", voice, speed, rewrite, fmt, 0, progress)


def run_paper(pdf, mode_label, voice, speed, rewrite, fmt, max_pages, progress=gr.Progress()):
    if pdf is None:
        raise gr.Error("Upload a PDF first.")
    return _run(Path(pdf), "paper", MODE_LABELS[mode_label], voice, speed, rewrite, fmt, max_pages, progress)


def outputs():
    with gr.Column():
        player = gr.Audio(label="Listen", interactive=False)
        download = gr.File(label="Download")
        stats = gr.Markdown()
        with gr.Accordion("What was read aloud", open=False):
            script = gr.Markdown()
    return [player, download, stats, script]


with gr.Blocks(title="Tex2vois") as demo:
    gr.Markdown("# Tex2vois\nListen to articles and research papers. Natural voice (Kokoro-82M), runs on your machine.")

    with gr.Row():
        voice = gr.Dropdown(choices=[(f"{k}  ({v})", k) for k, v in VOICES.items()], value=DEFAULT_VOICE, label="Voice")
        speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="Speed")
        fmt = gr.Radio(["m4b", "mp3", "wav"], value="m4b", label="Format (m4b keeps chapters)")
    with gr.Row():
        preview_btn = gr.Button("Preview voice", size="sm")
        preview_audio = gr.Audio(label="Voice preview", interactive=False)
    preview_btn.click(preview, [voice, speed], preview_audio)

    with gr.Tab("Article"):
        with gr.Row():
            with gr.Column():
                text = gr.Textbox(label="Paste an article", lines=14, placeholder="Paste any text. Use '# Heading' lines for chapters.")
                a_rewrite = gr.Checkbox(label="Smooth for listening with an AI model (optional, fact-checked)")
                a_go = gr.Button("Read it to me", variant="primary")
            a_out = outputs()
        a_go.click(run_article, [text, voice, speed, a_rewrite, fmt], a_out)

    with gr.Tab("Research paper"):
        with gr.Row():
            with gr.Column():
                pdf = gr.File(label="Paper (PDF)", file_types=[".pdf"], type="filepath")
                mode = gr.Radio(list(MODE_LABELS), value="Summary (about 2 minutes)", label="What to listen to")
                p_rewrite = gr.Checkbox(label="Smooth equations and symbols with an AI model (slower, fact-checked)")
                max_pages = gr.Number(value=0, precision=0, label="Only the first N pages (0 = all)")
                p_go = gr.Button("Read it to me", variant="primary")
                gr.Markdown("Summary and skim use a free AI model via OpenRouter (or local Ollama). "
                            "Every number and gene name it says is checked against the paper; if the check fails, you hear the abstract instead.")
            p_out = outputs()
        p_go.click(run_paper, [pdf, mode, voice, speed, p_rewrite, fmt, max_pages], p_out)

    with gr.Tab("Book (coming soon)"):
        gr.Markdown("EPUB and PDF books with chapter-by-chapter generation that can pause and resume. Next on the roadmap.")


if __name__ == "__main__":
    demo.queue().launch()
