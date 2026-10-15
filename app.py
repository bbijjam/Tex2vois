"""Tex2vois web app: listen to articles, research papers and books, with live captions and notes.

Run:  python app.py   (then open http://127.0.0.1:7860)
"""

from __future__ import annotations

import functools
import json
import mimetypes
import re
import tempfile
import time
from pathlib import Path

import gradio as gr

from tex2vois import assistant, book, pipeline, player, themes, triage
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
EMPTY = """<div class="t2v-player t2v-empty-player"><div class="t2v-stage">
<div class="t2v-np-label">Now playing</div><div class="t2v-np-title">{title}</div>
<div class="t2v-np-chapter">{hint}</div></div></div>"""


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
    what = {"summary": "a quick summary", "skim": "the highlights", "full": "the whole text",
            "assistant": "the script from your assistant"}[s.mode]
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


def triage_prompt(pdf, focus, context, use_context):
    """Instructions for Claude / ChatGPT, plus the paper's cleaned text for the 'with text' copy button."""
    if pdf is None:
        return "", ""
    try:
        title, body = _paper_text(pdf)
    except (ValueError, RuntimeError) as e:
        raise gr.Error(f"Sorry, this paper couldn't be read. {e}")
    return triage.build(title, focus, context=context if use_context else ""), body


COPY_PLAIN_JS = r'''(prompt) => {
  if (!prompt) return 'Add a paper first.';
  navigator.clipboard.writeText(prompt);
  return 'Copied. Open Claude or ChatGPT, paste the instructions, and attach the PDF.';
}'''
COPY_FULL_JS = r'''(prompt, text) => {
  if (!prompt) return 'Add a paper first.';
  const fence = '"' + '"' + '"';
  const full = prompt.replace(/the attached (research )?paper/, (m, r) => 'the ' + (r || '') + 'paper text included below')
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


def _paper_text(pdf) -> tuple[str, str]:
    """(title, cleaned body) of an uploaded paper; cached so editing other fields doesn't re-read the PDF."""
    path = Path(pdf)
    return _read_paper(str(path), path.stat().st_mtime)


@functools.lru_cache(maxsize=8)
def _read_paper(path: str, mtime: float) -> tuple[str, str]:
    script = pipeline.load(Path(path), "paper")
    body = "\n\n".join(f"{c.title}\n\n" + "\n\n".join(p.text for p in c.paras) for c in script.chapters)
    return script.title, body


def deep_prepare(pdf, length, context, use_context):
    context = context if use_context else ""
    minutes = triage.LENGTHS.get(length, 10)
    if pdf is None:
        return triage.build_script_prompt("", context=context, minutes=minutes), ""
    try:
        title, body = _paper_text(pdf)
    except (ValueError, RuntimeError) as e:
        raise gr.Error(f"Sorry, this paper couldn't be read. {e}")
    return triage.build_script_prompt(title, context=context, minutes=minutes), body


CONTEXT_LABEL = "About your work (optional, remembered in this browser)"
CONTEXT_HINT = ("For example: I study RNAi-based pest control in soybean and need delivery methods that work in the field. "
                "Saved only in this browser, so you don't have to type it again. Clear it to forget it.")


def context_field():
    with gr.Group():
        box = gr.Textbox(label=CONTEXT_LABEL, lines=2, max_lines=6, placeholder=CONTEXT_HINT)
        use = gr.Checkbox(label="Use it this time", value=True)
    return box, use


def deep_load_file(file):
    if file is None:
        return gr.skip()
    return Path(file).read_text(encoding="utf-8", errors="replace")


def _check_note(script_text: str, paper_body: str) -> str:
    r = assistant.compare(script_text, paper_body)
    lines = [f"Checked against the paper: the script includes **{r['covered']} of the {r['paper_facts']}** numbers and names "
             f"in the paper ({r['coverage']:.0%})."]
    if len(script_text.split()) < 0.5 * len(paper_body.split()):
        lines[0] += " A shorter script leaves some details out by design."
    if r["not_in_paper"]:
        lines.append("In the script but not found in the paper, worth checking: " + ", ".join(r["not_in_paper"][:10]) + ".")
    if r["missing"]:
        more = f" and {len(r['missing']) - 12} more" if len(r["missing"]) > 12 else ""
        lines.append("In the paper but not in the script: " + ", ".join(r["missing"][:12]) + more + ".")
    return "\n\n".join(lines)


def run_deep(script_text, pdf, voice, speed, fmt, request: gr.Request, progress=gr.Progress()):
    if not script_text or not script_text.strip():
        raise gr.Error("Paste the script from your assistant first.")
    try:
        parsed = assistant.parse(script_text)
    except ValueError as e:
        raise gr.Error(str(e))
    session = request.session_hash
    out = OUT_DIR / f"{_slug(parsed.script.title)}-script-{int(time.time())}.{fmt}"
    try:
        report = pipeline.convert(parsed.script, out, kind="paper", voice=voice, speed=speed,
                                  synthesizer=synth, progress=_stopper(progress, session))
    except Stopped:
        raise gr.Error("Stopped. Nothing was saved.", title="Stopped")
    except (ValueError, RuntimeError) as e:
        raise gr.Error(str(e))
    finally:
        STOP_REQUESTED.discard(session)
    about = [_about(report)] + parsed.notes
    if pdf is not None:
        try:
            about.append(_check_note(parsed.script.to_markdown(), _paper_text(pdf)[1]))
        except (ValueError, RuntimeError):
            pass
    return (player.render(_url(report.output), report.captions, report.script.title),
            gr.update(value=str(report.output), visible=True), "\n\n".join(about))


DEEP_INTRO = """
<div class="t2v-triage-head">
  <h3>How it works</h3>
  <p>This is separate from the quick summary and highlights on the Research paper tab.</p>
  <ol>
    <li>Add the paper. This is optional, but it lets Tex2vois include the paper's text and check the script afterwards.</li>
    <li>Choose how long you would like to listen.</li>
    <li>Copy the instructions, open Claude or ChatGPT, paste them, attach the PDF (not needed if you copied the version with the paper's text), and send.</li>
    <li>The assistant writes the script. If it ends with "CONTINUING IN THE NEXT MESSAGE", reply "continue" until the last line says "END OF SCRIPT".</li>
    <li>Copy the assistant's whole answer with its copy button, paste it in the box below, and press Read it to me.</li>
  </ol>
</div>"""


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
body, .gradio-container { background: var(--t2v-page) !important; }
.gradio-container { max-width: 1200px !important; width: 100% !important; margin: 0 auto !important; padding-top: 14px !important; }
footer { opacity: .5; }

/* ---------- header band ---------- */
:root { --t2v-pattern: radial-gradient(circle, #ffffff16 1px, transparent 1.6px) 0 0 / 18px 18px;
        --t2v-pattern-soft: radial-gradient(circle, #ffffff0c 1px, transparent 1.6px) 0 0 / 18px 18px; }
.t2v-header { position: relative; overflow: hidden; isolation: isolate;
  display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap;
  padding: 28px 30px 26px; border-radius: 16px; background: var(--t2v-brand); color: var(--t2v-brand-text);
  box-shadow: 0 14px 34px rgba(18, 64, 63, .22); }
.t2v-header::before { content: ""; position: absolute; inset: -40px; z-index: -1; background: var(--t2v-pattern);
  animation: t2v-drift 60s linear infinite; pointer-events: none; }
@keyframes t2v-drift { from { transform: translate(0, 0); } to { transform: translate(40px, 24px); } }
.t2v-header h1 { margin: 0; font-family: 'Literata', Georgia, serif; font-size: 2.2rem; font-weight: 600; letter-spacing: -.01em;
  color: var(--t2v-brand-text); }
.t2v-header p { margin: 6px 0 0; max-width: 560px; font-size: 1.04rem; line-height: 1.5; color: var(--t2v-brand-muted); }
.t2v-header-side { display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.t2v-header-points { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.t2v-theme-pick { display: inline-flex; align-items: center; gap: 8px; font-size: .85rem; font-weight: 500; color: var(--t2v-brand-muted) !important; }
.t2v-theme-pick select { height: 36px; padding: 0 10px; border-radius: 8px; font: inherit; font-size: .9rem; cursor: pointer;
  background: #ffffff14; color: var(--t2v-brand-text); border: 1px solid #ffffff38; }
.t2v-theme-pick select:focus-visible { outline: 2px solid var(--t2v-brand-text); outline-offset: 2px; }
.t2v-theme-pick select option { color: #1d1c1a; background: #ffffff; }
.t2v-header-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.t2v-bg-pick, .t2v-bg-clear { display: inline-flex; align-items: center; height: 36px; padding: 0 12px; border-radius: 8px;
  cursor: pointer; font: inherit; font-size: .85rem; font-weight: 500; background: #ffffff14; color: var(--t2v-brand-text) !important;
  border: 1px solid #ffffff38; }
.t2v-bg-pick:hover, .t2v-bg-clear:hover { background: #ffffff24; }
.t2v-bg-pick:focus-within, .t2v-bg-clear:focus-visible { outline: 2px solid var(--t2v-brand-text); outline-offset: 2px; }
.t2v-bg-status { font-size: .8rem; color: var(--t2v-brand-muted) !important; }

/* the reader's own background picture, behind a veil so text stays readable */
:root { --t2v-bg-veil: rgba(243, 241, 236, .80); }
body.dark { --t2v-bg-veil: rgba(10, 10, 12, .74); }
html.t2v-has-bg body { background: linear-gradient(var(--t2v-bg-veil), var(--t2v-bg-veil)), var(--t2v-bg-image) center / cover fixed no-repeat !important; }
/* text that normally sits on the page gets its own backing when a picture is behind it */
html.t2v-has-bg .t2v-tabs > .tab-wrapper { background: var(--t2v-surface); border: 1px solid var(--t2v-border); border-radius: 12px; padding: 4px; }
html.t2v-has-bg .t2v-help, html.t2v-has-bg .t2v-about, html.t2v-has-bg .t2v-status {
  background: var(--t2v-surface); border: 1px solid var(--t2v-border); border-radius: 10px; padding: 8px 12px !important; }
html.t2v-has-bg gradio-app, html.t2v-has-bg .gradio-container, html.t2v-has-bg .main,
html.t2v-has-bg .wrap, html.t2v-has-bg .contain { background: transparent !important; }

/* ---------- gentle motion ---------- */
@keyframes t2v-rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes t2v-pulse { 0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--t2v-mode-on-stage) 55%, transparent); }
                       50% { box-shadow: 0 0 0 10px color-mix(in srgb, var(--t2v-mode-on-stage) 0%, transparent); } }
.t2v-header, .t2v-intro, .t2v-player, .t2v-notes, .t2v-triage { animation: t2v-rise .45s ease-out both; }
.t2v-intro { animation-delay: .05s; } .t2v-player { animation-delay: .1s; } .t2v-notes { animation-delay: .15s; }
.t2v-player.t2v-playing .t2v-ctl.t2v-play { animation: t2v-pulse 2.2s ease-in-out infinite; }
.t2v-ctl, .t2v-rate, .t2v-link-btn, .t2v-icon-btn, .t2v-bg-pick, .t2v-bg-clear, button.primary, button.secondary {
  transition: transform .15s ease, background .15s ease, border-color .15s ease, filter .15s ease; }
.t2v-ctl:hover, .t2v-link-btn:hover, .t2v-icon-btn:hover, button.primary:hover { transform: translateY(-1px); }
.t2v-ctl:active, button.primary:active { transform: translateY(0) scale(.97); }
.t2v-fill { transition: width .25s linear; }
.t2v-captions .t2v-s { transition: background .3s ease, box-shadow .3s ease, color .3s ease; }
.tabitem { animation: t2v-rise .3s ease-out both; }
@media (prefers-reduced-motion: reduce) {
  .t2v-header::before, .t2v-header, .t2v-intro, .t2v-player, .t2v-notes, .t2v-triage, .tabitem,
  .t2v-player.t2v-playing .t2v-ctl.t2v-play { animation: none !important; }
  .t2v-ctl, .t2v-rate, .t2v-fill, .t2v-captions .t2v-s, .t2v-captions p, button { transition: none !important; }
}
@media (max-width: 760px) { .t2v-header-side { align-items: flex-start; } .t2v-header-points { justify-content: flex-start; } }
.t2v-header-points span { padding: 7px 12px; border-radius: 999px; font-size: .85rem; font-weight: 500;
  background: #ffffff14; border: 1px solid #ffffff26; color: var(--t2v-brand-text); }

/* ---------- settings bar ---------- */
.t2v-settings { background: var(--t2v-surface); border: 1px solid var(--t2v-border); border-radius: 14px;
  padding: 14px 18px !important; gap: 18px !important; align-items: center !important; margin-top: 14px; }
.t2v-settings > *:not(button) { border: none !important; box-shadow: none !important; background: transparent !important; }
.t2v-settings input[type=number], .t2v-settings button[aria-label*='eset'], .t2v-settings .reset-button { display: none !important; }
.t2v-settings button { min-height: 42px; }

/* ---------- tabs ---------- */
.t2v-tabs > .tab-wrapper { margin: 16px 0 16px; }
.t2v-tabs > .tab-wrapper .tab-container { gap: 6px; }
.t2v-tabs > .tab-wrapper button[role="tab"] {
  font-size: 1rem !important; font-weight: 500 !important; color: var(--t2v-muted) !important;
  padding: 10px 16px !important; background: transparent !important; border: none !important; border-radius: 10px !important;
}
.t2v-tabs > .tab-wrapper button[role="tab"]:hover { color: var(--t2v-text) !important; background: var(--t2v-surface) !important; }
.t2v-tabs > .tab-wrapper button[role="tab"].selected { color: var(--t2v-text) !important; font-weight: 600 !important;
  background: var(--t2v-surface) !important; box-shadow: inset 0 0 0 1px var(--t2v-border); }
.t2v-tabs > .tab-wrapper button[role="tab"].selected::after { display: none !important; }

/* ---------- per-mode accents ---------- */
[class*="t2v-mode-"] { --t2v-on-mode: #ffffff; }
.dark [class*="t2v-mode-"] { --t2v-on-mode: #101413; }
[class*="t2v-mode-"] button.primary { background: var(--t2v-mode) !important; border-color: var(--t2v-mode) !important;
  color: var(--t2v-on-mode) !important; }
[class*="t2v-mode-"] button.primary:hover { filter: brightness(1.08); }
[class*="t2v-mode-"] input[type=radio]:checked, [class*="t2v-mode-"] input[type=checkbox]:checked {
  background-color: var(--t2v-mode) !important; border-color: var(--t2v-mode) !important; }
[class*="t2v-mode-"] label.selected { background: var(--t2v-mode-soft) !important; color: var(--t2v-text) !important;
  box-shadow: inset 0 0 0 1px var(--t2v-mode); }

.t2v-intro { padding: 18px 20px; border-radius: 14px; background: var(--t2v-mode-soft); border: 1px solid var(--t2v-border);
  border-left: 5px solid var(--t2v-mode); margin-bottom: 4px; }
.t2v-intro-kicker { font-size: .74rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--t2v-mode); }
.t2v-intro h2 { margin: 4px 0 4px; font-family: 'Literata', Georgia, serif; font-size: 1.35rem; font-weight: 600; color: var(--t2v-text); }
.t2v-intro p { margin: 0; color: var(--t2v-muted); line-height: 1.5; }

/* ---------- panels and text ---------- */
.t2v-help { color: var(--t2v-muted); font-size: .9rem; line-height: 1.5; margin: 8px 2px 0; }
.t2v-buttons button { min-height: 50px; font-size: 1.02rem !important; font-weight: 600 !important; border-radius: 10px !important; }
.t2v-about { font-size: .95rem; padding: 2px 4px; }
.t2v-empty-player .t2v-stage { padding-bottom: 22px; }
.t2v-empty-player .t2v-np-chapter { color: var(--t2v-stage-muted); max-width: 520px; line-height: 1.5; }
.t2v-wave { height: 46px; margin-top: 16px; border-radius: 8px; opacity: .55;
  background:
    repeating-linear-gradient(90deg, var(--t2v-mode-on-stage) 0 3px, transparent 3px 9px) center / 100% 30% no-repeat,
    repeating-linear-gradient(90deg, var(--t2v-mode-on-stage) 0 3px, transparent 3px 9px) 4px center / 100% 70% no-repeat,
    repeating-linear-gradient(90deg, var(--t2v-mode-on-stage) 0 3px, transparent 3px 9px) 2px center / 100% 50% no-repeat; }

/* instruction panels with numbered steps */
.t2v-triage { margin-top: 18px; padding: 20px 22px !important; background: var(--t2v-surface);
  border: 1px solid var(--t2v-border); border-radius: 14px; }
.t2v-deep { margin: 0 0 12px !important; }
.t2v-triage-head h3 { margin: 0 0 4px; font-family: 'Literata', Georgia, serif; font-size: 1.25rem; font-weight: 600; color: var(--t2v-text); }
.t2v-triage-head p { margin: 0 0 12px; color: var(--t2v-muted); line-height: 1.5; }
.t2v-triage-head ol { list-style: none; counter-reset: step; margin: 0 0 6px; padding: 0; }
.t2v-triage-head li { counter-increment: step; position: relative; padding: 2px 0 10px 40px; line-height: 1.5; color: var(--t2v-text); }
.t2v-triage-head li::before { content: counter(step); position: absolute; left: 0; top: 0; width: 26px; height: 26px; border-radius: 999px;
  display: grid; place-items: center; font-size: .82rem; font-weight: 700; background: var(--t2v-mode-soft); color: var(--t2v-mode);
  box-shadow: inset 0 0 0 1px var(--t2v-mode); }
.t2v-triage-actions { align-items: center !important; gap: 10px !important; }
.t2v-triage-actions button { min-height: 44px; border-radius: 10px !important; }
.t2v-links { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.t2v-links span { color: var(--t2v-muted); margin-right: 4px; }
.t2v-link-btn { display: inline-flex; align-items: center; height: 44px; padding: 0 18px; border-radius: 10px;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); color: var(--t2v-mode) !important;
  font-weight: 600; text-decoration: none !important; white-space: nowrap; }
.t2v-link-btn:hover { border-color: var(--t2v-mode); background: var(--t2v-mode-soft); }
.t2v-link-btn:focus-visible { outline: 2px solid var(--t2v-mode); outline-offset: 2px; }

@media (max-width: 760px) {
  .t2v-header { padding: 22px 20px; } .t2v-header h1 { font-size: 1.7rem; }
  .t2v-tabs > .tab-wrapper button[role="tab"] { padding: 8px 10px !important; font-size: .95rem !important; }
  .t2v-controls { gap: 8px; } .t2v-ctl { width: 36px; height: 36px; } .t2v-ctl.t2v-play { width: 48px; height: 48px; }
}
"""

HEADER = f"""
<div class="t2v-header">
  <div>
    <h1>Tex2vois</h1>
    <p>Turn articles, research papers and books into natural-sounding audio, and follow every word as it is read.</p>
  </div>
  <div class="t2v-header-side">
    {themes.picker()}
    <div class="t2v-header-points"><span>Natural voices</span><span>Live captions</span><span>Notes as you listen</span></div>
  </div>
</div>
"""


def card_title(text: str):
    gr.HTML(f'<div class="t2v-card-title">{text}</div>')


def help_text(text: str):
    gr.HTML(f'<p class="t2v-help">{text}</p>')


def mode_intro(kicker: str, title: str, text: str):
    gr.HTML(f'<div class="t2v-intro"><div class="t2v-intro-kicker">{kicker}</div><h2>{title}</h2><p>{text}</p></div>', padding=False)


def listen_panel(hint: str):
    listen = gr.HTML(empty(hint=hint), padding=False)
    about = gr.Markdown(elem_classes="t2v-about")
    download = gr.File(label="Save the audio", height=64, visible=False)
    gr.HTML(player.NOTES, padding=False)
    return listen, download, about


with gr.Blocks(title="Tex2vois") as demo:
    gr.HTML(HEADER)
    # A fixed secret so the saved value can still be read after the app restarts (it only obscures the
    # person's own note in their own browser; nothing is stored on the server).
    saved_context = gr.BrowserState("", storage_key="tex2vois-about-my-work", secret="tex2vois-about-my-work-v1")

    with gr.Row(equal_height=True, elem_classes="t2v-settings"):
        voice = gr.Dropdown(VOICE_CHOICES, value=DEFAULT_VOICE, label="Voice", scale=3)
        speed = gr.Slider(0.7, 1.5, value=1.0, step=0.05, label="Reading speed", scale=3)
        fmt = gr.Dropdown(FORMAT_CHOICES, value="m4b", label="Save as", scale=2)
        preview_btn = gr.Button("Play a sample", scale=2, size="lg")
    preview_audio = gr.Audio(label="Voice sample", interactive=False, visible=False, autoplay=True)
    preview_btn.click(preview, [voice, speed], preview_audio)

    with gr.Tabs(elem_classes="t2v-tabs"):
        with gr.Tab("Article", elem_classes="t2v-mode-article"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    mode_intro("Article", "Read anything aloud", "Paste an article, an email or your own notes and listen while the words light up.")
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

        with gr.Tab("Research paper", elem_classes="t2v-mode-paper"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    mode_intro("Research paper", "Hear a paper your way", "A two-minute summary, the highlights, or the whole paper, read clearly.")
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
                focus = gr.Textbox(label="What are you looking for in this paper? (optional)",
                                   placeholder="For example: drought tolerance in rice, or better ways to deliver RNAi to insects")
                t_ctx, t_use = context_field()
                t_prompt = gr.Textbox(label="Instructions for the assistant (you can edit them)", lines=12, max_lines=24,
                                      placeholder="Add a paper above and the instructions will appear here.")
                t_text = gr.Textbox(visible=False)
                with gr.Row(elem_classes="t2v-triage-actions"):
                    copy_plain = gr.Button("Copy instructions", variant="primary")
                    copy_full = gr.Button("Copy instructions with the paper's text")
                copy_status = gr.Markdown()
                gr.HTML(f'<div class="t2v-links"><span>Then open:</span>{ASSISTANT_LINKS}</div>', padding=False)
            t_inputs = [pdf, focus, t_ctx, t_use]
            pdf.change(triage_prompt, t_inputs, [t_prompt, t_text])
            focus.submit(triage_prompt, t_inputs, [t_prompt, t_text])
            focus.blur(triage_prompt, t_inputs, [t_prompt, t_text])
            t_use.change(triage_prompt, t_inputs, [t_prompt, t_text])
            copy_plain.click(None, [t_prompt], copy_status, js=COPY_PLAIN_JS)
            copy_full.click(None, [t_prompt, t_text], copy_status, js=COPY_FULL_JS)

        with gr.Tab("Assistant script", elem_classes="t2v-mode-assistant"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    mode_intro("Assistant script", "Your assistant explains, Tex2vois reads", "Have Claude or ChatGPT write a script of the length you choose, then listen to it here.")
                    with gr.Column(elem_classes="t2v-triage t2v-deep"):
                        gr.HTML(DEEP_INTRO, padding=False)
                        d_pdf = gr.File(label="The paper (PDF, optional)", file_types=[".pdf"], type="filepath", height=150)
                        d_length = gr.Radio(list(triage.LENGTHS), value="About 10 minutes", label="How long should it be?")
                        d_ctx, d_use = context_field()
                        d_prompt = gr.Textbox(visible=False, value=triage.build_script_prompt("", minutes=10))
                        d_text = gr.Textbox(visible=False)
                        with gr.Row(elem_classes="t2v-triage-actions"):
                            d_copy = gr.Button("Copy script instructions", variant="primary")
                            d_copy_full = gr.Button("Copy with the paper's text")
                        d_copy_status = gr.Markdown()
                        gr.HTML(f'<div class="t2v-links"><span>Then open:</span>{ASSISTANT_LINKS}</div>', padding=False)
                    script_in = gr.Textbox(label="Paste the script from your assistant", lines=12, max_lines=30,
                                           placeholder="Paste the assistant's whole answer here, including every part if it continued over several messages.")
                    script_file = gr.File(label="Or upload the script (.txt or .md)", file_types=[".txt", ".md"],
                                          type="filepath", height=100)
                    with gr.Row(elem_classes="t2v-buttons"):
                        d_go = gr.Button("Read it to me", variant="primary", scale=3)
                        d_stop = gr.Button("Stop", variant="stop", scale=1)
                with gr.Column(scale=7):
                    d_out = listen_panel("Paste the script from your assistant and press <b>Read it to me</b>.")
            d_inputs = [d_pdf, d_length, d_ctx, d_use]
            d_pdf.change(deep_prepare, d_inputs, [d_prompt, d_text])
            d_length.change(deep_prepare, d_inputs, [d_prompt, d_text])
            d_use.change(deep_prepare, d_inputs, [d_prompt, d_text])
            d_copy.click(None, [d_prompt], d_copy_status, js=COPY_PLAIN_JS)
            d_copy_full.click(None, [d_prompt, d_text], d_copy_status, js=COPY_FULL_JS)
            script_file.change(deep_load_file, script_file, script_in)
            d_job = d_go.click(run_deep, [script_in, d_pdf, voice, speed, fmt], list(d_out))
            d_stop.click(stop, None, None, cancels=[d_job])

        with gr.Tab("Book", elem_classes="t2v-mode-book"):
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    mode_intro("Book", "Turn a book into an audiobook", "Prepared chapter by chapter, so you can start listening while the rest are on the way.")
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

    # "About your work": one value, shown on two tabs, kept in this browser.
    # It is copied across and saved when the person finishes editing (leaves the box or presses Enter).
    def remember(value):
        return value, value

    for here, there in ((t_ctx, d_ctx), (d_ctx, t_ctx)):
        for finished in (here.blur, here.submit):
            finished(remember, here, [there, saved_context]).then(
                triage_prompt, t_inputs, [t_prompt, t_text]).then(deep_prepare, d_inputs, [d_prompt, d_text])
    demo.load(remember, saved_context, [t_ctx, d_ctx]).then(deep_prepare, d_inputs, [d_prompt, d_text])


if __name__ == "__main__":
    page_js = player.JS.replace("() => {", "() => {" + themes.JS, 1)
    demo.queue(default_concurrency_limit=2).launch(theme=THEME, js=page_js, css=CSS + themes.css(), allowed_paths=[str(OUT_DIR)])
