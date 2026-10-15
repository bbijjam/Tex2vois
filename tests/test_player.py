import json

import numpy as np

from tex2vois import pipeline, player
from tex2vois.script import from_text
from tex2vois.tts import SAMPLE_RATE


class FakeSynth:
    """0.05 s of silence per character: deterministic durations, no model."""

    def speak(self, text, voice=None, speed=1.0):
        return np.zeros(int(len(text) * 0.05 * SAMPLE_RATE), dtype=np.float32)


def test_captions_match_audio(tmp_path):
    script = from_text("Title line\n\nFirst sentence here. Second one!\n\n## Part two\n\nThird & last <b>.")
    out, seconds, _, cues, caps = pipeline.speak(script, tmp_path / "x.wav", synthesizer=FakeSynth())
    texts = [c["text"] for c in caps]
    assert texts == ["Title line", "First sentence here.", "Second one!", "Part two", "Third & last <b>."]
    starts = [c["start"] for c in caps]
    assert starts == sorted(starts) and all(c["end"] > c["start"] for c in caps)
    for c in caps:  # each caption lasts exactly as long as its synthesised audio
        spoken = c["text"] + ("." if c["kind"] == "title" else "")
        assert abs((c["end"] - c["start"]) - len(spoken) * 0.05) < 0.002
    assert caps[-1]["end"] < seconds  # trailing pauses come after the last word
    assert json.loads(out.with_suffix(".cues.json").read_text())["captions"] == caps


def test_render_escapes_and_marks_sentences(tmp_path):
    script = from_text("T\n\nA <script>alert(1)</script> test. Next.")
    *_, caps = pipeline.speak(script, tmp_path / "x.wav", synthesizer=FakeSynth())
    page = player.render("/gradio_api/file=/tmp/x.wav", caps, "T")
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert page.count('class="t2v-s"') == 2 and page.count("<h4") == 1
    assert 'class="t2v-captions"' in page and "<audio controls" in page
