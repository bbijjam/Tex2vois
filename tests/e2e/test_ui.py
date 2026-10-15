"""Browser tests for the web app (Playwright + Chromium).

They start their own copy of the app on a spare port with the AI switched off
(TEX2VOIS_LLM=off), so results don't depend on free-model availability.

    TEX2VOIS_E2E=1 pytest tests/e2e -q        (first time: playwright install chromium)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

if os.environ.get("TEX2VOIS_E2E") != "1":
    pytest.skip("browser tests are opt-in: set TEX2VOIS_E2E=1", allow_module_level=True)

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from tests.test_book import make_epub  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
THEMES = ["classic", "naruto", "demon-slayer", "one-piece", "solo-leveling", "hunter-x-hunter"]
ARTICLE = "Why walking helps you think\n\n" + "\n\n".join(
    ["Walking increases blood flow to the brain. People came up with 60% more ideas while walking. "
     "The gentle rhythm frees the mind to wander."] * 3)
SCRIPT = "# A tiny paper\n\n## Introduction\n\nPlants grow toward light.\n\n## Results\n\nSeedlings bent 30 degrees in 2 hours.\n\nEND OF SCRIPT"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    port = _free_port()
    env = {**os.environ, "TEX2VOIS_LLM": "off", "GRADIO_SERVER_PORT": str(port), "GRADIO_ANALYTICS_ENABLED": "False"}
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("app did not start")
    yield url
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        yield b
        b.close()


def open_page(browser, url, mode="light", width=1360, height=1000, **ctx) -> tuple[Page, list[str]]:
    context = browser.new_context(viewport={"width": width, "height": height}, **ctx)
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.rstrip("/"))
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{url}?__theme={mode}", wait_until="networkidle")
    page.wait_for_selector(".t2v-header")
    time.sleep(0.8)  # entrance animations
    return page, errors


def reachable(page: Page, locator) -> bool:
    """True if a click at the element's centre would land on the element itself (nothing covers it)."""
    box = locator.bounding_box()
    if not box:
        return False
    return locator.evaluate("(e, p) => { const t = document.elementFromPoint(p.x, p.y); return !!t && (t === e || e.contains(t)); }",
                            {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2})


def check_dropdown(page: Page, combobox) -> None:
    """Open the dropdown, check every option is visible and unobstructed, and pick the last one."""
    combobox.scroll_into_view_if_needed()
    combobox.click()
    page.wait_for_selector("ul.option-list li", timeout=5000)
    items = page.locator("ul.option-list li")
    n = items.count()
    assert n > 0
    target_box = combobox.bounding_box()
    list_box = page.locator("ul.option-list").bounding_box()
    # the list opens right next to its box (above or below), not somewhere else on the page
    gap = min(abs(list_box["y"] - (target_box["y"] + target_box["height"])), abs(target_box["y"] - (list_box["y"] + list_box["height"])))
    assert gap < 40, f"dropdown list opened {gap:.0f}px away from its box"
    for i in range(n):
        item = items.nth(i)
        item.scroll_into_view_if_needed()
        assert reachable(page, item), f"option {i} of {combobox.get_attribute('aria-label')} is covered"
    label = items.nth(n - 1).inner_text().strip()
    items.nth(n - 1).click()
    time.sleep(0.3)
    assert combobox.input_value().strip() == label


def visible_buttons(page: Page):
    # Gradio keeps 1px-high copies of the tab buttons for measuring; skip anything that small
    return [b for b in page.locator("button:visible").all() if min((b.bounding_box() or {}).get(k, 0) for k in ("width", "height")) > 4]


# ---------------------------------------------------------------- layout and controls

@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("theme", ["classic", "naruto", "solo-leveling"])
def test_dropdowns_and_buttons_are_usable(server, browser, mode, theme):
    page, errors = open_page(browser, server, mode)
    page.locator("select[data-t2v-theme]").select_option(theme)
    time.sleep(0.5)
    check_dropdown(page, page.get_by_role("combobox", name="Voice"))
    check_dropdown(page, page.get_by_role("combobox", name="Save as"))
    for tab in ("Article", "Research paper", "Assistant script", "Book"):
        page.get_by_role("tab", name=tab).click()
        time.sleep(0.6)
        for button in visible_buttons(page):
            button.scroll_into_view_if_needed()
            assert reachable(page, button), f"{tab}: button '{button.inner_text()[:30]}' is covered"
    assert not errors, errors


def test_phone_layout(server, browser):
    page, errors = open_page(browser, server, width=390, height=844, is_mobile=True, has_touch=True)
    for tab in ("Article", "Research paper", "Assistant script", "Book"):
        page.get_by_role("tab", name=tab).click()
        time.sleep(0.5)
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 1, f"{tab}: page scrolls sideways by {overflow}px on a phone"
    check_dropdown(page, page.get_by_role("combobox", name="Voice"))
    assert not errors, errors


def test_themes_and_background_persist(server, browser, tmp_path):
    page, errors = open_page(browser, server)
    for theme in THEMES:
        page.locator("select[data-t2v-theme]").select_option(theme)
        time.sleep(0.3)
        cls = page.evaluate("document.documentElement.className")
        assert (f"t2v-theme-{theme}" in cls) == (theme != "classic")
        assert ("t2v-has-scene" in cls) == (theme != "classic")
    page.locator("select[data-t2v-theme]").select_option("naruto")
    img = tmp_path / "bg.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=800x450", "-frames:v", "1", str(img)], check=True)
    page.locator("input[data-t2v-bg]").set_input_files(str(img))
    time.sleep(1)
    page.reload(wait_until="networkidle")
    time.sleep(1)
    cls = page.evaluate("document.documentElement.className")
    assert "t2v-theme-naruto" in cls and "t2v-has-bg" in cls
    page.locator("[data-t2v-bg-clear]").click()
    page.locator("select[data-t2v-theme]").select_option("classic")
    time.sleep(0.3)
    assert "t2v-has-bg" not in page.evaluate("document.documentElement.className")
    assert not errors, errors


# ---------------------------------------------------------------- flows

def run_article(page: Page, text: str = ARTICLE):
    page.get_by_role("tab", name="Article").click()
    page.get_by_label("Paste your text").fill(text)
    page.locator(".tabitem:visible").get_by_role("button", name="Read it to me").click()
    page.wait_for_selector(".t2v-player:not(.t2v-empty-player) audio", state="attached", timeout=180_000)
    time.sleep(0.5)


def test_article_player_controls_and_notes(server, browser):
    page, errors = open_page(browser, server)
    run_article(page)
    player = page.locator(".t2v-player:not(.t2v-empty-player)").first
    audio = "document.querySelector('.t2v-player:not(.t2v-empty-player) audio')"
    player.locator("[data-t2v-ctl=play]").click()
    page.wait_for_selector(".t2v-s.t2v-on", timeout=10_000)  # after the spoken title, a sentence lights up
    assert page.evaluate(f"!{audio}.paused") and "t2v-playing" in player.get_attribute("class")
    assert page.locator(".t2v-s.t2v-on").count() == 1
    t = page.evaluate(f"{audio}.currentTime")
    player.locator("[data-t2v-ctl=fwd]").click()
    time.sleep(0.4)
    assert page.evaluate(f"{audio}.currentTime") > t + 10
    player.locator("[data-t2v-ctl=back]").click()
    time.sleep(0.4)
    player.locator("[data-t2v-ctl=rate]").click()
    assert page.evaluate(f"{audio}.playbackRate") == 1.25
    box = player.locator(".t2v-track").bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.75, box["y"] + box["height"] / 2)
    time.sleep(0.4)
    frac = page.evaluate(f"{audio}.currentTime / {audio}.duration")
    assert 0.65 < frac < 0.85
    page.locator(".t2v-s").nth(2).click()
    time.sleep(0.4)
    start = float(page.locator(".t2v-s").nth(2).get_attribute("data-start"))
    assert abs(page.evaluate(f"{audio}.currentTime") - start) < 1.0
    player.locator("[data-t2v-ctl=play]").click()
    time.sleep(0.3)
    assert page.evaluate(f"{audio}.paused")
    # notes: stamp, sync, persist, download
    page.get_by_role("button", name="Mark this moment").first.click()
    notes = page.locator(".t2v-notes-text").first
    notes.press_sequentially("check this")
    value = notes.input_value()
    assert value.startswith("- [") and value.endswith("check this")
    page.get_by_role("tab", name="Book").click()
    assert page.locator(".t2v-notes-text:visible").first.input_value() == value
    with page.expect_download() as d:
        page.locator(".tabitem:visible").get_by_role("button", name="Save notes").click()
    assert d.value.suggested_filename.endswith(".txt")
    page.reload(wait_until="networkidle")
    time.sleep(1)
    assert page.locator(".t2v-notes-text").first.input_value() == value
    page.evaluate("localStorage.removeItem('t2v-notes')")
    assert not errors, errors


def test_stop_button(server, browser):
    page, errors = open_page(browser, server)
    page.get_by_label("Paste your text").fill("Long text.\n\n" + "This sentence keeps the voice busy for a while. " * 120)
    page.locator(".tabitem:visible").get_by_role("button", name="Read it to me").click()
    time.sleep(4)
    page.locator(".tabitem:visible").get_by_role("button", name="Stop").click()
    page.wait_for_selector("text=Nothing was saved", timeout=20_000)
    assert page.locator(".wrap.full:not(.hide)").count() == 0  # progress gone
    run_article(page, "After stopping.\n\nThis should still work.")  # the next run is not blocked
    assert not [e for e in errors if "Stopped" not in e], errors


def test_paper_modes_and_triage(server, browser):
    from tests.conftest import BODY, HEADING  # noqa: F401
    import pymupdf

    pdf = ROOT / ".pytest_cache" / "e2e_paper.pdf"
    pdf.parent.mkdir(exist_ok=True)
    doc = pymupdf.open()
    page_ = doc.new_page()
    page_.insert_text((72, 80), "Abstract", fontsize=16)
    page_.insert_textbox(pymupdf.Rect(72, 100, 520, 300), "We grew 40 seedlings and 30 bent toward light within 2 hours.", fontsize=11)
    page_.insert_text((72, 340), "Introduction", fontsize=16)
    page_.insert_textbox(pymupdf.Rect(72, 360, 520, 600), "Plants sense light. We ask how fast they respond.", fontsize=11)
    doc.save(pdf)

    page, errors = open_page(browser, server)
    page.get_by_role("tab", name="Research paper").click()
    page.locator("input[type=file]:visible, .tabitem:visible input[type=file]").first.set_input_files(str(pdf))
    page.wait_for_function("() => [...document.querySelectorAll('textarea')].some(t => t.value.startsWith('I want to decide'))", timeout=60_000)
    page.get_by_role("button", name="Copy instructions", exact=True).click()
    time.sleep(0.5)
    assert page.evaluate("navigator.clipboard.readText()").startswith("I want to decide")
    for label in ("Quick summary (about 2 minutes)", "Highlights (the most important parts)", "The whole paper"):
        page.get_by_label(label).check()
        page.locator(".tabitem:visible").get_by_role("button", name="Read it to me").click()
        page.wait_for_selector(".tabitem:visible .t2v-player:not(.t2v-empty-player) audio", state="attached", timeout=180_000)
        assert page.locator(".tabitem:visible .t2v-s").count() >= 1
        time.sleep(0.5)
    assert not errors, errors


def test_assistant_script(server, browser):
    page, errors = open_page(browser, server)
    page.get_by_role("tab", name="Assistant script").click()
    page.get_by_label("About 5 minutes").check()
    time.sleep(0.6)
    page.get_by_role("button", name="Copy script instructions").click()
    time.sleep(0.5)
    assert "about 750 words" in page.evaluate("navigator.clipboard.readText()")
    page.get_by_label("Paste the script from your assistant").fill("Sure, here it is!\n\n" + SCRIPT)
    page.locator(".tabitem:visible").get_by_role("button", name="Read it to me").click()
    page.wait_for_selector(".tabitem:visible .t2v-player:not(.t2v-empty-player) audio", state="attached", timeout=180_000)
    captions = " ".join(page.locator(".tabitem:visible .t2v-s").all_inner_texts())
    assert "Seedlings bent 30 degrees" in captions and "Sure" not in captions
    assert not errors, errors


def test_book_generate_listen_download(server, browser, tmp_path):
    epub = make_epub(tmp_path / "fox.epub")
    page, errors = open_page(browser, server)
    page.get_by_role("tab", name="Book").click()
    page.locator(".tabitem:visible input[type=file]").first.set_input_files(str(epub))
    page.wait_for_selector("text=chapters, about", timeout=60_000)
    page.get_by_role("button", name="Start").click()
    page.wait_for_selector("text=All 2 chapters are ready", timeout=300_000)
    page.wait_for_selector(".tabitem:visible .t2v-player:not(.t2v-empty-player) audio", state="attached", timeout=30_000)
    check_dropdown(page, page.get_by_role("combobox", name="Chapter"))
    time.sleep(0.8)
    assert "morning" in page.locator(".tabitem:visible .t2v-captions h4").first.inner_text().lower()  # switched chapter
    page.get_by_role("button", name="Download the whole book").click()
    page.wait_for_selector("text=Your audiobook", timeout=60_000)
    assert not errors, errors


def test_notes_without_any_audio(server, browser):
    """Marking a moment and saving notes must work before anything has been played."""
    page, errors = open_page(browser, server, accept_downloads=True)
    page.locator(".tabitem:visible").get_by_role("button", name="Mark this moment").click()
    page.locator(".tabitem:visible .t2v-notes-text").press_sequentially("idea")
    assert page.locator(".tabitem:visible .t2v-notes-text").input_value().endswith("idea")
    with page.expect_download() as d:
        page.locator(".tabitem:visible").get_by_role("button", name="Save notes").click()
    assert "idea" in Path(d.value.path()).read_text()
    page.evaluate("localStorage.removeItem('t2v-notes')")
    assert not errors, errors


def test_reduced_motion(server, browser):
    page, errors = open_page(browser, server, reduced_motion="reduce")
    assert page.evaluate("getComputedStyle(document.querySelector('.t2v-intro')).animationName") == "none"
    assert page.evaluate("getComputedStyle(document.querySelector('.t2v-header'), '::before').animationName") == "none"
    assert not errors, errors
