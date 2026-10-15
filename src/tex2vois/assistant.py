"""Listening scripts written by the reader's own AI assistant (Claude, ChatGPT, ...).

The assistant is asked (see triage.build_script_prompt) for "# title", "## section"
headings, plain paragraphs and a final END OF SCRIPT line. Assistants don't always
comply, so the parser is forgiving: it drops chatter before the script and after
the end marker, "continuing" markers between messages, and leftover Markdown
(bold, bullets, tables, links, code fences).

`compare` checks the script against the paper: how many of the paper's numbers
and names made it in, and which numbers or names in the script are not in the
paper at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import clean
from .rewrite import facts
from .script import Chapter, Para, Script, role_of
from .triage import SCRIPT_CONTINUE, SCRIPT_END

_CHATTER = re.compile(r"^(sure|certainly|of course|here('s| is)|below is|absolutely|great)\b", re.I)
_END = re.compile(r"^\W*" + re.escape(SCRIPT_END) + r"\W*$", re.I)
_CONTINUE = re.compile(r"^\W*(" + re.escape(SCRIPT_CONTINUE) + r"|\(?continued\)?|continue[ds]?( from (the )?(previous|last) message)?)\W*$", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BOLD_HEADING = re.compile(r"^\*\*([^*]{2,90})\*\*:?$")
_LIST = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+")
_TABLE = re.compile(r"^\s*\|.*\|\s*$|^\s*[-:| ]{3,}\s*$")


def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)  # links
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)  # bold
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)  # italics
    text = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


@dataclass
class Parsed:
    script: Script
    complete: bool
    notes: list[str]


def parse(text: str, title: str | None = None) -> Parsed:
    lines = text.replace("\r\n", "\n").split("\n")
    doc_title, complete = title, False
    chapters: list[tuple[str, list[str]]] = []
    para: list[str] = []
    in_code = False
    started = False

    def flush():
        if para:
            if not chapters:
                chapters.append(("", []))
            chapters[-1][1].append(" ".join(para))
        para.clear()

    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if _END.match(line):
            complete = True
            break  # anything after the end marker is the assistant talking
        if not line:
            flush()
            continue
        if _CONTINUE.match(line) or _TABLE.match(line) or line in ("---", "***", "___"):
            flush()
            continue
        heading = _HEADING.match(line) or _BOLD_HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1)) if heading.re is _HEADING else 2
            name = _inline(heading.group(2) if heading.re is _HEADING else heading.group(1))
            if level == 1 and not doc_title:
                doc_title = name
            elif level >= 2 or doc_title:
                chapters.append((name, []))
            started = True
            continue
        if not started and _CHATTER.match(line):
            continue  # "Sure, here is the script for ..."
        started = True
        if _LIST.match(line):
            flush()
            line = _LIST.sub("", line)
        para.append(_inline(line))
    flush()

    chapters = [(t, [p for p in (clean.clean(x) for x in ps) if p and not clean.is_noise(p)]) for t, ps in chapters]
    chapters = [(t or doc_title or "Script", ps) for t, ps in chapters if ps]
    if not chapters:
        raise ValueError("No script text found. Paste the whole answer from your assistant.")
    out = [Chapter(t, [Para(f"c{ci}p{pi}", p) for pi, p in enumerate(ps, 1)], role_of(t)) for ci, (t, ps) in enumerate(chapters, 1)]
    script = Script(doc_title or chapters[0][0], out, kind="paper", mode="assistant")
    notes = [] if complete else [
        f'The script does not end with "{SCRIPT_END}", so your assistant may have stopped early. '
        'If it did, reply "continue" to it and paste the rest underneath.'
    ]
    return Parsed(script, complete, notes)


def _significant(items: set[str]) -> set[str]:
    """Facts worth tracking: drop single digits and bare years, which are mostly noise."""
    return {f for f in items if not re.fullmatch(r"\d|(19|20)\d\d", f)}


def compare(script_text: str, paper_text: str) -> dict:
    """Coverage of the paper's numbers/names in the script, and script facts missing from the paper."""
    norm = lambda s: re.sub(r"[‐-–−]", "-", s).replace(",", "")
    script_n, paper_n = norm(script_text), norm(paper_text)
    paper_facts = _significant({norm(f) for f in facts(paper_text)})
    script_facts = _significant({norm(f) for f in facts(script_text)})
    covered = {f for f in paper_facts if f in script_n}
    invented = sorted(f for f in script_facts if f not in paper_n)
    return {
        "paper_facts": len(paper_facts),
        "covered": len(covered),
        "coverage": len(covered) / len(paper_facts) if paper_facts else 1.0,
        "missing": sorted(paper_facts - covered),
        "not_in_paper": invented,
    }
