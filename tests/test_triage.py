from tex2vois import triage


def test_prompt_with_focus_and_attachment():
    p = triage.build("Double-stranded DNA reduces dsRNA degradation", "RNAi delivery in insects")
    assert "Paper: Double-stranded DNA reduces dsRNA degradation" in p
    assert "What I am looking for: RNAi delivery in insects" in p
    assert "the attached paper" in p and "Paper text:" not in p
    assert '"Read in depth"' in p and "not stated" in p


def test_prompt_with_paper_text():
    p = triage.build("T", paper_text="Abstract\n\nWe did things.")
    assert "the paper text included below" in p and p.rstrip().endswith('We did things.\n"""')
    assert "What I am looking for" not in p and "to a general reader" in p


def test_links_are_https():
    assert all(u.startswith("https://") for u in triage.ASSISTANTS.values())
