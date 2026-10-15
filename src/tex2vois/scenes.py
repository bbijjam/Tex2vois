"""Original background scenes for the colour themes.

Hand-written SVG landscapes that evoke the mood of each series (colours, setting,
simple shapes) without copying any character, logo or artwork. Each is embedded as
a data URI, so nothing is downloaded and the repository stays free of third-party art.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice">'


def _leaf(x: int, y: int, r: int, color: str, opacity: float = 0.8) -> str:
    return (f'<path transform="translate({x} {y}) rotate({r})" d="M0 0 C 18 -22 46 -22 64 0 C 46 22 18 22 0 0 Z M0 0 L64 0" '
            f'fill="{color}" stroke="{color}" stroke-opacity=".6" opacity="{opacity}"/>')


NARUTO = _HEAD + """
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b1745"/><stop offset=".45" stop-color="#7b2f7a"/>
    <stop offset=".75" stop-color="#f06d2f"/><stop offset="1" stop-color="#ffb35c"/></linearGradient>
  <radialGradient id="sun" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#ffe2a8"/><stop offset=".6" stop-color="#ffb04d"/>
    <stop offset="1" stop-color="#ff8a2a" stop-opacity="0"/></radialGradient>
</defs>
<rect width="1600" height="900" fill="url(#sky)"/>
<circle cx="1180" cy="560" r="230" fill="url(#sun)"/>
<g fill="none" stroke="#ffd29a" stroke-opacity=".35" stroke-width="3">
  <path d="M1180 560 m0 -40 a40 40 0 1 1 -40 40 a60 60 0 1 1 60 60 a90 90 0 1 1 -90 -90 a130 130 0 1 1 130 130"/>
</g>
<path d="M0 700 L180 560 L320 650 L520 470 L700 620 L860 520 L1040 660 L1240 540 L1420 640 L1600 560 L1600 900 L0 900 Z" fill="#4a1f5e" opacity=".85"/>
<path d="M0 780 L220 660 L420 740 L640 620 L860 730 L1080 650 L1300 750 L1600 660 L1600 900 L0 900 Z" fill="#2e1640"/>
<path d="M0 850 L300 790 L620 840 L940 780 L1260 840 L1600 790 L1600 900 L0 900 Z" fill="#1c0d29"/>
""" + "".join(_leaf(x, y, r, "#ff9f45", o) for x, y, r, o in
              [(140, 180, 20, .7), (380, 300, -30, .55), (620, 140, 60, .6), (900, 260, 10, .5), (1420, 200, -50, .7), (260, 470, 35, .45), (1500, 420, 80, .5)]) + "</svg>"

DEMON_SLAYER = _HEAD + """
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#06120f"/><stop offset=".6" stop-color="#0d3b2e"/>
    <stop offset="1" stop-color="#174d3b"/></linearGradient>
  <radialGradient id="moon" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff6e8"/><stop offset=".7" stop-color="#f4e3cf"/>
    <stop offset="1" stop-color="#f4e3cf" stop-opacity="0"/></radialGradient>
  <pattern id="check" width="40" height="40" patternUnits="userSpaceOnUse"><rect width="40" height="40" fill="#0b2a21"/>
    <rect width="20" height="20" fill="#123d30"/><rect x="20" y="20" width="20" height="20" fill="#123d30"/></pattern>
</defs>
<rect width="1600" height="900" fill="url(#sky)"/>
<circle cx="1250" cy="230" r="150" fill="url(#moon)"/>
<g fill="#ffffff" opacity=".7"><circle cx="200" cy="120" r="2"/><circle cx="520" cy="80" r="1.5"/><circle cx="860" cy="160" r="2"/>
  <circle cx="1020" cy="60" r="1.5"/><circle cx="1480" cy="420" r="1.5"/><circle cx="340" cy="260" r="1.5"/></g>
""" + "".join(
    f'<g transform="translate({x} 0)">' + "".join(
        f'<ellipse cx="{(i % 3) * 9 - 9}" cy="{30 + i * 22}" rx="{11 - i // 3}" ry="{8 - i // 4}" fill="{c}" opacity=".85"/>'
        for i in range(n)) + f'<path d="M0 0 L0 {30 + n * 22}" stroke="#4a6b4f" stroke-width="2" opacity=".6"/></g>'
    for x, n, c in [(120, 12, "#c9a2f2"), (210, 9, "#e7b8e6"), (300, 14, "#b98be8"), (420, 8, "#f0a9d4"), (520, 11, "#c9a2f2"),
                    (1520, 12, "#e7b8e6"), (1440, 9, "#c9a2f2")]) + """
<path d="M0 760 L60 640 L120 760 L170 600 L230 760 L300 660 L360 760 L1240 760 L1300 650 L1360 760 L1420 610 L1480 760 L1540 670 L1600 760 L1600 900 L0 900 Z" fill="#071b15"/>
<rect y="840" width="1600" height="60" fill="url(#check)" opacity=".9"/>
</svg>"""

ONE_PIECE = _HEAD + """
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3f7fbf"/><stop offset=".55" stop-color="#9cc8ea"/>
    <stop offset=".75" stop-color="#ffd98a"/></linearGradient>
  <linearGradient id="sea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1c5d99"/><stop offset="1" stop-color="#0c2c4f"/></linearGradient>
</defs>
<rect width="1600" height="900" fill="url(#sky)"/>
<circle cx="380" cy="560" r="120" fill="#ffe08a" opacity=".9"/>
<g fill="#ffffff" opacity=".85"><ellipse cx="1150" cy="180" rx="130" ry="34"/><ellipse cx="1240" cy="160" rx="90" ry="40"/>
  <ellipse cx="420" cy="140" rx="110" ry="28"/><ellipse cx="500" cy="124" rx="70" ry="32"/></g>
<rect y="600" width="1600" height="300" fill="url(#sea)"/>
<g fill="none" stroke="#9cc8ea" stroke-opacity=".5" stroke-width="3">
  <path d="M0 650 q40 -20 80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0 t80 0"/>
  <path d="M0 720 q50 -24 100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0 t100 0"/>
  <path d="M0 800 q60 -28 120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0 t120 0"/>
</g>
<g transform="translate(1000 470)">
  <path d="M0 120 L260 120 L230 165 L30 165 Z" fill="#5a3418"/>
  <path d="M120 0 L120 120" stroke="#3b2210" stroke-width="7"/>
  <path d="M60 20 Q120 0 180 20 L176 100 Q120 84 64 100 Z" fill="#fff6e0"/>
  <circle cx="120" cy="58" r="18" fill="none" stroke="#b42318" stroke-width="5"/>
  <path d="M120 0 L150 -16 L120 -26 Z" fill="#b42318"/>
</g>
<g fill="none" stroke="#12355b" stroke-width="4" stroke-linecap="round" opacity=".7">
  <path d="M640 260 q16 -14 32 0 q16 -14 32 0"/><path d="M760 320 q12 -10 24 0 q12 -10 24 0"/><path d="M560 340 q10 -8 20 0 q10 -8 20 0"/></g>
</svg>"""

SOLO_LEVELING = _HEAD + """
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#03050b"/><stop offset="1" stop-color="#0d1430"/></linearGradient>
  <radialGradient id="gate" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#e9f0ff"/><stop offset=".25" stop-color="#6ea8ff"/>
    <stop offset=".6" stop-color="#6d3fd1" stop-opacity=".8"/><stop offset="1" stop-color="#2554c7" stop-opacity="0"/></radialGradient>
</defs>
<rect width="1600" height="900" fill="url(#sky)"/>
<ellipse cx="1060" cy="430" rx="190" ry="300" fill="url(#gate)" opacity=".9"/>
<ellipse cx="1060" cy="430" rx="120" ry="230" fill="none" stroke="#9cc3ff" stroke-width="3" opacity=".7"/>
<g fill="#6ea8ff">""" + "".join(
    f'<circle cx="{x}" cy="{y}" r="{r}" opacity="{o}"/>' for x, y, r, o in
    [(880, 200, 3, .8), (1240, 260, 2, .7), (960, 620, 2.5, .6), (1200, 580, 3, .8), (820, 420, 2, .5), (1320, 380, 2, .6),
     (300, 160, 1.5, .5), (520, 90, 1.5, .4), (1480, 120, 1.5, .5)]) + """</g>
<g fill="#070a17">
  <rect x="0" y="600" width="90" height="300"/><rect x="100" y="520" width="70" height="380"/><rect x="180" y="640" width="110" height="260"/>
  <rect x="300" y="560" width="60" height="340"/><rect x="370" y="680" width="120" height="220"/><rect x="500" y="590" width="80" height="310"/>
  <rect x="600" y="660" width="140" height="240"/><rect x="1300" y="580" width="90" height="320"/><rect x="1400" y="650" width="80" height="250"/>
  <rect x="1490" y="540" width="110" height="360"/>
</g>
<g fill="#6ea8ff" opacity=".45"><rect x="120" y="560" width="8" height="10"/><rect x="140" y="600" width="8" height="10"/>
  <rect x="320" y="600" width="8" height="10"/><rect x="520" y="630" width="8" height="10"/><rect x="1320" y="620" width="8" height="10"/>
  <rect x="1520" y="590" width="8" height="10"/><rect x="1540" y="640" width="8" height="10"/></g>
<rect y="860" width="1600" height="40" fill="#05070d"/>
</svg>"""

HUNTER_X_HUNTER = _HEAD + """
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4fa3e0"/><stop offset=".7" stop-color="#bfe3f7"/>
    <stop offset="1" stop-color="#e8f7e1"/></linearGradient>
</defs>
<rect width="1600" height="900" fill="url(#sky)"/>
<circle cx="1320" cy="170" r="70" fill="#fff7d1" opacity=".9"/>
<path d="M980 60 L930 210 L990 205 L920 380 L1060 170 L995 175 L1050 60 Z" fill="#dbe4ff" stroke="#91a7ff" stroke-width="4" opacity=".75"/>
<path d="M0 620 Q300 470 620 590 T1240 560 T1600 600 L1600 900 L0 900 Z" fill="#5cae6b"/>
<path d="M0 720 Q360 600 760 700 T1600 690 L1600 900 L0 900 Z" fill="#2f7d45"/>
<path d="M0 820 Q420 740 860 810 T1600 800 L1600 900 L0 900 Z" fill="#1d5730"/>
""" + "".join(
    f'<g transform="translate({x} {y})"><rect x="-10" y="0" width="20" height="{h}" fill="#3b2a1c"/>'
    f'<ellipse cx="0" cy="0" rx="{w}" ry="{w * 1.3:.0f}" fill="#1f6b37"/><ellipse cx="-{w // 3}" cy="-{w // 2}" rx="{w * 0.7:.0f}" ry="{w * 0.8:.0f}" fill="#2b8a3e"/></g>'
    for x, y, w, h in [(140, 560, 70, 200), (300, 600, 55, 170), (1420, 540, 80, 230), (1540, 590, 60, 190), (760, 640, 45, 120)]
) + "".join(_leaf(x, y, r, "#2b8a3e", o) for x, y, r, o in [(420, 260, 20, .6), (640, 360, -40, .5), (1120, 300, 50, .55), (220, 380, 70, .5)]) + "</svg>"

SCENES = {
    "naruto": NARUTO,
    "demon-slayer": DEMON_SLAYER,
    "one-piece": ONE_PIECE,
    "solo-leveling": SOLO_LEVELING,
    "hunter-x-hunter": HUNTER_X_HUNTER,
}


def data_uri(svg: str) -> str:
    return "data:image/svg+xml;charset=utf-8," + quote(" ".join(svg.split()), safe="")


LOCAL_ART = Path(__file__).resolve().parents[2] / "local_art"
IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".webp")


def local_art() -> dict[str, Path]:
    """Your own pictures for each theme: local_art/<theme>.jpg (png/webp too). The folder is git-ignored,
    so personal or copyrighted images are used on this computer but never published."""
    found = {}
    for key in SCENES:
        for ext in IMAGE_TYPES:
            f = LOCAL_ART / f"{key}{ext}"
            if f.is_file():
                found[key] = f
                break
    return found


def css() -> str:
    """Each theme gets its scene (or your own picture from local_art/) behind a veil.
    A picture chosen with the Background picture button still wins (t2v-has-bg)."""
    out, mine = [], local_art()
    for key, svg in SCENES.items():
        src = f"/gradio_api/file={mine[key]}" if key in mine else data_uri(svg)
        out.append(f'html.t2v-theme-{key}:not(.t2v-has-bg) body {{ background: linear-gradient(var(--t2v-scene-veil), var(--t2v-scene-veil)), '
                   f'url("{src}") center bottom / cover fixed no-repeat !important; }}')
    return "\n".join(out)
