"""Audio player with synced, auto-scrolling captions.

`render()` returns static HTML (an <audio> element plus the transcript, one
<span> per spoken sentence carrying its start/end time). `JS` holds one
global script (passed to Gradio's launch(js=...), which runs it on page load) that drives every player on the page: media events don't bubble
but they do reach capturing listeners on `document`, so no per-render script
execution is needed. Clicking a sentence seeks to it; manual scrolling pauses
auto-scroll for a few seconds.
"""

from __future__ import annotations

import html
from itertools import groupby

CSS = """
/* Palette: warm neutrals, one ink-blue accent, a highlighter-yellow for the current sentence.
   Every colour has an explicit dark-mode value (Gradio adds .dark to the page in dark mode). */
:root {
  --t2v-surface: #ffffff;
  --t2v-surface-2: #f7f6f3;
  --t2v-border: #e3e0da;
  --t2v-text: #1f1d1a;
  --t2v-muted: #5f5a52;
  --t2v-accent: #1f4d7a;
  --t2v-mark: #fbe7a1;
  --t2v-mark-text: #1f1d1a;
  --t2v-para: #f6f1e3;
}
.dark {
  --t2v-surface: #1c1c1e;
  --t2v-surface-2: #232325;
  --t2v-border: #3a3a3d;
  --t2v-text: #ececea;
  --t2v-muted: #b3afa8;
  --t2v-accent: #9cc3ec;
  --t2v-mark: #6b5a1e;
  --t2v-mark-text: #fff8e1;
  --t2v-para: #2a2721;
}
.t2v-player { display: flex; flex-direction: column; gap: 10px; }
.t2v-player audio { width: 100%; height: 44px; }
.dark .t2v-player audio { color-scheme: dark; }
.t2v-captions {
  height: 25vh; min-height: 170px; overflow-y: auto; padding: 14px 18px;
  border: 1px solid var(--t2v-border); border-radius: 8px; background: var(--t2v-surface);
  font-family: 'Literata', Georgia, 'Times New Roman', serif;
  font-size: 1.08rem; line-height: 1.75; color: var(--t2v-text); scroll-behavior: smooth;
}
.t2v-captions h4 { margin: 16px 0 6px; font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: .82rem;
  font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--t2v-muted); }
.t2v-captions h4:first-child { margin-top: 0; }
.t2v-captions p { margin: 0 0 12px; padding: 2px 6px; border-radius: 4px; transition: background .2s; }
.t2v-captions p.t2v-para-on { background: var(--t2v-para); }
.t2v-captions .t2v-s { cursor: pointer; border-radius: 3px; transition: background .15s; }
.t2v-captions .t2v-s:hover { text-decoration: underline; text-decoration-color: var(--t2v-muted); text-underline-offset: 3px; }
.t2v-captions .t2v-s.t2v-on { background: var(--t2v-mark); color: var(--t2v-mark-text); box-shadow: 0 0 0 2px var(--t2v-mark); }
.t2v-captions h4.t2v-on { color: var(--t2v-accent); }
.t2v-hint { font-size: .85rem; color: var(--t2v-muted); }

.t2v-notes { display: flex; flex-direction: column; gap: 8px; }
.t2v-notes-bar { display: flex; align-items: center; gap: 8px; }
.t2v-notes-bar strong { flex: 1; font-size: 1rem; font-weight: 600; color: var(--t2v-text); }
.t2v-notes textarea {
  width: 100%; box-sizing: border-box; height: 25vh; min-height: 170px; resize: vertical;
  padding: 12px 14px; border-radius: 8px; font: inherit; font-size: .97rem; line-height: 1.55;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); color: var(--t2v-text);
}
.t2v-notes textarea::placeholder { color: var(--t2v-muted); opacity: 1; }
.t2v-notes textarea:focus { outline: 2px solid var(--t2v-accent); outline-offset: -1px; }
.t2v-icon-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  min-width: 38px; height: 36px; padding: 0 12px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); color: var(--t2v-text);
  font: inherit; font-size: .88rem; font-weight: 500;
}
.t2v-icon-btn:hover { border-color: var(--t2v-accent); color: var(--t2v-accent); }
.t2v-icon-btn:focus-visible { outline: 2px solid var(--t2v-accent); outline-offset: 2px; }
.t2v-icon-btn svg { width: 18px; height: 18px; }
"""

DOWNLOAD_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>'
)

NOTES = f"""
<div class="t2v-notes">
  <div class="t2v-notes-bar">
    <strong>Your notes</strong>
    <button type="button" class="t2v-icon-btn" data-t2v="stamp" title="Add the current moment to your notes">Mark this moment</button>
    <button type="button" class="t2v-icon-btn" data-t2v="download" title="Save your notes to your computer" aria-label="Save notes">{DOWNLOAD_ICON}</button>
  </div>
  <textarea class="t2v-notes-text" placeholder="Jot down thoughts while you listen. Your notes stay in this browser, and the download button saves a copy."></textarea>
</div>
"""

JS = r"""
() => {
  if (window.__t2vPlayer) return;
  window.__t2vPlayer = true;
  const pauseUntil = new WeakMap();

  function update(audio) {
    const root = audio.closest('.t2v-player');
    if (!root) return;
    const box = root.querySelector('.t2v-captions');
    const t = audio.currentTime;
    let current = null;
    for (const el of box.querySelectorAll('[data-start]')) {
      if (t >= +el.dataset.start) current = el; else break;
    }
    const prev = box.querySelector('.t2v-on');
    if (current === prev) return;
    if (prev) prev.classList.remove('t2v-on');
    box.querySelectorAll('.t2v-para-on').forEach(p => p.classList.remove('t2v-para-on'));
    if (!current) return;
    current.classList.add('t2v-on');
    const para = current.closest('p');
    if (para) para.classList.add('t2v-para-on');
    if ((pauseUntil.get(box) || 0) < Date.now()) {
      const top = current.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - box.clientHeight / 3;
      box.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    }
  }

  document.addEventListener('timeupdate', e => {
    if (e.target.matches && e.target.matches('.t2v-player audio')) update(e.target);
  }, true);
  document.addEventListener('seeked', e => {
    if (e.target.matches && e.target.matches('.t2v-player audio')) {
      const box = e.target.closest('.t2v-player').querySelector('.t2v-captions');
      pauseUntil.delete(box);
      update(e.target);
    }
  }, true);

  // click a sentence to jump there
  document.addEventListener('click', e => {
    const s = e.target.closest && e.target.closest('.t2v-player [data-start]');
    if (!s) return;
    const audio = s.closest('.t2v-player').querySelector('audio');
    audio.currentTime = +s.dataset.start + 0.01;
    audio.play();
  });

  // ---- notes: kept in this browser (localStorage), downloadable as Markdown ----
  const NOTES_KEY = 't2v-notes';
  const allBoxes = () => [...document.querySelectorAll('.t2v-notes-text')];
  const notesBox = (from) => (from && from.closest('.t2v-notes')?.querySelector('.t2v-notes-text')) || allBoxes()[0];
  const syncAll = (value, except) => allBoxes().forEach(b => { if (b !== except) b.value = value; });
  const store = {
    get() { try { return localStorage.getItem(NOTES_KEY) || ''; } catch (e) { return ''; } },
    set(v) { try { localStorage.setItem(NOTES_KEY, v); } catch (e) {} },
  };
  // the notes panel may render after this script runs
  new MutationObserver(() => {
    allBoxes().forEach(box => {
      if (!box.dataset.t2vReady) { box.dataset.t2vReady = '1'; box.value = store.get(); }
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('input', e => {
    if (e.target.classList && e.target.classList.contains('t2v-notes-text')) {
      store.set(e.target.value);
      syncAll(e.target.value, e.target);
    }
  });

  const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const activePlayer = () => {
    const all = [...document.querySelectorAll('.t2v-player')].filter(p => p.offsetParent !== null);  // visible tab only
    return all.find(p => !p.querySelector('audio').paused) || all[all.length - 1];
  };

  document.addEventListener('click', e => {
    const btn = e.target.closest && e.target.closest('[data-t2v]');
    if (!btn) return;
    const box = notesBox(btn);
    if (!box) return;
    if (btn.dataset.t2v === 'stamp') {
      const p = activePlayer();
      let line = '- ';
      if (p) {
        const t = p.querySelector('audio').currentTime;
        const s = p.querySelector('.t2v-on');
        line = `- [${fmt(t)}]` + (s ? ` "${s.textContent.trim()}"` : '') + ' ';
      }
      const at = box.selectionStart ?? box.value.length;
      const before = box.value.slice(0, at), after = box.value.slice(at);
      const insert = (before && !before.endsWith('\n') ? '\n' : '') + line;
      box.value = before + insert + after;
      box.selectionStart = box.selectionEnd = before.length + insert.length;
      box.focus();
      store.set(box.value);
      syncAll(box.value, box);
    }
    if (btn.dataset.t2v === 'download') {
      const p = activePlayer();
      const title = p ? p.querySelector('audio').getAttribute('aria-label') : 'Tex2vois';
      const date = new Date().toISOString().slice(0, 10);
      const body = `Notes: ${title}\n${date}\n\n${box.value.trim()}\n`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([body], { type: 'text/plain' }));
      a.download = `notes-${title.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'tex2vois'}-${date}.txt`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }
  });

  // the reader scrolled by hand: let them look around for a few seconds
  for (const type of ['wheel', 'touchmove', 'keydown']) {
    document.addEventListener(type, e => {
      const box = e.target.closest && e.target.closest('.t2v-captions');
      if (box) pauseUntil.set(box, Date.now() + 4000);
    }, { capture: true, passive: true });
  }
}
"""


def _attr(seconds: float) -> str:
    return f"{seconds:.3f}"


def render(audio_url: str, captions: list[dict], title: str = "") -> str:
    """HTML for the player. `captions` come from pipeline.speak()."""
    body: list[str] = []
    for chapter, items in groupby(captions, key=lambda c: c["chapter"]):
        items = list(items)
        for c in items:
            if c["kind"] == "title":
                body.append(f'<h4 data-start="{_attr(c["start"])}">{html.escape(c["text"])}</h4>')
        for _, sentences in groupby((c for c in items if c["kind"] == "text"), key=lambda c: c["para"]):
            spans = " ".join(
                f'<span class="t2v-s" data-start="{_attr(c["start"])}" data-end="{_attr(c["end"])}">{html.escape(c["text"])}</span>'
                for c in sentences
            )
            body.append(f"<p>{spans}</p>")
    label = html.escape(title) if title else "Tex2vois audio"
    return (
        f'<div class="t2v-player">'
        f'<audio controls preload="metadata" src="{html.escape(audio_url, quote=True)}" aria-label="{label}"></audio>'
        f'<div class="t2v-captions" tabindex="0" aria-label="Captions">{"".join(body)}</div>'
        f'<div class="t2v-hint">The words light up as they are read. Click any sentence to jump to it.</div>'
        f"</div>"
    )
