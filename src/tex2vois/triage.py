"""Ready-to-paste instructions for Claude, ChatGPT or any chat assistant:
"should I read this paper in depth?"

Tex2vois does not call these services; the reader copies the instructions
(optionally with the paper's cleaned text) and pastes them into the assistant
of their choice.
"""

from __future__ import annotations

ASSISTANTS = {
    "Claude": "https://claude.ai/new",
    "ChatGPT": "https://chatgpt.com/",
}

PROMPT = """I want to decide whether this research paper is worth reading in depth. Please review {what} and reply in exactly this format, using short plain-language sentences.

Paper: {title}
{focus_line}
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


def build(title: str, focus: str = "", paper_text: str | None = None) -> str:
    focus = (focus or "").strip()
    prompt = PROMPT.format(
        what="the paper text included below" if paper_text else "the attached paper",
        title=title or "(see the attached file)",
        focus_line=f"What I am looking for: {focus}\n" if focus else "",
        relevance_to=f" to what I am looking for ({focus})" if focus else " to a general reader in this field",
    )
    if paper_text:
        prompt += "\n\nPaper text:\n\"\"\"\n" + paper_text.strip() + "\n\"\"\""
    return prompt
