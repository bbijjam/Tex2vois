"""Gradio UI: upload a PDF, pick a voice, get an audiobook.

Run:  python app.py   (then open http://127.0.0.1:7860)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr

from tex2vois import pipeline, rewrite
from tex2vois.tts import DEFAULT_VOICE, VOICES, Synthesizer

synth = Synthesizer()  # loaded once, shared across requests
OUT_DIR = Path(tempfile.gettempdir()) / "tex2vois"
PREVIEW_TEXT = "Hi! I'll be reading your document today. Sit back and enjoy."


def preview(voice: str, speed: float):
    return 24_000, synth.speak(PREVIEW_TEXT, voice, speed)


def run(pdf, voice, speed, use_llm, llm_model, max_pages, fmt, progress=gr.Progress()):
    if pdf is None:
        raise gr.Error("Upload a PDF first.")
    pdf = Path(pdf)
    out = OUT_DIR / f"{pdf.stem}.{fmt}"
    try:
        report = pipeline.convert(
            pdf, out, voice=voice, speed=speed, use_llm=use_llm, llm_model=llm_model,
            max_pages=int(max_pages) or None, synthesizer=synth,
            progress=lambda f, msg: progress(f, desc=msg),
        )
    except (ValueError, RuntimeError, rewrite.OllamaError) as e:
        raise gr.Error(str(e))
    script = "\n\n".join(f"## {t}\n\n" + "\n\n".join(p) for t, p in report.script)
    return str(report.output), str(report.output), f"```\n{report.summary()}\n```", script


with gr.Blocks(title="Tex2vois") as demo:
    gr.Markdown("# Tex2vois\nTurn any PDF into an audiobook, fully offline. Kokoro-82M voice, optional local LLM cleanup.")
    with gr.Row():
        with gr.Column():
            pdf = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
            voice = gr.Dropdown(
                choices=[(f"{k}  ({v})", k) for k, v in VOICES.items()], value=DEFAULT_VOICE, label="Voice"
            )
            speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="Speed")
            preview_btn = gr.Button("Preview voice", size="sm")
            preview_audio = gr.Audio(label="Voice preview", interactive=False)
            with gr.Accordion("Options", open=False):
                use_llm = gr.Checkbox(label="Rewrite for listening with a local LLM (needs Ollama)")
                llm_model = gr.Textbox(value=rewrite.DEFAULT_MODEL, label="Ollama model")
                max_pages = gr.Number(value=0, precision=0, label="Only the first N pages (0 = all)")
                fmt = gr.Radio(["m4b", "mp3", "wav"], value="m4b", label="Format (m4b keeps chapters)")
            go = gr.Button("Convert", variant="primary")
        with gr.Column():
            player = gr.Audio(label="Audiobook", interactive=False)
            download = gr.File(label="Download")
            stats = gr.Markdown()
            with gr.Accordion("What was read aloud", open=False):
                script = gr.Markdown()

    preview_btn.click(preview, [voice, speed], preview_audio)
    go.click(run, [pdf, voice, speed, use_llm, llm_model, max_pages, fmt], [player, download, stats, script])


if __name__ == "__main__":
    demo.queue().launch()
