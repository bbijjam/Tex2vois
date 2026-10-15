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

from tex2vois import book, pipeline, player
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
    ("Heart · warm, American", "af_heart"),
    ("Bella · bright, American", "af_bella"),
    ("Nicole · soft, American", "af_nicole"),
    ("Michael · steady, American", "am_michael"),
    ("Fenrir · deep, American", "am_fenrir"),
    ("Puck · lively, American", "am_puck"),
    ("Emma · clear, British", "bf_emma"),
    ("George · classic narrator, British", "bm_george"),
    ("Fable · storyteller, British", "bm_fable"),
]
FORMAT_CHOICES = [("Audiobook", "m4b"), ("MP3", "mp3")]  # audiobook files keep chapters; MP3 plays anywhere
MODE_CHOICES = [
    ("Quick summary · about 2 minutes", "summary"),
    ("Highlights · the most important parts", "skim"),
    ("The whole paper", "full"),
]
EMPTY = """
<div class="t2v-empty">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
    <path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 11v2"/></svg>
  <div><strong>{title}</strong><span>{hint}</span></div>
</div>"""


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
    lines = [f"**{s.title}**", f"{_length(report.audio_seconds)} of listening · {s.words:,} words · {what}"]
    if report.llm_model:
        lines.append("Written with help from a free AI model; every number and name was checked against the original.")
    for note in s.notes:
        friendly = "The AI summary couldn't be checked, so you're hearing the paper's own abstract instead." \
            if "abstract" in note else "Part of the AI help was skipped because it couldn't be checked against the paper."
        lines.append(f"ⓘ {friendly}")
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


def stop(request: gr.Request):
    STOP_REQUESTED.add(request.session_hash)
    gr.Info("Stopping…")


# ---------------------------------------------------------------- books

def _chapter_choices(script, folder: Path | None):
    done = book.finished(folder) if folder else {}
    return [(f"{'✓ ' if i in done else ''}{c['title']}  ·  {_length(c['minutes'] * 60)}", i)
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
    resume = f"\n\n✓ {len(done)} chapters are already ready; pressing **Start** carries on from there." if done else ""
    info = (f"### {script.title}\n{len(plan)} chapters · about **{_length(total)}** of listening · "
            f"takes about {_length(total * MAKE_TIME)} to prepare{resume}")
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
                   f"✓ **{title}** is ready. {len([j for j in order if j in book.finished(folder)])} of {len(order)} done.")
    except Stopped:
        done = len([i for i in order if i in book.finished(folder)])
        yield gr.skip(), gr.skip(), f"⏸ Paused. {done} of {len(order)} chapters are ready. Press **Start** to carry on."
        return
    finally:
        STOP_REQUESTED.discard(session)
    yield gr.skip(), gr.skip(), f"✅ All {len(order)} chapters are ready. You can download the whole book below."


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

THEME = gr.themes.Soft(
    primary_hue="indigo", secondary_hue="violet", neutral_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"],
    radius_size="lg",
).set(
    body_background_fill="#f5f6fa",
    body_background_fill_dark="#0b0f17",
    block_background_fill="#ffffff",
    block_background_fill_dark="#121826",
    block_border_width="1px",
    block_border_color="#e7e9f0",
    block_border_color_dark="#232b3b",
    block_shadow="0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.05)",
    block_label_text_weight="600",
    block_label_background_fill="transparent",
    block_label_background_fill_dark="transparent",
    block_title_background_fill="transparent",
    block_title_background_fill_dark="transparent",
    block_title_text_color="*neutral_700",
    block_title_text_color_dark="*neutral_200",
    block_title_padding="0",
    block_label_padding="0",
    button_large_radius="12px",
    button_primary_background_fill="linear-gradient(135deg, *primary_500, *secondary_500)",
    button_primary_background_fill_hover="linear-gradient(135deg, *primary_600, *secondary_600)",
    button_primary_text_color="white",
)

CSS = player.CSS + """
.gradio-container { max-width: 1200px !important; width: 100% !important; margin: 0 auto !important; padding-top: 8px !important; }
footer { opacity: .45; }

/* header */
.t2v-header { display: flex; align-items: center; gap: 14px; padding: 18px 2px 6px; }
.t2v-logo { width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; color: #fff; flex: none;
  background: linear-gradient(135deg, var(--primary-500), var(--secondary-500)); box-shadow: 0 8px 22px rgba(99,102,241,.35); }
.t2v-logo svg { width: 26px; height: 26px; }
.t2v-header h1 { margin: 0; font-size: 1.75rem; font-weight: 760; letter-spacing: -.025em; }
.t2v-header p { margin: 2px 0 0; color: var(--body-text-color-subdued); font-size: 1rem; }

/* tabs as big choice cards, like a reading app's home screen */
.t2v-tabs > .tab-wrapper { margin: 10px 0 14px; }
.t2v-tabs > .tab-wrapper .tab-container { gap: 10px; border: none !important; height: auto !important; }
.t2v-tabs > .tab-wrapper button[role="tab"] {
  flex: 1; height: auto !important; padding: 14px 16px !important; border-radius: 14px !important;
  border: 1.5px solid var(--block-border-color) !important; background: var(--block-background-fill) !important;
  font-size: 1.02rem !important; font-weight: 650 !important; color: var(--body-text-color) !important;
  box-shadow: 0 1px 2px rgba(16,24,40,.04); transition: all .15s;
}
.t2v-tabs > .tab-wrapper button[role="tab"]:hover { border-color: var(--primary-300) !important; }
.t2v-tabs > .tab-wrapper button[role="tab"].selected {
  border-color: var(--primary-500) !important; color: var(--primary-600) !important;
  background: color-mix(in srgb, var(--primary-500) 7%, var(--block-background-fill)) !important;
}
.t2v-tabs > .tab-wrapper button[role="tab"].selected::after { display: none !important; }

/* settings bar: one white card */
.t2v-settings { background: var(--block-background-fill); border: 1px solid var(--block-border-color);
  border-radius: 16px; padding: 14px 16px !important; gap: 16px !important; align-items: center !important;
  box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 8px 24px rgba(16,24,40,.05); }
.t2v-settings > * { border: none !important; box-shadow: none !important; background: transparent !important; }
.t2v-settings input[type=number], .t2v-settings button[aria-label*='eset'], .t2v-settings .reset-button { display: none !important; }
.t2v-settings button { min-height: 44px; }

/* cards and text */
.t2v-card-title { font-size: 1.05rem; font-weight: 700; margin: 2px 2px 8px; }
.t2v-help { color: var(--body-text-color-subdued); font-size: .88rem; line-height: 1.45; margin: 6px 2px 0; }
.t2v-empty { display: flex; gap: 14px; align-items: center; padding: 30px 20px; border-radius: 12px;
  border: 1.5px dashed var(--block-border-color); color: var(--body-text-color-subdued); }
.t2v-empty svg { width: 34px; height: 34px; flex: none; color: var(--primary-400); }
.t2v-empty strong { display: block; color: var(--body-text-color); font-weight: 650; margin-bottom: 2px; }
.t2v-buttons button { min-height: 48px; font-size: 1.02rem !important; font-weight: 650 !important; }
.t2v-about { font-size: .95rem; }
.t2v-player audio { height: 44px; }

@media (max-width: 760px) {
  .t2v-header h1 { font-size: 1.4rem; }
  .t2v-tabs > .tab-wrapper button[role="tab"] { padding: 10px 8px !important; font-size: .92rem !important; }
}
"""

HEADER = """
<div class="t2v-header">
  <div class="t2v-logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
    <path d="M3 10v4M7 7v10M11 4v16M15 8v8M19 11v2"/></svg></div>
  <div><h1>Tex2vois</h1><p>Turn articles, research papers and books into audio, and follow along as it reads.</p></div>
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


with gr.Blocks(title="Tex2vois · listen to anything") as demo:
    gr.HTML(HEADER)

    with gr.Row(equal_height=True, elem_classes="t2v-settings"):
        voice = gr.Dropdown(VOICE_CHOICES, value=DEFAULT_VOICE, label="Voice", scale=3)
        speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="Reading speed", scale=3)
        fmt = gr.Dropdown(FORMAT_CHOICES, value="m4b", label="Save as", scale=2)
        preview_btn = gr.Button("▶  Hear this voice", scale=2, size="lg")
    preview_audio = gr.Audio(label="Voice sample", interactive=False, visible=False, autoplay=True)
    preview_btn.click(preview, [voice, speed], preview_audio)

    with gr.Tabs(elem_classes="t2v-tabs"):
        with gr.Tab("📰  Article"):
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

        with gr.Tab("🔬  Paper"):
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

        with gr.Tab("📚  Book"):
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
                        b_build = gr.Button("⬇  Download the whole book", scale=1)
                    b_file = gr.File(label="Your audiobook", height=64, visible=False)
                    gr.HTML(player.NOTES, padding=False)

            book_file.change(book_loaded, [book_file, voice, speed], [chapters, book_info, listen_to, b_player])
            b_job = b_go.click(book_generate, [book_file, chapters, voice, speed], [chapters, listen_to, b_status])
            b_stop.click(stop, None, None, cancels=[b_job])
            listen_to.change(book_listen, [book_file, listen_to, voice, speed], b_player)
            b_build.click(book_download, [book_file, voice, speed], b_file)


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2).launch(theme=THEME, js=player.JS, css=CSS, allowed_paths=[str(OUT_DIR)])
