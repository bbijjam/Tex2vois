"""Ready-to-paste instructions for Claude, ChatGPT or any chat assistant:
"should I read this paper in depth?"

Tex2vois does not call these services; the reader copies the instructions
(optionally with the paper's cleaned text) and pastes them into the assistant
of their choice.
"""

from __future__ import annotations

import re

ASSISTANTS = {
    "Claude": "https://claude.ai/new",
    "ChatGPT": "https://chatgpt.com/",
}

PROMPT = """I want to decide whether this research paper is worth reading in depth. Please review {what} and reply in exactly this format, using short plain-language sentences.

Paper: {title}
{focus_line}{context_line}
1. Takeaway: the main finding in one sentence.
2. Question: what problem the authors address and why it matters.
3. What they did: the organism, system or data studied, and the main methods.
4. Key findings: up to five bullet points, each with the exact numbers reported (effect sizes, p-values, sample sizes).
5. Strength of evidence: sample sizes, replicates, controls, and whether it is a peer-reviewed article or a preprint.
6. Limitations: what the authors admit and anything important they do not address.
7. Relevance{relevance_to}: high, medium or low, with one sentence explaining why.
8. Verdict: choose one of "Read in depth", "Skim the abstract, figures and discussion", or "Skip", and give two or three reasons.
9. If worth reading: which sections, figures or tables to read first.

Rules:
- Use only what is in the paper. Copy numbers, gene, protein and species names exactly.
- If something is not reported, write "not stated" instead of guessing.
- If you add context from outside the paper, label it clearly as outside context.
- Keep the whole answer under 400 words."""


def _context_line(context: str, purpose: str) -> str:
    context = re.sub(r"\s+", " ", context or "").strip()
    return f"About me and my work: {context}\n({purpose})\n" if context else ""


def build(title: str, focus: str = "", paper_text: str | None = None, context: str = "") -> str:
    focus = (focus or "").strip()
    prompt = PROMPT.format(
        what="the paper text included below" if paper_text else "the attached paper",
        title=title or "(see the attached file)",
        focus_line=f"What I am looking for: {focus}\n" if focus else "",
        context_line=_context_line(context, "Use this only to judge relevance and the verdict; it must not change what you report from the paper."),
        relevance_to=(f" to what I am looking for ({focus})" if focus else " to my work" if context.strip() else " to a general reader in this field"),
    )
    if paper_text:
        prompt += "\n\nPaper text:\n\"\"\"\n" + paper_text.strip() + "\n\"\"\""
    return prompt


SCRIPT_END = "END OF SCRIPT"
SCRIPT_CONTINUE = "CONTINUING IN THE NEXT MESSAGE"

WORDS_PER_MINUTE = 150
LENGTHS = {  # minutes of listening; 0 = everything
    "About 5 minutes": 5,
    "About 10 minutes": 10,
    "About 20 minutes": 20,
    "Everything, nothing left out": 0,
}

LENGTH_FULL = """- Cover every section, including the methods, every result, and every figure and table. For each figure or table, say what it shows and its key values, as you would to someone who cannot see it.
- Do not shorten anything to save space."""

LENGTH_TIMED = """- Length: about {words} words, which is about {minutes} minutes when read aloud. Stay close to this length.
- Within that length, cover every section briefly, and spend most of the words on the main results: what was found, the key numbers, and the most important figures, said in words.
- Keep the methods to what a listener needs to trust the results. Leave out minor details rather than rushing through everything."""

SCRIPT_PROMPT = """Please turn {what} into a listening script. It will be read aloud by a text-to-speech voice to someone who wants to understand the paper without reading it.

Paper: {title}
{context_line}
Format (follow it exactly, because the script is read automatically):
- First line: "# " followed by the paper's title.
- Start each section with a line beginning "## ", for example "## Introduction", "## Methods", "## Results: the first finding", "## Discussion". Keep the paper's order.
- Write everything else as plain spoken paragraphs separated by a blank line.
- Do not use bullet points, numbered lists, tables, bold, italics, links or code.
- Finish with a line that says exactly: {end}

Content:
{length_rules}
- Copy every number, unit, p-value, sample size, and gene, protein and species name you mention exactly as in the paper.
- Say symbols, units and equations the way a person reads them aloud (for example "p less than 0.01", "micromoles per square metre per second", "x squared"), and explain what each equation means in words.
- Spell out each abbreviation the first time it is used.
- Leave out references, citation numbers, acknowledgements, funding and author details.
- Do not add opinions or anything that is not in the paper. If something in the paper is unclear, say so.
- If you reach your reply length limit, stop at the end of a paragraph and write "{cont}". When I reply "continue", carry on exactly where you stopped without repeating anything."""


def build_script_prompt(title: str, paper_text: str | None = None, context: str = "", minutes: int = 10) -> str:
    length_rules = LENGTH_TIMED.format(words=minutes * WORDS_PER_MINUTE, minutes=minutes) if minutes else LENGTH_FULL
    prompt = SCRIPT_PROMPT.format(
        length_rules=length_rules,
        context_line=_context_line(context, 'Where it genuinely helps, add a short paragraph starting "Relevant to your work:" '
                                            "after the section it relates to. Never leave anything out because of this."),
        what="the research paper text included below" if paper_text else "the attached research paper",
        title=title or "(see the attached file)",
        end=SCRIPT_END,
        cont=SCRIPT_CONTINUE,
    )
    if paper_text:
        prompt += "\n\nPaper text:\n\"\"\"\n" + paper_text.strip() + "\n\"\"\""
    return prompt
