"""The corpus survey: a deterministic map, and candidates rather than facts."""
import os
import tempfile

import pytest

from oto.intake import survey as sv

HANDBOOK = """# Claims handbook

The Claims Adjuster reviews each First Notice of Loss within two days. Acme Insurance requires
the FNOL form. Disputes go to the Claims Manager.

## Escalation

Escalation reaches the Claims Manager, then the Fraud Unit. Policy dated 2026-02-01.

### Timing

Every day counts. The FNOL form is due first.
"""

MEMO = """# Fraud memo

The Fraud Unit reports to the Claims Manager as of 2026-03-15. FNOL delays are reviewed.
"""


def _corpus(root):
    corpus = os.path.join(root, "documents")
    os.makedirs(os.path.join(corpus, "assets"))
    for name, text in (("handbook.md", HANDBOOK), ("memo.md", MEMO)):
        with open(os.path.join(corpus, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(corpus, "notes.txt"), "w") as f:
        f.write("Not Markdown, Not Read")
    return corpus


def test_profile_reads_title_headings_and_dates():
    p = sv.profile("handbook", HANDBOOK)
    assert p["title"] == "Claims handbook"
    assert p["headings"] == ["Escalation", "Timing"]
    assert p["dates"] == ["2026-02-01"]
    assert p["words"] > 30


def test_recurring_phrases_are_counted_across_documents():
    with tempfile.TemporaryDirectory() as root:
        result = sv.survey(_corpus(root))
    terms = {r["term"]: r for r in result["terms"]}
    assert terms["Claims Manager"]["documents"] == ["handbook", "memo"]
    assert terms["Claims Manager"]["count"] == 3
    assert terms["Fraud Unit"]["documents"] == ["handbook", "memo"]
    assert "First Notice of Loss" not in terms, "mentioned once: below the floor of two"
    assert sv.phrases(HANDBOOK)["First Notice of Loss"] == 1
    # Ranked by how many documents mention them, then mentions.
    assert result["terms"][0]["term"] in ("Claims Manager", "Fraud Unit")


def test_a_capitalised_sentence_start_is_grammar_not_a_name():
    counts = sv.phrases("Every day counts. Disputes go to the Claims Manager. Every claim matters.")
    assert "Every" not in counts
    assert "Disputes" not in counts
    assert counts["Claims Manager"] == 1


def test_acronyms_are_listed_separately():
    with tempfile.TemporaryDirectory() as root:
        result = sv.survey(_corpus(root))
    acronyms = {r["term"]: r for r in result["acronyms"]}
    assert acronyms["FNOL"]["documents"] == ["handbook", "memo"]


def test_only_markdown_is_read_and_assets_are_skipped():
    with tempfile.TemporaryDirectory() as root:
        result = sv.survey(_corpus(root))
    assert [d["slug"] for d in result["documents"]] == ["handbook", "memo"]


def test_report_is_plain_text_and_says_candidates_are_not_facts():
    with tempfile.TemporaryDirectory() as root:
        text = sv.report(sv.survey(_corpus(root)))
    assert "2 document(s)" in text
    assert "Claims Manager" in text
    assert "candidate, not a fact" in text


def test_survey_of_a_missing_corpus_is_empty_not_an_error():
    result = sv.survey("/nonexistent/corpus")
    assert result["totals"]["documents"] == 0 and result["terms"] == []


# ---- the per-document brief ----

def test_brief_says_which_terms_already_resolve(tmp_path):
    corpus = _corpus(str(tmp_path))
    live = {"nodes": [{"id": "role.claims-manager", "type": "Role", "label": "Claims Manager",
                       "aliases": [], "status": "current"}], "edges": []}
    candidate = {"nodes": live["nodes"] + [{"id": "unit.fraud", "type": "Unit", "label": "Fraud Unit",
                                            "aliases": [], "status": "current"}], "edges": []}
    result = sv.brief(corpus, "memo", live, candidate)
    assert result["document"]["title"] == "Fraud memo" and result["candidate_open"]
    rows = {r["term"]: r for r in result["terms"]}
    assert rows["Claims Manager"]["matches"][0]["id"] == "role.claims-manager"
    assert rows["Claims Manager"]["matches"][0]["where"] == "live"
    assert rows["Fraud Unit"]["matches"][0]["where"] == "candidate only"
    text = sv.brief_report(result)
    assert "role.claims-manager" in text and "candidate only" in text
    assert "Reuse a matched id" in text


def test_brief_without_a_candidate_reads_the_live_graph_only(tmp_path):
    corpus = _corpus(str(tmp_path))
    result = sv.brief(corpus, "handbook", {"nodes": [], "edges": []})
    assert not result["candidate_open"]
    assert all(not r["matches"] for r in result["terms"])
    assert "new: derive an id" in sv.brief_report(result)


def test_brief_of_a_missing_document_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sv.brief(_corpus(str(tmp_path)), "nope", {"nodes": []})


def test_a_name_may_end_in_a_number():
    """Machine names, lines and quarters: "Press 01" is one term, not a word and a stray number."""
    counts = sv.phrases("Every shift starts at Press 01. The Line 3 crew reports to the Claims Manager.")
    assert counts["Press 01"] == 1 and counts["Line 3"] == 1 and counts["Claims Manager"] == 1
