"""Optional: rewrite text for listening with a local LLM via Ollama.

The model is asked to make the text speakable (verbalise symbols, equations,
tables and leftover artefacts) without summarising. A length guard rejects
outputs that drift too far from the input, so a misbehaving model can only
ever fall back to the rule-cleaned text, never lose or invent content.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434"

PROMPT = """You are preparing text to be read aloud by a text-to-speech engine.
Rewrite the passage below so it sounds natural when spoken. Rules:
- Keep every idea and keep the author's wording wherever it already reads well. Do NOT summarise or add commentary.
- Spell out symbols, units, math and equations the way a person would say them (e.g. "x^2" -> "x squared", "≥" -> "greater than or equal to", "5 km" -> "5 kilometres").
- Turn any table-like or list-like fragments into full spoken sentences.
- Remove leftover artefacts: citation markers, footnote numbers, broken hyphenation, stray page headers.
- Output only the rewritten passage, as plain prose, with no preamble.

Passage:
\"\"\"
{text}
\"\"\""""

MIN_RATIO, MAX_RATIO = 0.6, 1.6


class OllamaError(RuntimeError):
    pass


def _generate(prompt: str, model: str, url: str, timeout: float) -> str:
    body = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}
    ).encode()
    req = urllib.request.Request(f"{url}/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["response"].strip()
    except urllib.error.HTTPError as e:
        raise OllamaError(f"Ollama returned {e.code}: {e.read().decode(errors='ignore')}") from e
    except urllib.error.URLError as e:
        raise OllamaError(f"Cannot reach Ollama at {url}. Is `ollama serve` running?") from e


def check_ollama(model: str = DEFAULT_MODEL, url: str = OLLAMA_URL) -> None:
    """Raise OllamaError with a helpful message if the server or model is missing."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as resp:
            names = {m["name"] for m in json.loads(resp.read())["models"]}
    except urllib.error.URLError as e:
        raise OllamaError(f"Cannot reach Ollama at {url}. Is `ollama serve` running?") from e
    if model not in names and f"{model}:latest" not in names:
        raise OllamaError(f"Model '{model}' not found. Run: ollama pull {model}")


def accept(original: str, rewritten: str) -> bool:
    if not rewritten:
        return False
    ratio = len(rewritten) / max(len(original), 1)
    return MIN_RATIO <= ratio <= MAX_RATIO


def rewrite_paragraphs(
    paragraphs: list[str],
    model: str = DEFAULT_MODEL,
    url: str = OLLAMA_URL,
    max_chars: int = 1500,
    timeout: float = 300,
) -> tuple[list[str], int, int]:
    """Rewrite paragraphs in batches of ~max_chars.

    Returns (paragraphs, n_batches, n_rejected).
    """
    batches: list[list[str]] = [[]]
    for p in paragraphs:
        if batches[-1] and sum(len(x) for x in batches[-1]) + len(p) > max_chars:
            batches.append([])
        batches[-1].append(p)

    out: list[str] = []
    rejected = 0
    for batch in batches:
        if not batch:
            continue
        original = "\n\n".join(batch)
        rewritten = _generate(PROMPT.format(text=original), model, url, timeout).strip('"').strip()
        if accept(original, rewritten):
            out.extend(p.strip() for p in rewritten.split("\n\n") if p.strip())
        else:
            rejected += 1
            out.extend(batch)
    return out, len([b for b in batches if b]), rejected
