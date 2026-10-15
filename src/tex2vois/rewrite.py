"""Optional: rewrite text for listening with an LLM (OpenRouter free models or Ollama).

The model makes text speakable (symbols, units, stats, leftover artefacts)
without summarising. Two guards decide whether a rewrite is accepted:

* length: the rewrite must stay within 0.6-1.6x the original length;
* facts: every number, gene/protein-style term (HhCHC, dsRNA-CHC, AtMYB75,
  pin1-4) and abbreviated species name (A. thaliana) in the original must
  still be present.

A rejected batch falls back to the rule-cleaned text, so a misbehaving model
can never silently drop or alter content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .llm import LLM
from .script import Chapter, Para, Script

PROMPT = """You are preparing text to be read aloud by a text-to-speech engine.
Rewrite the passage below so it sounds natural when spoken. Rules:
- Keep every idea and keep the author's wording wherever it already reads well. Do NOT summarise or add commentary.
- Keep every number, gene or protein name, species name and abbreviation exactly as written.
- Spell out symbols, units, math and statistics the way a person would say them (e.g. "x^2" -> "x squared", "p < 0.01" -> "p less than 0.01", "5 km" -> "5 kilometres").
- Turn table-like or list-like fragments into full spoken sentences.
- Remove leftover artefacts: citation markers, footnote numbers, broken hyphenation, stray page headers.
- Keep paragraph breaks (blank lines). Output only the rewritten passage, as plain prose, with no preamble.

Passage:
\"\"\"
{text}
\"\"\""""

MIN_RATIO, MAX_RATIO = 0.6, 1.6
NUMBER_WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()

_HYPHENS = re.compile(r"[‐‑‒–−]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_TERM = re.compile(r"\b[A-Za-z]*(?:[a-z][A-Z]|[A-Z]{2}|[A-Za-z]\d|\d[A-Za-z])[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")
_SPECIES = re.compile(r"\b[A-Z]\. [a-z]{3,}")


def _norm(text: str) -> str:
    return _HYPHENS.sub("-", text).replace(" ", " ")


def facts(text: str) -> set[str]:
    text = _norm(text)
    return set(_NUMBER.findall(text)) | set(_TERM.findall(text)) | set(_SPECIES.findall(text))


def missing_facts(original: str, rewritten: str) -> set[str]:
    out = _norm(rewritten)
    lowered = out.lower()
    words = set(re.findall(r"[a-z]+", lowered))
    missing = set()
    for fact in facts(original):
        if fact in out or fact.replace(",", "") in out.replace(",", ""):
            continue
        if fact.isdigit() and int(fact) <= 20 and NUMBER_WORDS[int(fact)] in lowered:
            continue  # "3-fold" -> "threefold"
        if fact.lower() in words:
            continue
        missing.add(fact)
    return missing


def accept(original: str, rewritten: str) -> tuple[bool, str]:
    if not rewritten:
        return False, "empty"
    ratio = len(rewritten) / max(len(original), 1)
    if not MIN_RATIO <= ratio <= MAX_RATIO:
        return False, "length"
    if missing_facts(original, rewritten):
        return False, "facts"
    return True, ""


@dataclass
class RewriteStats:
    batches: int = 0
    rejected_length: int = 0
    rejected_facts: int = 0
    failed: int = 0

    @property
    def rejected(self) -> int:
        return self.rejected_length + self.rejected_facts + self.failed


def _batches(paras: list[Para], max_chars: int) -> list[list[Para]]:
    out: list[list[Para]] = [[]]
    for p in paras:
        if out[-1] and sum(len(x.text) for x in out[-1]) + len(p.text) > max_chars:
            out.append([])
        out[-1].append(p)
    return [b for b in out if b]


def rewrite_script(script: Script, llm: LLM, max_chars: int = 1500, progress=None) -> tuple[Script, RewriteStats]:
    stats = RewriteStats()
    chapters = []
    total = sum(len(c.paras) for c in script.chapters) or 1
    done = 0
    for chapter in script.chapters:
        new_paras: list[Para] = []
        for batch in _batches(chapter.paras, max_chars):
            stats.batches += 1
            original = "\n\n".join(p.text for p in batch)
            try:
                rewritten = llm.complete(PROMPT.format(text=original)).strip('"').strip()
            except Exception:
                stats.failed += 1
                rewritten = ""
            ok, why = accept(original, rewritten) if rewritten else (False, "")
            if ok:
                parts = [x.strip() for x in rewritten.split("\n\n") if x.strip()]
                if len(parts) == len(batch):
                    new_paras += [Para(p.id, t, p.source) for p, t in zip(batch, parts)]
                else:
                    new_paras += [Para(f"{batch[0].id}r{i}", t, batch[0].source or batch[0].id) for i, t in enumerate(parts)]
            else:
                stats.rejected_length += why == "length"
                stats.rejected_facts += why == "facts"
                new_paras += batch
            done += len(batch)
            if progress:
                progress(done / total, f"Rewriting for listening: {chapter.title}")
        chapters.append(Chapter(chapter.title, new_paras, chapter.role))
    return Script(script.title, chapters, script.kind, script.mode), stats
