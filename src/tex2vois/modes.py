"""Listening modes for research papers: full, skim, summary.

* full    - every cleaned paragraph.
* skim    - mostly the paper's own words: abstract, the question the
            introduction ends on, the first paragraph of each results /
            discussion section, the conclusion, plus a one-paragraph spoken
            recap of the methods (LLM, if available). About a third of the length.
* summary - a ~250 word spoken overview written by the LLM, fact-checked
            against the paper; falls back to the abstract without an LLM.

Every skim paragraph keeps `source` = the id of the full-script paragraph it
came from, so a player can jump into the full reading at the same spot.
"""

from __future__ import annotations

from .llm import LLM, LLMError
from .rewrite import missing_facts
from .script import Chapter, Para, Script

MODES = ("full", "skim", "summary")

METHODS_PROMPT = """Summarise the methods of a research paper in 2-3 spoken sentences for a listener:
the organism or system studied, the main experimental or computational approaches, and the key measurements.
Use only what the text says. No preamble.

Methods text:
\"\"\"
{text}
\"\"\""""

SUMMARY_PROMPT = """Write a spoken summary (about 250 words) of the research paper below, for someone listening on a commute.
Cover: the problem and why it matters, what the authors did, the main findings with their key numbers, and the main limitation or open question.
Skip test statistics (F, t, chi-square values, degrees of freedom); mention a p-value only when it is the point.
Use only facts stated in the text; copy every number, gene, protein and species name exactly. Plain prose, no headings, no lists, no preamble.

Paper:
\"\"\"
{text}
\"\"\""""


def _sources(chapter: Chapter, indexes) -> list[Para]:
    return [Para(f"s-{p.id}", p.text, p.id) for i, p in enumerate(chapter.paras) if i in indexes]


def skim(script: Script, llm: LLM | None = None) -> Script:
    chapters: list[Chapter] = []
    notes: list[str] = []
    for ch in script.chapters:
        n = len(ch.paras)
        if ch.role == "abstract":
            keep = _sources(ch, range(n))
        elif ch.role == "introduction":
            keep = _sources(ch, {n - 1})  # intros end on the gap and the question
        elif ch.role in ("results", "discussion", "body"):
            keep = _sources(ch, {0})
        elif ch.role == "conclusion":
            keep = _sources(ch, range(n))
        elif ch.role == "methods":
            keep = []
            if llm is not None:
                text = "\n\n".join(p.text for p in ch.paras)[:12000]
                try:
                    recap = llm.complete(METHODS_PROMPT.format(text=text), max_tokens=2000)
                    if not missing_facts(recap, text):  # nothing invented
                        keep = [Para(f"s-{ch.paras[0].id}", "In brief, the methods. " + recap, ch.paras[0].id)]
                    else:
                        notes.append("methods recap rejected by the fact check; methods skipped")
                except LLMError as e:
                    notes.append(f"methods recap unavailable ({e}); methods skipped")
        else:
            keep = []
        if keep:
            chapters.append(Chapter(ch.title, keep, ch.role))
    if not chapters:
        raise ValueError("Nothing to skim: no recognisable sections.")
    return Script(script.title, chapters, script.kind, "skim", notes)


def summary(script: Script, llm: LLM | None = None) -> Script:
    abstract = next((c for c in script.chapters if c.role == "abstract"), None)
    if llm is not None:
        text = script.to_markdown()[:60000]
        try:
            answer = llm.complete(SUMMARY_PROMPT.format(text=text), max_tokens=4000, temperature=0.3)
            invented = missing_facts(answer, text)  # numbers/names not in the paper
            if not invented:
                paras = [p.strip() for p in answer.split("\n\n") if p.strip()]
                return Script(script.title, [Chapter("Summary", [Para(f"sum{i}", t) for i, t in enumerate(paras, 1)], "summary")], script.kind, "summary")
            note = f"LLM summary rejected: mentions {', '.join(sorted(invented)[:5])} which are not in the paper"
        except LLMError as e:
            note = f"LLM summary unavailable ({e})"
    else:
        note = "no LLM configured"
    if abstract is None:
        raise ValueError(f"No summary possible: {note}, and no abstract found.")
    return Script(script.title, [Chapter("Summary", _sources(abstract, range(len(abstract.paras))), "summary")],
                  script.kind, "summary", [note + "; reading the abstract instead."])


def apply(script: Script, mode: str, llm: LLM | None = None) -> Script:
    if mode == "full":
        return script
    if mode == "skim":
        return skim(script, llm)
    if mode == "summary":
        return summary(script, llm)
    raise ValueError(f"Unknown mode '{mode}'. Use one of: {', '.join(MODES)}")
