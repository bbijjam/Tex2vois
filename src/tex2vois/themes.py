"""Colour themes the reader can pick in the header (saved in their browser).

Palettes only, loosely inspired by series the reader likes; no logos or artwork.
Each theme has a light and a dark version; every pair was checked for contrast.
Two accents per theme: "primary" is used on the Article and Assistant script
tabs, "secondary" on Research paper and Book, so the tabs stay distinguishable.

The page's <html> gets the class `t2v-theme-<key>`; Gradio puts `.dark` on <body>.
"""

from __future__ import annotations

import html
import re

KEYS = ("page", "surface", "surface_2", "border", "text", "muted", "brand", "brand_text", "brand_muted",
        "stage", "stage_text", "stage_muted", "stage_track", "mark", "mark_text", "para",
        "primary", "primary_soft", "primary_on_stage", "secondary", "secondary_soft", "secondary_on_stage")

THEMES: dict[str, dict] = {
    "naruto": {
        "label": "Naruto (orange and purple)",
        "light": dict(page="#fbf5ef", surface="#ffffff", surface_2="#fdf3e9", border="#ecdccb", text="#22180f", muted="#66544a",
                      brand="#2b1745", brand_text="#fff4ea", brand_muted="#e2cdee", stage="#1d1230", stage_text="#fff4ea",
                      stage_muted="#cdb9df", stage_track="#3e2c57", mark="#ffd8a8", mark_text="#22180f", para="#fff2e2",
                      primary="#c2410c", primary_soft="#fff0e3", primary_on_stage="#ff9f45",
                      secondary="#6b3fa0", secondary_soft="#f3ecfb", secondary_on_stage="#c9a2f2"),
        "dark": dict(page="#140e1b", surface="#1e1626", surface_2="#251b2f", border="#3b2d48", text="#f3ece6", muted="#c2b3bf",
                     brand="#2b1745", brand_text="#fff4ea", brand_muted="#d9c2ec", stage="#120b1a", stage_text="#fff4ea",
                     stage_muted="#c6b3d8", stage_track="#3a2a4e", mark="#8a3d0e", mark_text="#fff3e8", para="#2a1d24",
                     primary="#ff9f45", primary_soft="#3a2214", primary_on_stage="#ff9f45",
                     secondary="#c9a2f2", secondary_soft="#2b1f3b", secondary_on_stage="#c9a2f2"),
    },
    "demon-slayer": {
        "label": "Demon Slayer (green and pink)",
        "light": dict(page="#f4f6f2", surface="#ffffff", surface_2="#f1f5f0", border="#d9e2d8", text="#151c18", muted="#4f5d55",
                      brand="#0d3b2e", brand_text="#f2fbf6", brand_muted="#b9dccb", stage="#0f1f1a", stage_text="#f2fbf6",
                      stage_muted="#a9c4b8", stage_track="#2a3f37", mark="#ffd3e2", mark_text="#151c18", para="#fdf0f4",
                      primary="#17714f", primary_soft="#e5f3ec", primary_on_stage="#6fd3a6",
                      secondary="#b4235b", secondary_soft="#fbe8ef", secondary_on_stage="#f78fb3"),
        "dark": dict(page="#0d1311", surface="#151d1a", surface_2="#1b2521", border="#2d3c36", text="#ecf3ef", muted="#a9bbb2",
                     brand="#0d3b2e", brand_text="#f2fbf6", brand_muted="#b9dccb", stage="#09110e", stage_text="#f2fbf6",
                     stage_muted="#a3bdb1", stage_track="#26362f", mark="#7a1f45", mark_text="#fff0f5", para="#23171c",
                     primary="#6fd3a6", primary_soft="#15302a", primary_on_stage="#6fd3a6",
                     secondary="#f78fb3", secondary_soft="#331a25", secondary_on_stage="#f78fb3"),
    },
    "one-piece": {
        "label": "One Piece (red, gold and ocean blue)",
        "light": dict(page="#f5f3ee", surface="#ffffff", surface_2="#f8f4ea", border="#e3dccb", text="#1b1a17", muted="#5c5649",
                      brand="#12355b", brand_text="#fdf8ea", brand_muted="#c3d4ea", stage="#0f2238", stage_text="#fdf8ea",
                      stage_muted="#b3c3d8", stage_track="#2b4060", mark="#ffe79a", mark_text="#1b1a17", para="#fff8e1",
                      primary="#b42318", primary_soft="#fdecea", primary_on_stage="#f2c94c",
                      secondary="#1c5d99", secondary_soft="#e7f0f9", secondary_on_stage="#7cb7ee"),
        "dark": dict(page="#0d1420", surface="#142033", surface_2="#1a283d", border="#2c3d55", text="#eef2f7", muted="#b0bccb",
                     brand="#12355b", brand_text="#fdf8ea", brand_muted="#c3d4ea", stage="#0a1524", stage_text="#fdf8ea",
                     stage_muted="#aebdd0", stage_track="#263a55", mark="#7a5c0e", mark_text="#fff9e6", para="#1f2430",
                     primary="#ff8a80", primary_soft="#3a1d1f", primary_on_stage="#f2c94c",
                     secondary="#7cb7ee", secondary_soft="#182c44", secondary_on_stage="#7cb7ee"),
    },
    "solo-leveling": {
        "label": "Solo Leveling (black, blue and violet)",
        "light": dict(page="#f2f3f7", surface="#ffffff", surface_2="#f4f5fa", border="#dadde8", text="#12141c", muted="#4e5468",
                      brand="#0b0f1e", brand_text="#eef2ff", brand_muted="#a9b8e8", stage="#0b0f1e", stage_text="#eef2ff",
                      stage_muted="#a3add0", stage_track="#262d4a", mark="#d6e4ff", mark_text="#12141c", para="#eef3ff",
                      primary="#2554c7", primary_soft="#e8eefc", primary_on_stage="#6ea8ff",
                      secondary="#6d3fd1", secondary_soft="#efe9fc", secondary_on_stage="#b69cff"),
        "dark": dict(page="#07090f", surface="#0f1320", surface_2="#141a2b", border="#252d45", text="#e9edfb", muted="#a6aecb",
                     brand="#0b0f1e", brand_text="#eef2ff", brand_muted="#a9b8e8", stage="#05070d", stage_text="#eef2ff",
                     stage_muted="#9ea9cf", stage_track="#20294a", mark="#23417e", mark_text="#eef4ff", para="#121a30",
                     primary="#6ea8ff", primary_soft="#14213f", primary_on_stage="#6ea8ff",
                     secondary="#b69cff", secondary_soft="#221a3d", secondary_on_stage="#b69cff"),
    },
    "hunter-x-hunter": {
        "label": "Hunter x Hunter (green and blue)",
        "light": dict(page="#f2f6f1", surface="#ffffff", surface_2="#f2f7f1", border="#d6e2d4", text="#141b14", muted="#4b5a4b",
                      brand="#173b23", brand_text="#f1faf1", brand_muted="#b8d9be", stage="#10241a", stage_text="#f1faf1",
                      stage_muted="#a9c6b0", stage_track="#2a4233", mark="#d3f9d8", mark_text="#141b14", para="#eefaf0",
                      primary="#237a3b", primary_soft="#e6f4e9", primary_on_stage="#8ce99a",
                      secondary="#3b5bdb", secondary_soft="#e9eefd", secondary_on_stage="#91a7ff"),
        "dark": dict(page="#0b120d", surface="#131c15", surface_2="#18241b", border="#2a3a2d", text="#ebf3ec", muted="#a8baab",
                     brand="#173b23", brand_text="#f1faf1", brand_muted="#b8d9be", stage="#08110b", stage_text="#f1faf1",
                     stage_muted="#a2bea8", stage_track="#24382a", mark="#2b6a3a", mark_text="#f1fff3", para="#16261b",
                     primary="#8ce99a", primary_soft="#17301e", primary_on_stage="#8ce99a",
                     secondary="#91a7ff", secondary_soft="#1b2342", secondary_on_stage="#91a7ff"),
    },
}

MODES = {"article": "primary", "paper": "secondary", "assistant": "primary", "book": "secondary"}

# Original background patterns drawn with CSS (no artwork): a nod to each series, nothing copied.
PATTERNS = {
    "classic": "radial-gradient(circle, #ffffff16 1px, transparent 1.6px) 0 0 / 18px 18px",
    "naruto": "repeating-radial-gradient(circle at 82% 38%, #ff9f4524 0 2px, transparent 2px 15px)",
    "demon-slayer": "repeating-conic-gradient(#ffffff10 0 25%, transparent 0 50%) 0 0 / 30px 30px",
    "one-piece": "radial-gradient(circle at 50% 100%, transparent 13px, #ffffff1a 14px 16px, transparent 17px) 0 0 / 34px 17px",
    "solo-leveling": "linear-gradient(#6ea8ff1f 1px, transparent 1px) 0 0 / 26px 26px, linear-gradient(90deg, #6ea8ff1f 1px, transparent 1px) 0 0 / 26px 26px",
    "hunter-x-hunter": "repeating-linear-gradient(135deg, #8ce99a1c 0 2px, transparent 2px 17px)",
}


def _soften(pattern: str) -> str:
    """Halve the alpha of every #rrggbbaa colour (and only those), for the quieter player-card pattern."""
    return re.sub(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})\b", lambda m: f"#{m.group(1)}{int(m.group(2), 16) // 2:02x}", pattern)


SOFT_PATTERNS = {k: _soften(v) for k, v in PATTERNS.items()}


def _vars(c: dict, dark: bool) -> str:
    """Our own --t2v-* variables plus the Gradio theme variables the components use."""
    ours = {
        "page": c["page"], "surface": c["surface"], "surface-2": c["surface_2"], "tint": c["surface_2"], "border": c["border"],
        "text": c["text"], "muted": c["muted"], "brand": c["brand"], "brand-text": c["brand_text"], "brand-muted": c["brand_muted"],
        "accent": c["primary"], "mark": c["mark"], "mark-text": c["mark_text"], "para": c["para"], "stage": c["stage"],
        "stage-text": c["stage_text"], "stage-muted": c["stage_muted"], "stage-track": c["stage_track"],
        "mode": c["primary"], "mode-soft": c["primary_soft"], "mode-on-stage": c["primary_on_stage"],
    }
    gradio = {
        "body-background-fill": c["page"], "background-fill-primary": c["surface"], "background-fill-secondary": c["surface_2"],
        "block-background-fill": c["surface"], "block-border-color": c["border"], "border-color-primary": c["border"],
        "input-background-fill": c["surface_2"] if dark else c["surface"], "input-border-color": c["border"],
        "input-border-color-focus": c["primary"], "body-text-color": c["text"], "body-text-color-subdued": c["muted"],
        "block-label-text-color": c["text"], "block-title-text-color": c["text"], "block-info-text-color": c["muted"],
        "button-secondary-background-fill": c["surface"], "button-secondary-background-fill-hover": c["surface_2"],
        "button-secondary-text-color": c["text"], "button-secondary-border-color": c["border"],
        "checkbox-label-background-fill": c["surface"], "checkbox-background-color-selected": c["primary"],
        "checkbox-border-color-selected": c["primary"], "slider-color": c["primary"], "color-accent": c["primary"],
        "color-accent-soft": c["primary_soft"], "link-text-color": c["primary"], "input-placeholder-color": c["muted"],
    }
    # !important: Gradio re-emits custom CSS with a long scoping prefix, which would otherwise outrank theme rules.
    # Among these !important rules, the dark ones are more specific, so they still win in dark mode.
    return " ".join(f"--t2v-{k}: {v} !important;" for k, v in ours.items()) + " " + " ".join(
        f"--{k}: {v} !important;" for k, v in gradio.items())


def _modes(c: dict) -> str:
    return " ".join(
        f".t2v-mode-{mode} {{ --t2v-mode: {c[role]} !important; --t2v-mode-soft: {c[role + '_soft']} !important; "
        f"--t2v-mode-on-stage: {c[role + '_on_stage']} !important; }}"
        for mode, role in MODES.items()
    )


def css() -> str:
    out = []
    for key, t in THEMES.items():
        light, dark = f"html.t2v-theme-{key}", f"html.t2v-theme-{key} body.dark"
        # Gradio also re-declares our base variables on .gradio-container / .contain, so set the theme there too.
        out.append(f"{light}, {light} body, {light} .gradio-container, {light} .contain {{ {_vars(t['light'], False)} "
                   f"--t2v-pattern: {PATTERNS[key]} !important; --t2v-pattern-soft: {SOFT_PATTERNS[key]} !important; }}")
        out.append(f"{dark}, {dark} .gradio-container, {dark} .contain {{ {_vars(t['dark'], True)} }}")
        out.append(_modes(t["light"]).replace(".t2v-mode-", f"{light} .t2v-mode-"))
        out.append(_modes(t["dark"]).replace(".t2v-mode-", f"{dark} .t2v-mode-"))
        # button text sits on the accent colour: white on the darker light-mode accents, near-black on dark-mode ones
        out.append(f"{light} [class*='t2v-mode-'] {{ --t2v-on-mode: #ffffff !important; }} "
                   f"{dark} [class*='t2v-mode-'] {{ --t2v-on-mode: #101413 !important; }}")
    return "\n".join(out)


def picker() -> str:
    options = '<option value="classic">Classic</option>' + "".join(
        f'<option value="{k}">{html.escape(t["label"])}</option>' for k, t in THEMES.items()
    )
    return (
        '<div class="t2v-header-controls">'
        f'<label class="t2v-theme-pick">Theme <select data-t2v-theme aria-label="Colour theme">{options}</select></label>'
        '<label class="t2v-bg-pick" title="Use a picture from your computer as the background. It stays in this browser.">'
        'Background picture<input type="file" accept="image/*" data-t2v-bg hidden></label>'
        '<button type="button" class="t2v-bg-clear" data-t2v-bg-clear hidden>Remove picture</button>'
        '<span class="t2v-bg-status" data-t2v-bg-status role="status"></span>'
        "</div>"
    )


JS = r"""
  // ---- background picture: the reader's own image, resized and kept in this browser only ----
  const BG_KEY = 't2v-bg';
  const applyBg = data => {
    const root = document.documentElement;
    if (data) { root.style.setProperty('--t2v-bg-image', `url("${data}")`); root.classList.add('t2v-has-bg'); }
    else { root.style.removeProperty('--t2v-bg-image'); root.classList.remove('t2v-has-bg'); }
    document.querySelectorAll('[data-t2v-bg-clear]').forEach(b => { b.hidden = !data; });
  };
  const bgStatus = msg => document.querySelectorAll('[data-t2v-bg-status]').forEach(s => { s.textContent = msg; });
  let savedBg = null;
  try { savedBg = localStorage.getItem(BG_KEY); } catch (e) {}
  applyBg(savedBg);
  new MutationObserver(() => document.querySelectorAll('[data-t2v-bg-clear]').forEach(b => { b.hidden = !savedBg; }))
    .observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('change', e => {
    if (!(e.target.matches && e.target.matches('[data-t2v-bg]')) || !e.target.files[0]) return;
    const file = e.target.files[0];
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, 1920 / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
      let data = canvas.toDataURL('image/jpeg', 0.82);
      try { localStorage.setItem(BG_KEY, data); bgStatus(''); }
      catch (err) { bgStatus('Shown for now, but too large to remember next time.'); }
      savedBg = data; applyBg(data); URL.revokeObjectURL(img.src);
    };
    img.onerror = () => bgStatus('That file could not be opened as a picture.');
    img.src = URL.createObjectURL(file);
    e.target.value = '';
  });
  document.addEventListener('click', e => {
    if (!(e.target.closest && e.target.closest('[data-t2v-bg-clear]'))) return;
    try { localStorage.removeItem(BG_KEY); } catch (err) {}
    savedBg = null; applyBg(null); bgStatus('');
  });

  // ---- colour theme: a class on <html>, remembered in this browser ----
  const THEME_KEY = 't2v-theme';
  const applyTheme = name => {
    document.documentElement.className = document.documentElement.className.replace(/\bt2v-theme-\S+/g, '').trim();
    if (name && name !== 'classic') document.documentElement.classList.add('t2v-theme-' + name);
    document.documentElement.classList.toggle('t2v-has-scene', !!name && name !== 'classic');
    document.querySelectorAll('[data-t2v-theme]').forEach(s => { s.value = name || 'classic'; });
  };
  let savedTheme = 'classic';
  try { savedTheme = localStorage.getItem(THEME_KEY) || 'classic'; } catch (e) {}
  applyTheme(savedTheme);
  new MutationObserver(() => {
    document.querySelectorAll('[data-t2v-theme]').forEach(s => { if (!s.dataset.ready) { s.dataset.ready = '1'; s.value = savedTheme; } });
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('change', e => {
    if (!(e.target.matches && e.target.matches('[data-t2v-theme]'))) return;
    savedTheme = e.target.value;
    try { localStorage.setItem(THEME_KEY, savedTheme); } catch (err) {}
    applyTheme(savedTheme);
  });
"""
