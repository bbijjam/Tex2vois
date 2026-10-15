"""Assemble chapter waveforms into a loudness-normalised MP3 / M4B / WAV."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .tts import SAMPLE_RATE

FORMATS = ("m4b", "mp3", "wav")


def ffmpeg() -> str:
    """Path to ffmpeg: the system one if installed, else the copy bundled with imageio-ffmpeg
    (so no Homebrew or admin rights are needed)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as e:
        raise RuntimeError("ffmpeg not found. Run ./setup.sh again, or install ffmpeg.") from e


def _escape(value: str) -> str:
    for ch in ("\\", "=", ";", "#", "\n"):
        value = value.replace(ch, "\\" + ch)
    return value


def chapter_metadata(chapters: list[tuple[str, int]], title: str) -> str:
    """FFMETADATA1 text for chapters given as (title, n_samples)."""
    lines = [";FFMETADATA1", f"title={_escape(title)}", "artist=Tex2vois", "genre=Audiobook"]
    start = 0
    for name, n in chapters:
        end = start + round(n * 1000 / SAMPLE_RATE)
        lines += ["", "[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={_escape(name)}"]
        start = end
    return "\n".join(lines) + "\n"


def export(chapters: list[tuple[str, np.ndarray]], out_path: str | Path, title: str) -> Path:
    out_path = Path(out_path)
    fmt = out_path.suffix.lstrip(".").lower()
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Use one of: {', '.join(FORMATS)}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    audio = np.concatenate([a for _, a in chapters]) if chapters else np.zeros(1, np.float32)
    if fmt == "wav":
        sf.write(out_path, audio, SAMPLE_RATE)
        return out_path


    codec = ["-c:a", "aac", "-b:a", "64k", "-f", "mp4"] if fmt == "m4b" else ["-c:a", "libmp3lame", "-q:a", "4", "-id3v2_version", "3"]
    with tempfile.TemporaryDirectory() as tmp:
        wav, meta = Path(tmp) / "audio.wav", Path(tmp) / "meta.txt"
        sf.write(wav, audio, SAMPLE_RATE)
        meta.write_text(chapter_metadata([(t, len(a)) for t, a in chapters], title), encoding="utf-8")
        cmd = [
            ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(wav), "-i", str(meta), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
            "-af", "loudnorm=I=-18:TP=-1.5:LRA=11",  # podcast/audiobook-style loudness
            "-ar", str(SAMPLE_RATE), *codec, str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()}")
    return out_path
