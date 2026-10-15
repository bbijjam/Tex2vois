import json
import shutil
import subprocess

import numpy as np
import pytest

from tex2vois import audio
from tex2vois.tts import SAMPLE_RATE


def tone(seconds: float, freq: float = 220) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_chapter_metadata_timings():
    meta = audio.chapter_metadata([("One", SAMPLE_RATE * 2), ("Two; = #", SAMPLE_RATE)], "Book")
    assert "START=0\nEND=2000" in meta
    assert "START=2000\nEND=3000" in meta
    assert r"title=Two\; \= \#" in meta


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffmpeg not installed")
@pytest.mark.parametrize("ext", ["m4b", "mp3"])
def test_export_writes_chapters(tmp_path, ext):
    out = audio.export([("Intro", tone(1.0)), ("Body", tone(2.0, 330))], tmp_path / f"book.{ext}", "Book")
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_chapters", "-show_format", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout)
    assert [c["tags"]["title"] for c in probe["chapters"]] == ["Intro", "Body"]
    assert float(probe["format"]["duration"]) == pytest.approx(3.0, abs=0.15)


def test_export_rejects_unknown_format(tmp_path):
    with pytest.raises(ValueError):
        audio.export([("a", tone(0.1))], tmp_path / "x.ogg", "t")
