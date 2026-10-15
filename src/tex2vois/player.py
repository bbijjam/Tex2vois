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
/* Palette: warm neutrals, a deep teal brand colour, and one muted accent per mode
   (--t2v-mode). Every colour has an explicit dark value (Gradio adds .dark in dark mode). */
:root {
  --t2v-page: #f3f1ec; --t2v-surface: #ffffff; --t2v-surface-2: #f8f6f1; --t2v-tint: #eef3f1;
  --t2v-border: #e2ded6; --t2v-text: #1d1c1a; --t2v-muted: #5d5850;
  --t2v-brand: #12403f; --t2v-brand-text: #f2f7f5; --t2v-brand-muted: #b9d2cc;
  --t2v-accent: #1f4d7a;
  --t2v-mark: #fbe3a0; --t2v-mark-text: #1d1c1a; --t2v-para: #fbf6e8;
  --t2v-stage: #17201f; --t2v-stage-text: #f3f1ec; --t2v-stage-muted: #b7c2bf; --t2v-stage-track: #3a4644;
  --t2v-mode: #1f5f8b; --t2v-mode-soft: #e9f1f8; --t2v-mode-on-stage: #8cc3ea;
}
.dark {
  --t2v-page: #111214; --t2v-surface: #1b1c1f; --t2v-surface-2: #212226; --t2v-tint: #1c2524;
  --t2v-border: #34363b; --t2v-text: #ecebe8; --t2v-muted: #b1ada6;
  --t2v-brand: #163e3c; --t2v-brand-text: #eef6f3; --t2v-brand-muted: #a9c6bf;
  --t2v-accent: #9cc3ec;
  --t2v-mark: #6a5718; --t2v-mark-text: #fff8e0; --t2v-para: #262219;
  --t2v-stage: #0c1312; --t2v-stage-text: #eef1f0; --t2v-stage-muted: #a4b1ae; --t2v-stage-track: #2e3a38;
  --t2v-mode: #8cc3ea; --t2v-mode-soft: #1a2a37; --t2v-mode-on-stage: #8cc3ea;
}
/* one accent per mode */
.t2v-mode-article   { --t2v-mode: #1f5f8b; --t2v-mode-soft: #e9f1f8; --t2v-mode-on-stage: #8cc3ea; }
.t2v-mode-paper     { --t2v-mode: #2d6a4f; --t2v-mode-soft: #e8f3ec; --t2v-mode-on-stage: #8fd1ad; }
.t2v-mode-assistant { --t2v-mode: #8a5a12; --t2v-mode-soft: #f7efe1; --t2v-mode-on-stage: #f0c27a; }
.t2v-mode-book      { --t2v-mode: #8c3a4f; --t2v-mode-soft: #f6e9ed; --t2v-mode-on-stage: #f0a9bb; }
.dark .t2v-mode-article   { --t2v-mode: #8cc3ea; --t2v-mode-soft: #1a2a37; }
.dark .t2v-mode-paper     { --t2v-mode: #8fd1ad; --t2v-mode-soft: #182a21; }
.dark .t2v-mode-assistant { --t2v-mode: #f0c27a; --t2v-mode-soft: #2c2416; }
.dark .t2v-mode-book      { --t2v-mode: #f0a9bb; --t2v-mode-soft: #2e1c22; }

/* ---------- now-playing card ---------- */
.t2v-player { display: flex; flex-direction: column; gap: 0; border-radius: 14px; overflow: hidden;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); box-shadow: 0 10px 30px rgba(20, 24, 22, .10); }
.t2v-player audio { display: none; }
.t2v-stage { background-color: var(--t2v-stage); background-image: var(--t2v-pattern-soft, none);
  color: var(--t2v-stage-text); padding: 18px 20px 16px; }
/* Gradio's light theme colours text inside HTML blocks; keep the dark card's text light. */
.t2v-stage .t2v-np-title, .t2v-stage .t2v-ctl, .t2v-stage .t2v-rate, .t2v-stage b, .t2v-stage strong { color: var(--t2v-stage-text) !important; }
.t2v-stage .t2v-np-chapter, .t2v-stage .t2v-times, .t2v-stage .t2v-times span { color: var(--t2v-stage-muted) !important; }
.t2v-stage .t2v-np-label { color: var(--t2v-mode-on-stage) !important; }
.t2v-stage .t2v-ctl.t2v-play { color: #0c1312 !important; }
.t2v-stage .t2v-ctl *, .t2v-stage .t2v-rate * { color: inherit !important; }
.t2v-np-label { font-size: .72rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; color: var(--t2v-mode-on-stage); }
.t2v-np-title { font-family: 'Literata', Georgia, serif; font-size: 1.25rem; font-weight: 600; line-height: 1.3; margin: 4px 0 2px; }
.t2v-np-chapter { font-size: .9rem; color: var(--t2v-stage-muted); min-height: 1.3em; }
.t2v-controls { display: flex; align-items: center; gap: 12px; margin-top: 14px; }
.t2v-ctl { display: inline-grid; place-items: center; width: 40px; height: 40px; border-radius: 999px; cursor: pointer;
  border: 1px solid #ffffff2a; background: transparent; color: var(--t2v-stage-text); padding: 0; }
.t2v-ctl:hover { background: #ffffff14; }
.t2v-ctl svg { width: 20px; height: 20px; }
.t2v-ctl.t2v-play { width: 54px; height: 54px; border: none; background: var(--t2v-mode-on-stage); color: #0c1312; }
.t2v-ctl.t2v-play:hover { filter: brightness(1.08); background: var(--t2v-mode-on-stage); }
.t2v-ctl.t2v-play svg { width: 24px; height: 24px; }
.t2v-ctl:focus-visible, .t2v-rate:focus-visible, .t2v-track:focus-visible { outline: 2px solid var(--t2v-mode-on-stage); outline-offset: 3px; }
.t2v-play .t2v-i-pause, .t2v-player.t2v-playing .t2v-play .t2v-i-play { display: none; }
.t2v-player.t2v-playing .t2v-play .t2v-i-pause { display: block; }
.t2v-timeline { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 120px; }
.t2v-track { position: relative; height: 6px; border-radius: 999px; background: var(--t2v-stage-track); cursor: pointer; }
.t2v-track::before { content: ""; position: absolute; inset: -8px 0; }  /* bigger hit area */
.t2v-fill { position: absolute; inset: 0 auto 0 0; width: 0; border-radius: inherit; background: var(--t2v-mode-on-stage); }
.t2v-times { display: flex; justify-content: space-between; font-size: .78rem; color: var(--t2v-stage-muted);
  font-variant-numeric: tabular-nums; }
.t2v-rate { height: 32px; min-width: 52px; padding: 0 10px; border-radius: 8px; cursor: pointer; font: inherit; font-size: .85rem;
  font-weight: 600; border: 1px solid #ffffff2a; background: transparent; color: var(--t2v-stage-text); }
.t2v-rate:hover { background: #ffffff14; }

/* ---------- captions ---------- */
.t2v-captions {
  height: 28vh; min-height: 190px; overflow-y: auto; padding: 18px 22px; background: var(--t2v-surface);
  font-family: 'Literata', Georgia, 'Times New Roman', serif; font-size: 1.1rem; line-height: 1.8; color: var(--t2v-text);
  scroll-behavior: smooth;
}
.t2v-captions h4 { margin: 18px 0 6px; font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: .78rem;
  font-weight: 600; letter-spacing: .1em; text-transform: uppercase; color: var(--t2v-muted); }
.t2v-captions h4:first-child { margin-top: 0; }
.t2v-captions p { margin: 0 0 12px; padding: 4px 8px; border-radius: 6px; transition: background .25s, opacity .25s; }
.t2v-player.t2v-playing .t2v-captions p:not(.t2v-para-on) { opacity: .5; }
.t2v-captions p.t2v-para-on { background: var(--t2v-para); }
.t2v-captions .t2v-s { cursor: pointer; border-radius: 3px; transition: background .15s; }
.t2v-captions .t2v-s:hover { text-decoration: underline; text-decoration-color: var(--t2v-muted); text-underline-offset: 3px; }
.t2v-captions .t2v-s.t2v-on { background: var(--t2v-mark); color: var(--t2v-mark-text); box-shadow: 0 0 0 2px var(--t2v-mark); }
.t2v-captions h4.t2v-on { color: var(--t2v-mode); }
.t2v-hint { font-size: .82rem; color: var(--t2v-muted); padding: 10px 20px 12px; border-top: 1px solid var(--t2v-border);
  background: var(--t2v-surface-2); }

/* ---------- notes ---------- */
.t2v-notes { display: flex; flex-direction: column; gap: 10px; padding: 16px 18px; border-radius: 14px;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); }
.t2v-notes-bar { display: flex; align-items: center; gap: 8px; }
.t2v-notes-bar strong { flex: 1; font-size: 1rem; font-weight: 600; color: var(--t2v-text); }
.t2v-notes textarea {
  width: 100%; box-sizing: border-box; height: 22vh; min-height: 150px; resize: vertical;
  padding: 12px 14px; border-radius: 10px; font: inherit; font-size: .97rem; line-height: 1.55;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface-2); color: var(--t2v-text);
}
.t2v-notes textarea::placeholder { color: var(--t2v-muted); opacity: 1; }
.t2v-notes textarea:focus { outline: 2px solid var(--t2v-mode); outline-offset: -1px; }
.t2v-icon-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  min-width: 38px; height: 36px; padding: 0 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--t2v-border); background: var(--t2v-surface); color: var(--t2v-text);
  font: inherit; font-size: .88rem; font-weight: 500;
}
.t2v-icon-btn:hover { border-color: var(--t2v-mode); color: var(--t2v-mode); }
.t2v-icon-btn:focus-visible { outline: 2px solid var(--t2v-mode); outline-offset: 2px; }
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

  const fmtClock = s => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  };
  function paintControls(audio) {
    const root = audio.closest('.t2v-player');
    const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
    root.querySelector('.t2v-fill').style.width = pct + '%';
    root.querySelector('.t2v-track').setAttribute('aria-valuenow', Math.round(pct));
    root.querySelector('.t2v-now').textContent = fmtClock(audio.currentTime);
    if (audio.duration) root.querySelector('.t2v-total').textContent = fmtClock(audio.duration);
    let chapter = null;
    for (const h of root.querySelectorAll('.t2v-captions h4')) { if (audio.currentTime >= +h.dataset.start) chapter = h; else break; }
    if (chapter) {
      const title = root.querySelector('.t2v-np-title').textContent.trim();
      root.querySelector('.t2v-np-chapter').textContent = chapter.textContent.trim() === title ? '' : chapter.textContent;
    }
  }
  document.addEventListener('timeupdate', e => {
    if (e.target.matches && e.target.matches('.t2v-player audio')) { update(e.target); paintControls(e.target); }
  }, true);
  for (const type of ['play', 'pause', 'ended', 'loadedmetadata']) {
    document.addEventListener(type, e => {
      if (!(e.target.matches && e.target.matches('.t2v-player audio'))) return;
      e.target.closest('.t2v-player').classList.toggle('t2v-playing', !e.target.paused && !e.target.ended);
      paintControls(e.target);
    }, true);
  }
  const RATES = [1, 1.25, 1.5, 1.75, 2, 0.75];
  document.addEventListener('click', e => {
    const btn = e.target.closest && e.target.closest('.t2v-player [data-t2v-ctl]');
    if (!btn) return;
    const audio = btn.closest('.t2v-player').querySelector('audio');
    const what = btn.dataset.t2vCtl;
    if (what === 'play') audio.paused ? audio.play() : audio.pause();
    if (what === 'back') audio.currentTime = Math.max(0, audio.currentTime - 15);
    if (what === 'fwd') audio.currentTime = Math.min(audio.duration || 1e9, audio.currentTime + 15);
    if (what === 'rate') {
      const next = RATES[(RATES.indexOf(audio.playbackRate) + 1) % RATES.length] || 1;
      audio.playbackRate = next; btn.textContent = next + 'x';
    }
  });
  // seek by clicking or dragging the progress bar, or with the arrow keys
  function seekTo(track, clientX) {
    const audio = track.closest('.t2v-player').querySelector('audio');
    const r = track.getBoundingClientRect();
    if (audio.duration) audio.currentTime = Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * audio.duration;
  }
  document.addEventListener('pointerdown', e => {
    const track = e.target.closest && e.target.closest('.t2v-track');
    if (!track) return;
    seekTo(track, e.clientX);
    const move = ev => seekTo(track, ev.clientX);
    const up = () => { document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up); };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
  });
  document.addEventListener('keydown', e => {
    const track = e.target.closest && e.target.closest('.t2v-track');
    if (!track || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const audio = track.closest('.t2v-player').querySelector('audio');
    audio.currentTime += e.key === 'ArrowRight' ? 5 : -5;
    e.preventDefault();
  });
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

  // ---- motion helpers: click ripple, reveal-on-scroll, a flash after an action ----
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.addEventListener('pointerdown', e => {
    const btn = e.target.closest && e.target.closest('button, .t2v-link-btn');
    if (!btn || reduceMotion() || btn.matches('[role="tab"]')) return;
    const r = btn.getBoundingClientRect();
    const dot = document.createElement('span');
    dot.className = 't2v-ripple';
    dot.style.left = (e.clientX - r.left) + 'px'; dot.style.top = (e.clientY - r.top) + 'px';
    btn.classList.add('t2v-rippling'); btn.appendChild(dot);
    setTimeout(() => dot.remove(), 650);
  });
  const revealer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => entries.forEach(en => {
    if (en.isIntersecting) { en.target.classList.add('t2v-in'); revealer.unobserve(en.target); }
  }), { threshold: 0.08 }) : null;
  new MutationObserver(() => {
    if (!revealer) return;
    document.querySelectorAll('.t2v-triage:not(.t2v-reveal)').forEach(el => {
      el.classList.add('t2v-reveal');
      revealer.observe(el);
    });
  }).observe(document.documentElement, { childList: true, subtree: true });
  window.t2vFlash = el => { if (!el || reduceMotion()) return; el.classList.remove('t2v-flash'); void el.offsetWidth; el.classList.add('t2v-flash'); };

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
    // players that have audio (not the "nothing playing yet" card) on the visible tab
    const all = [...document.querySelectorAll('.t2v-player')].filter(p => p.offsetParent !== null && p.querySelector('audio'));
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
      window.t2vFlash && window.t2vFlash(box);
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


ICONS = {
    "play": '<svg class="t2v-i-play" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
    "pause": '<svg class="t2v-i-pause" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6.5" y="5" width="4" height="14" rx="1.2"/><rect x="13.5" y="5" width="4" height="14" rx="1.2"/></svg>',
    "back": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 4v4.5h4.5"/><text x="12" y="15.2" text-anchor="middle" font-size="7" font-family="system-ui" font-weight="700" fill="currentColor" stroke="none">15</text></svg>',
    "fwd": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.4-5.7"/><path d="M20 4v4.5h-4.5"/><text x="12" y="15.2" text-anchor="middle" font-size="7" font-family="system-ui" font-weight="700" fill="currentColor" stroke="none">15</text></svg>',
}


def _clock(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render(audio_url: str, captions: list[dict], title: str = "") -> str:
    """HTML for the now-playing card. `captions` come from pipeline.speak()."""
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
    first_chapter = next((html.escape(c["text"]) for c in captions if c["kind"] == "title"), "")
    if first_chapter == label:
        first_chapter = ""  # an article's only chapter is its title
    duration = _clock(captions[-1]["end"]) if captions else "0:00"
    return (
        f'<div class="t2v-player">'
        f'<audio preload="metadata" src="{html.escape(audio_url, quote=True)}" aria-label="{label}"></audio>'
        f'<div class="t2v-stage">'
        f'<div class="t2v-np-label">Now playing<span class="t2v-eq" aria-hidden="true"><i></i><i></i><i></i><i></i></span></div>'
        f'<div class="t2v-np-title">{label}</div>'
        f'<div class="t2v-np-chapter">{first_chapter}</div>'
        f'<div class="t2v-controls">'
        f'<button type="button" class="t2v-ctl" data-t2v-ctl="back" aria-label="Back 15 seconds" title="Back 15 seconds">{ICONS["back"]}</button>'
        f'<button type="button" class="t2v-ctl t2v-play" data-t2v-ctl="play" aria-label="Play or pause" title="Play or pause">{ICONS["play"]}{ICONS["pause"]}</button>'
        f'<button type="button" class="t2v-ctl" data-t2v-ctl="fwd" aria-label="Forward 15 seconds" title="Forward 15 seconds">{ICONS["fwd"]}</button>'
        f'<div class="t2v-timeline">'
        f'<div class="t2v-track" role="slider" tabindex="0" aria-label="Position" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="t2v-fill"></div></div>'
        f'<div class="t2v-times"><span class="t2v-now">0:00</span><span class="t2v-total">{duration}</span></div>'
        f'</div>'
        f'<button type="button" class="t2v-rate" data-t2v-ctl="rate" aria-label="Playback speed" title="Playback speed">1x</button>'
        f'</div></div>'
        f'<div class="t2v-captions" tabindex="0" aria-label="Captions">{"".join(body)}</div>'
        f'<div class="t2v-hint">The words light up as they are read. Click any sentence to jump to it.</div>'
        f"</div>"
    )
