import json
import urllib.error

import pytest

from tex2vois import modes, pipeline
from tex2vois.llm import LLM, LLMError
from tex2vois.rewrite import rewrite_script
from tex2vois.script import Chapter, Para, Script, from_text, role_of


class FakeLLM(LLM):
    """Returns canned answers in order; raises if an answer is an exception."""

    def __init__(self, *answers):
        super().__init__("fake", "http://fake", ["fake:free"])
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt, system=None, max_tokens=2000, temperature=0.2):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        self.last_model = "fake:free"
        return answer


def paper() -> Script:
    def ch(title, *texts):
        return Chapter(title, [Para(f"{title[:3]}{i}", t) for i, t in enumerate(texts, 1)], role_of(title))

    return Script("Test paper", [
        ch("Abstract", "We silenced HhCHC in H. halys and saw 93% mortality."),
        ch("Introduction", "Stink bugs are pests.", "RNAi is promising.", "We asked whether dsDNA protects dsRNA."),
        ch("Materials and methods", "Nymphs were fed 20 ug dsRNA-CHC for 72 h.", "RNA was extracted."),
        ch("Results", "Saliva degraded dsRNA within 10 minutes.", "dsDNA slowed degradation."),
        ch("Discussion", "dsDNA is a cheap protectant.", "Uptake remains a barrier."),
        ch("Acknowledgements-free body", "Extra modelling details."),
    ], kind="paper")


def test_roles():
    assert [role_of(t) for t in ("2. Materials and methods", "RESULTS", "Conclusions", "Model formulation")] == [
        "methods", "results", "conclusion", "body"]


def test_skim_extractive_keeps_sources():
    s = modes.skim(paper(), llm=None)
    texts = [p.text for c in s.chapters for p in c.paras]
    assert texts[0].startswith("We silenced HhCHC")
    assert "We asked whether dsDNA protects dsRNA." in texts  # last intro paragraph
    assert "RNAi is promising." not in texts
    assert "Saliva degraded dsRNA within 10 minutes." in texts and "dsDNA slowed degradation." not in texts
    assert all(p.source for c in s.chapters for p in c.paras)  # every skim paragraph maps back
    assert not any(c.role == "methods" for c in s.chapters)  # no LLM, no methods recap


def test_skim_methods_recap_rejected_if_it_invents_numbers():
    ok = modes.skim(paper(), FakeLLM("Nymphs were fed 20 ug of dsRNA-CHC over 72 h, then RNA was extracted."))
    assert any(c.role == "methods" for c in ok.chapters)
    bad = modes.skim(paper(), FakeLLM("Nymphs were fed 50 ug of dsRNA-CHC over 96 h."))
    assert not any(c.role == "methods" for c in bad.chapters)


def test_summary_uses_llm_then_falls_back_to_abstract():
    good = modes.summary(paper(), FakeLLM("Silencing HhCHC in H. halys caused 93% mortality.\n\nUptake remains a barrier."))
    assert [p.text for p in good.chapters[0].paras][0].startswith("Silencing HhCHC")
    invented = modes.summary(paper(), FakeLLM("Silencing caused 99% mortality."))
    assert invented.chapters[0].paras[0].text.startswith("We silenced HhCHC")  # abstract fallback
    offline = modes.summary(paper(), FakeLLM(LLMError("rate limited")))
    assert offline.chapters[0].paras[0].source == "Abs1"


def test_rewrite_script_keeps_ids_and_falls_back():
    s = Script("t", [Chapter("Results", [Para("c1p1", "HhCHC fell 3-fold."), Para("c1p2", "p < 0.01 here.")])])
    out, stats = rewrite_script(s, FakeLLM("HhCHC fell threefold.\n\np less than 0.01 here."))
    assert [p.id for p in out.chapters[0].paras] == ["c1p1", "c1p2"] and stats.rejected == 0
    out, stats = rewrite_script(s, FakeLLM("The gene fell threefold.\n\np less than 0.01 here."))
    assert out.chapters[0].paras[0].text == "HhCHC fell 3-fold." and stats.rejected_facts == 1


def test_article_from_text():
    s = from_text("Why sleep matters\n\nSleep helps memory (e.g. learning).\n\n## Tips\n\nKeep a schedule.")
    assert s.title == "Why sleep matters" and s.kind == "article"
    assert [c.title for c in s.chapters] == ["Why sleep matters", "Tips"]
    assert s.chapters[0].paras[0].text == "Sleep helps memory (for example, learning)."
    assert pipeline.load("Just one line of text.").chapters[0].paras[0].text == "Just one line of text."


def test_llm_falls_back_across_models(monkeypatch):
    llm = LLM("openrouter", "https://x", ["busy:free", "ok:free"], "key")
    calls = []

    def post(model, *a):
        calls.append(model)
        if model == "busy:free":
            raise urllib.error.HTTPError("u", 429, "rate limited", {}, None)
        return "hello"

    monkeypatch.setattr(llm, "_post", post)
    assert llm.complete("hi") == "hello" and calls == ["busy:free", "ok:free"] and llm.last_model == "ok:free"


def test_llm_refuses_paid_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.delenv("TEX2VOIS_ALLOW_PAID", raising=False)
    with pytest.raises(LLMError, match="paid"):
        LLM.from_env("openrouter", "openai/gpt-5")
    assert LLM.from_env("openrouter", "a:free,b:free").models == ["a:free", "b:free"]


def test_summary_without_ai_or_abstract_uses_key_paragraphs():
    s = paper()
    s.chapters = [c for c in s.chapters if c.role != "abstract"]  # a paper with no recognisable abstract
    out = modes.summary(s, llm=None)
    texts = [p.text for p in out.chapters[0].paras]
    assert texts and "We asked whether dsDNA protects dsRNA." in texts  # the question the intro ends on
    assert all(p.source for p in out.chapters[0].paras)
    assert "own key paragraphs" in out.notes[0] and "Claude or ChatGPT" in out.notes[0]
    assert "LLM" not in out.notes[0] and "Ollama" not in out.notes[0]


def test_summary_with_no_sections_starts_at_the_beginning():
    s = Script("t", [Chapter("Part 1", [Para("c1p1", "Plain text with no headings at all.")], "body")], kind="paper")
    assert modes.summary(s, None).chapters[0].paras[0].text.startswith("Plain text")


def test_auto_provider_without_key_or_ollama(monkeypatch):
    import tex2vois.llm as llm_mod

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TEX2VOIS_LLM", raising=False)
    monkeypatch.setattr(llm_mod, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(llm_mod, "_ollama_running", lambda url: False)
    with pytest.raises(LLMError, match="No AI available"):
        LLM.from_env()
