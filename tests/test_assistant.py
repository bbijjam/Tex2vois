from tex2vois import assistant, pipeline, triage

REPLY = """Sure! Here is the detailed listening script you asked for.

# Double-stranded DNA protects dsRNA in stink bug saliva

## Introduction

The brown marmorated stink bug, **Halyomorpha halys**, is an invasive pest. RNA interference, or RNAi, can silence genes.

## Results: saliva destroys dsRNA

- Saliva degraded 2 micrograms of dsRNA-GUS within 10 minutes.
- HhNSE was the most highly expressed nuclease.

| table | row |
|---|---|

CONTINUING IN THE NEXT MESSAGE

Adding dsDNA at a 1:1 ratio kept dsRNA stable for 60 minutes (see [Figure 6](http://x)).

END OF SCRIPT

I hope this helps! Let me know if you want a shorter version."""


def test_parse_assistant_reply():
    parsed = assistant.parse(REPLY)
    s = parsed.script
    assert parsed.complete and not parsed.notes
    assert s.title == "Double-stranded DNA protects dsRNA in stink bug saliva" and s.mode == "assistant"
    assert [c.title for c in s.chapters] == ["Introduction", "Results: saliva destroys dsRNA"]
    texts = [p.text for c in s.chapters for p in c.paras]
    assert texts[0].startswith("The brown marmorated stink bug, Halyomorpha halys,")  # bold removed
    assert "Saliva degraded 2 micrograms of dsRNA-GUS within 10 minutes." in texts  # bullet became a paragraph
    assert not any("Sure" in t or "hope this helps" in t or "CONTINUING" in t or "|" in t for t in texts)
    assert any("(see Figure 6)" in t for t in texts)  # link text kept, URL dropped


def test_incomplete_script_is_flagged():
    parsed = assistant.parse("## Methods\n\nNymphs were fed dsRNA for 72 hours.")
    assert not parsed.complete and "continue" in parsed.notes[0]


def test_compare_against_paper():
    paper = "We fed 20 ug dsRNA-CHC for 72 h. HhNSE expression was 7.31-fold higher (p < 0.001). Mortality reached 93.75%."
    script = "Nymphs got 20 micrograms of dsRNA-CHC for 72 hours. HhNSE was 7.31-fold higher, p less than 0.001. Mortality was 95%."
    r = assistant.compare(script, paper)
    assert "93.75" in r["missing"] and "95" in r["not_in_paper"]
    assert 0 < r["coverage"] < 1


def test_script_prompt_and_pipeline_accepts_script():
    p = triage.build_script_prompt("T")
    assert "END OF SCRIPT" in p and "## " in p and "the attached research paper" in p and "1500 words" in p
    s = assistant.parse("# T\n\n## A\n\nHello there.\n\nEND OF SCRIPT").script
    assert pipeline.load(s) is s
