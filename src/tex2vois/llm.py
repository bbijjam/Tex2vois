"""One small client for any OpenAI-compatible chat endpoint: OpenRouter or Ollama.

Provider is chosen by TEX2VOIS_LLM (openrouter | ollama | auto). "auto" uses
OpenRouter when OPENROUTER_API_KEY is set, else a local Ollama.

OpenRouter is restricted to free (":free") models unless TEX2VOIS_ALLOW_PAID=1,
and requests fall back through a list of models, because free models are often
rate-limited upstream.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

OPENROUTER_URL = "https://openrouter.ai/api/v1"
OLLAMA_URL = "http://localhost:11434/v1"

# Free general-purpose models, tried in order. The free catalogue changes often:
# override with TEX2VOIS_MODELS="a:free,b:free".
OPENROUTER_FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling:free",
]
OLLAMA_MODELS = ["qwen2.5:7b"]


class LLMError(RuntimeError):
    pass


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines; never overrides real env vars."""
    for candidate in (Path(path), Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
            return


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


@dataclass
class LLM:
    provider: str
    base_url: str
    models: list[str]
    api_key: str | None = None
    timeout: float = 180
    last_model: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None) -> "LLM":
        load_dotenv()
        key = os.environ.get("OPENROUTER_API_KEY") or None
        provider = (provider or os.environ.get("TEX2VOIS_LLM") or "auto").lower()
        if provider == "auto":
            provider = "openrouter" if key else "ollama"
        override = model or os.environ.get("TEX2VOIS_MODELS")
        if provider == "openrouter":
            if not key:
                raise LLMError("OPENROUTER_API_KEY is not set. Put it in .env (see .env.example).")
            models = override.split(",") if override else OPENROUTER_FREE_MODELS
            paid = [m for m in models if not m.strip().endswith(":free")]
            if paid and os.environ.get("TEX2VOIS_ALLOW_PAID") != "1":
                raise LLMError(f"Refusing paid model(s) {paid}. Use ':free' models or set TEX2VOIS_ALLOW_PAID=1.")
            return cls("openrouter", OPENROUTER_URL, [m.strip() for m in models], key)
        if provider == "ollama":
            models = override.split(",") if override else OLLAMA_MODELS
            return cls("ollama", os.environ.get("OLLAMA_URL", OLLAMA_URL), [m.strip() for m in models])
        raise LLMError(f"Unknown LLM provider '{provider}'. Use openrouter, ollama or auto.")

    def _post(self, model: str, messages: list[dict], max_tokens: int, temperature: float) -> str:
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-Title"] = "Tex2vois"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_context()) as resp:
            data = json.loads(resp.read())
        if "error" in data:
            raise LLMError(str(data["error"])[:200])
        choice = data["choices"][0]
        content = (choice["message"].get("content") or "").strip()
        if not content:
            raise LLMError("empty reply")
        if choice.get("finish_reason") == "length":
            # reasoning models spend part of the budget thinking; a cut-off answer is useless
            raise LLMError("reply cut off at max_tokens")
        return content

    def complete(self, prompt: str, system: str | None = None, max_tokens: int = 4000, temperature: float = 0.2) -> str:
        """Ask each model in turn; return the first non-empty answer."""
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        errors = []
        for model in self.models:
            try:
                answer = self._post(model, messages, max_tokens, temperature)
                self.last_model = model
                return answer
            except urllib.error.HTTPError as e:
                errors.append(f"{model}: HTTP {e.code}")
                if e.code in (401, 403):
                    break  # bad key: no point trying other models
            except urllib.error.URLError as e:
                hint = " Is `ollama serve` running?" if self.provider == "ollama" else ""
                raise LLMError(f"Cannot reach {self.base_url}.{hint}") from e
            except (LLMError, KeyError, ValueError, TimeoutError) as e:
                errors.append(f"{model}: {e}")
        raise LLMError("All models failed: " + "; ".join(errors))
