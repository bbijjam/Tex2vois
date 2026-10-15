"""Text -> waveform with Kokoro-82M (Apache-2.0), running locally."""

from __future__ import annotations

import os
import re
import warnings

import numpy as np

SAMPLE_RATE = 24_000

# A curated subset of Kokoro's voices. First letter = language (a: US, b: UK).
VOICES = {
    "af_heart": "US female · warm (default)",
    "af_bella": "US female · bright",
    "af_nicole": "US female · soft, close-mic",
    "am_michael": "US male · steady",
    "am_fenrir": "US male · deep",
    "am_puck": "US male · lively",
    "bf_emma": "UK female · clear",
    "bm_george": "UK male · classic narrator",
    "bm_fable": "UK male · storyteller",
}
DEFAULT_VOICE = "af_heart"

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


def split_sentences(text: str, max_chars: int = 400) -> list[str]:
    """Split into sentence-ish chunks no longer than max_chars.

    Kokoro handles ~500 phonemes per call; shorter chunks keep prosody stable
    and give smooth progress updates.
    """
    chunks: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            cut = max(sentence.rfind(sep, 0, max_chars) for sep in (", ", "; ", ": ", " "))
            cut = cut if cut > max_chars // 3 else max_chars
            chunks.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


class Synthesizer:
    """Lazily loads one Kokoro pipeline per language and caches it."""

    def __init__(self, device: str | None = "cpu"):
        # On Apple Silicon, CPU beats MPS for an 82M model (see README benchmarks).
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        self.device = device
        self._pipelines: dict[str, object] = {}

    def _pipeline(self, voice: str):
        lang = voice[0]
        if lang not in self._pipelines:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from kokoro import KPipeline

                self._pipelines[lang] = KPipeline(
                    lang_code=lang, repo_id="hexgrad/Kokoro-82M", device=self.device
                )
        return self._pipelines[lang]

    def speak(self, text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> np.ndarray:
        pipeline = self._pipeline(voice)
        parts = []
        for result in pipeline(text, voice=voice, speed=speed, split_pattern=None):
            audio = result.audio
            if audio is not None:
                parts.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
        return np.concatenate(parts).astype(np.float32) if parts else silence(0)
