"""Tex2vois web app: listen to articles, research papers and books, with live captions and notes.

Run:  python app.py   (then open http://127.0.0.1:7860)
"""

from __future__ import annotations

import json
import mimetypes
import re
import tempfile
import time
from pathlib import Path

import gradio as gr

from tex2vois import book, pipeline, player, triage
from tex2vois.llm import LLM, LLMError
from tex2vois.tts import DEFAULT_VOICE, Synthesizer

synth = Synthesizer()  # loaded once, shared across requests
OUT_DIR = Path(tempfile.gettempdir()) / "tex2vois"
BOOKS_DIR = OUT_DIR / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)
mimetypes.add_type("audio/mp4", ".m4b")  # so browsers play chapterised audiobooks inline
STOP_REQUESTED: set[str] = set()  # session ids whose user pressed Stop
MAKE_TIME = 0.13  # minutes of work per minute of audio, measured on an M-series Mac
PREVIEW_TEXT = "Hi! I'll be reading for you today. Sit back and enjoy."

# Everything a visitor sees is in plain language.
VOICE_CHOICES = [
    ("Heart (warm, American)", "af_heart"),
    ("Bella (bright, American)", "af_bella"),
    ("Nicole (soft, American)", "af_nicole"),
    ("Michael (steady, American)", "am_michael"),
    ("Fenrir (deep, American)", "am_fenrir"),
    ("Puck (lively, American)", "am_puck"),
    ("Emma (clear, British)", "bf_emma"),
    ("George (classic narrator, British)", "bm_george"),
    ("Fable (storyteller, British)", "bm_fable"),
]
FORMAT_CHOICES = [("Audiobook", "m4b"), ("MP3", "mp3")]  # audiobook files keep chapters; MP3 plays anywhere
MODE_CHOICES = [
    ("Quick summary (about 2 minutes)", "summary"),
    ("Highlights (the most important parts)", "skim"),
    ("The whole paper", "full"),
]
EMPTY = """<div class="t2v-empty"><strong>{title}</strong><span>{hint}</span></div>"""


class Stopped(Exception):
    pass


def empty(title: str = "Nothing playing yet", hint: str = "Your audio will appear here, with the words highlighted as they are read.") -> str:
    return EMPTY.format(title=title, hint=hint)


def _llm() -> LLM | None:
    try:
        return LLM.from_env()
    except LLMError:
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:50] or "tex2vois"


def _url(path: Path) -> str:
    return f"/gradio_api/file={path.resolve()}"


def _length(seconds: float) -> str:
    m = round(seconds / 60)
    if seconds < 60:
        return f"{round(seconds)} seconds"
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def _stopper(progress, session):
    STOP_REQUESTED.discard(session)

    def report(fraction, message):
        if session in STOP_REQUESTED:
            raise Stopped  # checked between sentences, so work ends within seconds
        progress(fraction, desc=message)

    return report


def _about(report: pipeline.Report) -> str:
    """A plain-language note about the audio that was just made."""
    s = report.script
    what = {"summary": "a quick summary", "skim": "the highlights", "full": "the whole text"}[s.mode]
    lines = [f"**{s.title}**", f"{_length(report.audio_seconds)} of listening, {s.words:,} words, {what}."]
    if report.llm_model:
        lines.append("Written with help from a free AI model; every number and name was checked against the original.")
    for note in s.notes:
        friendly = "The AI summary couldn't be checked, so you're hearing the paper's own abstract instead." \
            if "abstract" in note else "Part of the AI help was skipped because it couldn't be checked against the paper."
        lines.append(friendly)
    return "\n\n".join(lines)


# ---------------------------------------------------------------- article & paper

def preview(voice: str, speed: float):
    return gr.update(value=(24_000, synth.speak(PREVIEW_TEXT, voice, speed)), visible=True)


def _run(source, kind, mode, voice, speed, rewrite, fmt, progress, session):
    llm = _llm() if (rewrite or mode != "full") else None
    if rewrite and llm is None:
        raise gr.Error("The AI helper isn't set up on this site, so this option is unavailable.")
    stem = _slug(Path(source).stem if isinstance(source, Path) else str(source).split("\n", 1)[0])
    out = OUT_DIR / f"{stem}-{mode}-{int(time.time())}.{fmt}"
    try:
        report = pipeline.convert(
            source, out, kind=kind, mode=mode, voice=voice, speed=speed, use_llm=rewrite, llm=llm,
            synthesizer=synth, progress=_stopper(progress, session),
        )
    except Stopped:
        raise gr.Error("Stopped. Nothing was saved.", title="Stopped")
    except (ValueError, RuntimeError) as e:
        raise gr.Error(str(e))
    finally:
        STOP_REQUESTED.discard(session)
    return (player.render(_url(report.output), report.captions, report.script.title),
            gr.update(value=str(report.output), visible=True), _about(report))


def run_article(text, voice, speed, rewrite, fmt, request: gr.Request, progress=gr.Progress()):
    if not text or not text.strip():
        raise gr.Error("Paste some text first.")
    return _run(text, "article", "full", voice, speed, rewrite, fmt, progress, request.session_hash)


def run_paper(pdf, mode, voice, speed, rewrite, fmt, request: gr.Request, progress=gr.Progress()):
    if pdf is None:
        raise gr.Error("Add a paper first (a PDF file).")
    return _run(Path(pdf), "paper", mode, voice, speed, rewrite, fmt, progress, request.session_hash)


def triage_prompt(pdf, focus):
    """Instructions for Claude / ChatGPT, plus the paper's cleaned text for the 'with text' copy button."""
    if pdf is None:
        return "", ""
    try:
        script = pipeline.load(Path(pdf), "paper")
    except (ValueError, RuntimeError) as e:
        raise gr.Error(f"Sorry, this paper couldn't be read. {e}")
    body = "\n\n".join(f"{c.title}\n\n" + "\n\n".join(p.text for p in c.paras) for c in script.chapters)
    return triage.build(script.title, focus), body


COPY_PLAIN_JS = r'''(prompt) => {
  if (!prompt) return 'Add a paper first.';
  navigator.clipboard.writeText(prompt);
  return 'Copied. Open Claude or ChatGPT, paste the instructions, and attach the PDF.';
}'''
COPY_FULL_JS = r'''(prompt, text) => {
  if (!prompt) return 'Add a paper first.';
  const fence = '"' + '"' + '"';
  const full = prompt.replace('the attached paper', 'the paper text included below')
    + '\n\nPaper text:\n' + fence + '\n' + text + '\n' + fence;
  navigator.clipboard.writeText(full);
  return 'Copied, including the paper. Open Claude or ChatGPT and paste. No need to attach anything.';
}'''
TRIAGE_INTRO = """
<div class="t2v-triage-head">
  <h3>Should I read this in depth?</h3>
  <p>Get a quick, structured verdict from Claude or ChatGPT using your own account. Tex2vois only prepares the instructions;
  nothing is sent from here.</p>
  <ol>
    <li>Add the paper above.</li>
    <li>Optionally, say what you are looking for. It is added to the instructions.</li>
    <li>Copy the instructions, then open Claude or ChatGPT and paste them.</li>
    <li>Attach the PDF in the chat, or use the second copy button, which includes the paper's text so you only need to paste.</li>
  </ol>
</div>"""
ASSISTANT_LINKS = "".join(
    f'<a class="t2v-link-btn" href="{url}" target="_blank" rel="noopener noreferrer">Open {name}</a>'
    for name, url in triage.ASSISTANTS.items()
)


def stop(request: gr.Request):
    STOP_REQUESTED.add(request.session_hash)
    gr.Info("Stopping…")


# ---------------------------------------------------------------- books

def _chapter_choices(script, folder: Path | None):
    done = book.finished(folder) if folder else {}
    return [(f"{c['title']} ({_length(c['minutes'] * 60)}{', ready' if i in done else ''})", i)
            for i, c in enumerate(book.chapter_plan(script))]


def _ready_choices(script, folder: Path):
    return [(script.chapters[i].title, i) for i in sorted(book.finished(folder))]


def book_loaded(file, voice, speed):
    if file is None:
        return (gr.update(choices=[], value=[]), "", gr.update(choices=[], value=None),
                empty("No book yet", "Add an EPUB, a plain-text book or a PDF on the left."))
    try:
        script = book.load(file)
    except (ValueError, KeyError, OSError) as e:
        raise gr.Error(f"Sorry, this book couldn't be opened. {e}")
    folder = book.work_dir(BOOKS_DIR, Path(file), voice, speed)
    plan = book.chapter_plan(script)
    total = sum(c["minutes"] for c in plan) * 60
    done = book.finished(folder)
    ready_text = "1 chapter is" if len(done) == 1 else f"{len(done)} chapters are"
    resume = f"\n\n{ready_text} already ready. Pressing **Start** carries on from there." if done else ""
    info = (f"### {script.title}\n{len(plan)} chapters, about **{_length(total)}** of listening. "
            f"Preparing all of it takes about {_length(total * MAKE_TIME)}.{resume}")
    ready = _ready_choices(script, folder)
    return (gr.update(choices=_chapter_choices(script, folder), value=[c["index"] for c in plan]), info,
            gr.update(choices=ready, value=ready[0][1] if ready else None),
            empty("Nothing to play yet", "Press Start. You can listen as soon as the first chapter is ready."))


def book_generate(file, chosen, voice, speed, request: gr.Request, progress=gr.Progress()):
    if file is None:
        raise gr.Error("Add a book first.")
    if not chosen:
        raise gr.Error("Tick at least one chapter.")
    session = request.session_hash
    script = book.load(file)
    folder = book.work_dir(BOOKS_DIR, Path(file), voice, speed)
    report = _stopper(progress, session)
    order = sorted(int(i) for i in chosen)
    try:
        for n, i in enumerate(order, 1):
            if i in book.finished(folder):
                continue
            title = script.chapters[i].title
            book.generate(script, folder, [i], voice, speed, synth,
                          lambda f, m, n=n, title=title: report((n - 1 + f) / len(order), f"Chapter {n} of {len(order)}: {title}"))
            ready = _ready_choices(script, folder)
            yield (gr.update(choices=_chapter_choices(script, folder), value=order),
                   gr.update(choices=ready, value=ready[0][1] if len(ready) == 1 else gr.skip()),
                   f"**{title}** is ready. {len([j for j in order if j in book.finished(folder)])} of {len(order)} chapters done.")
    except Stopped:
        done = len([i for i in order if i in book.finished(folder)])
        yield gr.skip(), gr.skip(), f"Paused. {done} of {len(order)} chapters are ready. Press **Start** to carry on."
        return
    finally:
        STOP_REQUESTED.discard(session)
    yield gr.skip(), gr.skip(), f"All {len(order)} chapters are ready. You can download the whole book on the right."


def book_listen(file, index, voice, speed):
    if file is None or index is None:
        return empty("Pick a chapter", "Chapters you can play appear in the list above.")
    folder = book.work_dir(BOOKS_DIR, Path(file), voice, speed)
    audio = book.chapter_file(folder, int(index))
    cues = audio.with_suffix(".cues.json")
    if not audio.exists() or not cues.exists():
        return empty("Not ready yet", "This chapter hasn't been prepared yet.")
    data = json.loads(cues.read_text())
    return player.render(_url(audio), data.get("captions", []), data.get("title", ""))


def book_download(file, voice, speed):
    if file is None:
        raise gr.Error("Add a book first.")
    script = book.load(file)
    folder = book.work_dir(BOOKS_DIR, Path(file), voice, speed)
    try:
        return gr.update(value=str(book.assemble(folder, folder / f"{_slug(script.title)}.m4b", script.title)), visible=True)
    except (ValueError, RuntimeError) as e:
        raise gr.Error("No chapters are ready yet." if "No finished" in str(e) else str(e))


# ---------------------------------------------------------------- look and feel

INK, INK_HOVER, INK_DARK, INK_DARK_HOVER = "#1f4d7a", "#173c60", "#9cc3ec", "#b8d4f2"

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.slate, secondary_hue=gr.themes.colors.slate, neutral_hue=gr.themes.colors.stone,
    font=[gr.themes.GoogleFont("IBM Plex Sans"), "system-ui", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "monospace"],
    radius_size=gr.themes.sizes.radius_sm,
).set(
    body_background_fill="#f4f2ee", body_background_fill_dark="#121213",
    body_text_color="#1f1d1a", body_text_color_dark="#ececea",
    body_text_color_subdued="#5f5a52", body_text_color_subdued_dark="#b3afa8",
    background_fill_primary="#ffffff", background_fill_primary_dark="#1c1c1e",
    background_fill_secondary="#f7f6f3", background_fill_secondary_dark="#232325",
    block_background_fill="#ffffff", block_background_fill_dark="#1c1c1e",
    block_border_color="#e3e0da", block_border_color_dark="#3a3a3d", block_border_width="1px",
    block_shadow="none", block_shadow_dark="none",
    block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
    block_label_text_color="#3d3933", block_label_text_color_dark="#d6d3cd",
    block_label_text_weight="600", block_label_padding="0",
    block_title_background_fill="transparent", block_title_background_fill_dark="transparent",
    block_title_text_color="#3d3933", block_title_text_color_dark="#d6d3cd",
    block_title_text_weight="600", block_title_padding="0",
    input_background_fill="#ffffff", input_background_fill_dark="#232325",
    input_border_color="#d6d2ca", input_border_color_dark="#45454a",
    input_border_color_focus=INK, input_border_color_focus_dark=INK_DARK,
    input_placeholder_color="#8a847a", input_placeholder_color_dark="#8f8b84",
    border_color_primary="#e3e0da", border_color_primary_dark="#3a3a3d",
    color_accent=INK, color_accent_soft="#e6eef6", color_accent_soft_dark="#1f2a36",
    checkbox_background_color_selected=INK, checkbox_background_color_selected_dark=INK_DARK,
    checkbox_border_color_selected=INK, checkbox_border_color_selected_dark=INK_DARK,
    checkbox_label_background_fill="#ffffff", checkbox_label_background_fill_dark="#232325",
    checkbox_label_background_fill_selected="#e6eef6", checkbox_label_background_fill_selected_dark="#1f2a36",
    checkbox_label_text_color_selected=INK, checkbox_label_text_color_selected_dark=INK_DARK,
    slider_color=INK, slider_color_dark=INK_DARK,
    button_primary_background_fill=INK, button_primary_background_fill_hover=INK_HOVER,
    button_primary_background_fill_dark=INK_DARK, button_primary_background_fill_hover_dark=INK_DARK_HOVER,
    button_primary_text_color="#ffffff", button_primary_text_color_dark="#0f1a26",
    button_primary_border_color=INK, button_primary_border_color_dark=INK_DARK,
    button_border_width="1px", button_border_width_dark="1px",
    button_secondary_background_fill="#ffffff", button_secondary_background_fill_dark="#232325",
    button_secondary_background_fill_hover="#f2f0ec", button_secondary_background_fill_hover_dark="#2c2c2f",
    button_secondary_text_color="#1f1d1a", button_secondary_text_color_dark="#ececea",
    button_secondary_border_color="#d6d2ca", button_secondary_border_color_dark="#45454a",
    button_cancel_background_fill="#ffffff", button_cancel_background_fill_dark="#232325",
    button_cancel_background_fill_hover="#fbefee", button_cancel_background_fill_hover_dark="#3a2524",
    button_cancel_text_color="#9b2c2c", button_cancel_text_color_dark="#f2b8b5",
    button_cancel_border_color="#e7c4c1", button_cancel_border_color_dark="#6a3a38",
    link_text_color=INK, link_text_color_dark=INK_DARK,
)

CSS = player.CSS + """
@import url('https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,600&display=swap');
.gradio-container { max-width: 1180px !important; width: 100% !important; margin: 0 auto !important; padding-top: 8px !important; }
footer { opacity: .5; }

/* header: a plain wordmark, no logo tile */
.t2v-header { padding: 22px 2px 10px; border-bottom: 1px solid var(--t2v-border); margin-bottom: 6px; }
.t2v-header h1 { margin: 0; font-family: 'Literata', Georgia, serif; font-size: 1.9rem; font-weight: 600;
  letter-spacing: -.01em; color: var(--t2v-text); }
.t2v-header p { margin: 4px 0 0; color: var(--t2v-muted); font-size: 1rem; }

/* tabs: simple underlined text tabs */
.t2v-tabs > .tab-wrapper { margin: 6px 0 14px; }
.t2v-tabs > .tab-wrapper .tab-container { gap: 4px; }
.t2v-tabs > .tab-wrapper button[role="tab"] {
  font-size: 1rem !important; font-weight: 500 !important; color: var(--t2v-muted) !important;
  padding: 10px 14px !important; background: transparent !important; border: none !important;
}
.t2v-tabs > .tab-wrapper button[role="tab"]:hover { color: var(--t2v-text) !important; }
.t2v-tabs > .tab-wrapper button[role="tab"].selected { color: var(--t2v-text) !important; font-weight: 600 !important; }
.t2v-tabs > .tab-wrapper button[role="tab"].selected::after { background: var(--t2v-accent) !important; height: 2px !important; }

/* settings bar: one quiet panel */
.t2v-settings { background: var(--t2v-surface); border: 1px solid var(--t2v-border); border-radius: 8px;
  padding: 14px 16px !important; gap: 18px !important; align-items: center !important; margin-top: 10px; }
.t2v-settings > *:not(button) { border: none !important; box-shadow: none !important; background: transparent !important; }
.t2v-settings input[type=number], .t2v-settings button[aria-label*='eset'], .t2v-settings .reset-button { display: none !important; }
.t2v-settings button { min-height: 42px; }

.t2v-card-title { font-size: 1.05rem; font-weight: 600; margin: 2px 2px 10px; color: var(--t2v-text); }
.t2v-help { color: var(--t2v-muted); font-size: .9rem; line-height: 1.5; margin: 8px 2px 0; }
.t2v-empty { display: flex; flex-direction: column; gap: 4px; padding: 26px 22px; border-radius: 8px;
  border: 1px dashed var(--t2v-border); background: var(--t2v-surface-2); color: var(--t2v-muted); }
.t2v-empty strong { color: var(--t2v-text); font-weight: 600; }
.t2v-buttons button { min-height: 46px; font-size: 1rem !important; font-weight: 600 !important; }
.t2v-about { font-size: .95rem; }

/* "should I read this in depth?" panel */
.t2v-triage { margin-top: 18px; padding: 18px 20px !important; background: var(--t2v-surface);
  border: 1px solid var(--t2v-border); border-radius: 8px; }
.t2v-triage-head h3 { margin: 0 0 4px; font-size: 1.15rem; font-weight: 600; color: var(--t2v-text); }
.t2v-triage-head p { margin: 0 0 8px; color: var(--t2v-muted); }
.t2v-triage-head ol { margin: 0 0 6px 1.2em; padding: 0; color: var(--t2v-text); line-height: 1.6; }
.t2v-triage-actions { align-items: center !important; gap: 10px !important; }
.t2v-triage-actions button { min-height: 44px; }
.t2v-links { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.t2v-links span { color: var(--t2v-muted); margin-right: 4px; }
.t2v-link-btn { display: inline-flex; align-items: center; height: 44px; padding: 0 16px; border-radius: 6px;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); color: var(--t2v-accent) !important;
  font-weight: 600; text-decoration: none !important; white-space: nowrap; }
.t2v-link-btn:hover { border-color: var(--t2v-accent); }
.t2v-link-btn:focus-visible { outline: 2px solid var(--t2v-accent); outline-offset: 2px; }

@media (max-width: 760px) {
  .t2v-header h1 { font-size: 1.5rem; }
  .t2v-tabs > .tab-wrapper button[role="tab"] { padding: 8px 10px !important; font-size: .95rem !important; }
}
"""

HEADER = """
<div class="t2v-header">
  <h1>Tex2vois</h1>
  <p>Turn articles, research papers and books into audio, and follow the words as they are read.</p>
</div>
"""


def card_title(text: str):
    gr.HTML(f'<div class="t2v-card-title">{text}</div>')


def help_text(text: str):
    gr.HTML(f'<p class="t2v-help">{text}</p>')


def listen_panel(hint: str):
    card_title("Listen")
    listen = gr.HTML(empty(hint=hint), padding=False)
    about = gr.Markdown(elem_classes="t2v-about")
    download = gr.File(label="Save the audio", height=64, visible=False)
    gr.HTML(player.NOTES, padding=False)
    return listen, download, about


with gr.Blocks(title="Tex2vois") as demo:
    gr.HTML(HEADER)

    with gr.Row(equal_height=True, elem_classes="t2v-settings"):
        voice = gr.Dropdown(VOICE_CHOICES, value=DEFAULT_VOICE, label="Voice", scale=3)
        speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="Reading speed", scale=3)
        fmt = gr.Dropdown(FORMAT_CHOICES, value="m4b", label="Save as", scale=2)
        preview_btn = gr.Button("Play a sample", scale=2, size="lg")
    preview_audio = gr.Audio(label="Voice sample", interactive=False, visible=False, autoplay=True)
    preview_btn.click(preview, [voice, speed], preview_audio)

    with gr.Tabs(elem_classes="t2v-tabs"):
        with gr.Tab("Article"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    with gr.Group():
                        text = gr.Textbox(label="Paste your text", lines=15, max_lines=30,
                                          placeholder="Paste a blog post, a news story, an email or notes…")
                    a_rewrite = gr.Checkbox(label="Make tricky parts easier to hear (uses AI, a little slower)")
                    with gr.Row(elem_classes="t2v-buttons"):
                        a_go = gr.Button("Read it to me", variant="primary", scale=3)
                        a_stop = gr.Button("Stop", variant="stop", scale=1)
                    help_text("Tip: start a line with <b>#</b> to make it a chapter heading.")
                with gr.Column(scale=7):
                    a_out = listen_panel("Paste some text and press <b>Read it to me</b>.")
            a_job = a_go.click(run_article, [text, voice, speed, a_rewrite, fmt], list(a_out))
            a_stop.click(stop, None, None, cancels=[a_job])

        with gr.Tab("Research paper"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    pdf = gr.File(label="Add a paper (PDF)", file_types=[".pdf"], type="filepath", height=190)
                    mode = gr.Radio(MODE_CHOICES, value="summary", label="What would you like to hear?")
                    p_rewrite = gr.Checkbox(label="Read equations and symbols in plain words (uses AI, slower)")
                    with gr.Row(elem_classes="t2v-buttons"):
                        p_go = gr.Button("Read it to me", variant="primary", scale=3)
                        p_stop = gr.Button("Stop", variant="stop", scale=1)
                    help_text("The summary and highlights are written with help from a free AI model. "
                              "Every number and name it mentions is checked against the paper. If anything doesn't match, "
                              "you'll hear the paper's own abstract instead.")
                with gr.Column(scale=7):
                    p_out = listen_panel("Add a paper, choose what you'd like to hear, and press <b>Read it to me</b>.")
            p_job = p_go.click(run_paper, [pdf, mode, voice, speed, p_rewrite, fmt], list(p_out))
            p_stop.click(stop, None, None, cancels=[p_job])

            with gr.Column(elem_classes="t2v-triage"):
                gr.HTML(TRIAGE_INTRO, padding=False)
                focus = gr.Textbox(label="What are you looking for? (optional)",
                                   placeholder="For example: drought tolerance in rice, or better ways to deliver RNAi to insects")
                t_prompt = gr.Textbox(label="Instructions for the assistant (you can edit them)", lines=12, max_lines=24,
                                      placeholder="Add a paper above and the instructions will appear here.")
                t_text = gr.Textbox(visible=False)
                with gr.Row(elem_classes="t2v-triage-actions"):
                    copy_plain = gr.Button("Copy instructions", variant="primary")
                    copy_full = gr.Button("Copy instructions with the paper's text")
                copy_status = gr.Markdown()
                gr.HTML(f'<div class="t2v-links"><span>Then open:</span>{ASSISTANT_LINKS}</div>', padding=False)
            pdf.change(triage_prompt, [pdf, focus], [t_prompt, t_text])
            focus.submit(triage_prompt, [pdf, focus], [t_prompt, t_text])
            focus.blur(triage_prompt, [pdf, focus], [t_prompt, t_text])
            copy_plain.click(None, [t_prompt], copy_status, js=COPY_PLAIN_JS)
            copy_full.click(None, [t_prompt, t_text], copy_status, js=COPY_FULL_JS)

        with gr.Tab("Book"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    book_file = gr.File(label="Add a book (EPUB, text file or PDF)", file_types=[".epub", ".txt", ".pdf"],
                                        type="filepath", height=190)
                    book_info = gr.Markdown()
                    chapters = gr.CheckboxGroup(label="Chapters to prepare", choices=[])
                    with gr.Row(elem_classes="t2v-buttons"):
                        b_go = gr.Button("Start", variant="primary", scale=3)
                        b_stop = gr.Button("Pause", variant="stop", scale=1)
                    b_status = gr.Markdown()
                    help_text("Books are prepared one chapter at a time, so you can start listening while the rest are on the way. "
                              "Pause whenever you like; pressing Start again carries on where it stopped.")
                with gr.Column(scale=7):
                    card_title("Listen")
                    listen_to = gr.Dropdown(label="Chapter", choices=[], value=None)
                    b_player = gr.HTML(empty("No book yet", "Add an EPUB, a plain-text book or a PDF on the left."), padding=False)
                    with gr.Row():
                        b_build = gr.Button("Download the whole book", scale=1)
                    b_file = gr.File(label="Your audiobook", height=64, visible=False)
                    gr.HTML(player.NOTES, padding=False)

            book_file.change(book_loaded, [book_file, voice, speed], [chapters, book_info, listen_to, b_player])
            b_job = b_go.click(book_generate, [book_file, chapters, voice, speed], [chapters, listen_to, b_status])
            b_stop.click(stop, None, None, cancels=[b_job])
            listen_to.change(book_listen, [book_file, listen_to, voice, speed], b_player)
            b_build.click(book_download, [book_file, voice, speed], b_file)


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(theme=THEME, js=player.JS, css=CSS, allowed_paths=[str(OUT_DIR)])
