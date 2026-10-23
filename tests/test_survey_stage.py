"""The survey's first stage: deterministic, quoted, and measured. Every fix must earn its place against
gold term lists on two unrelated corpora, so the chain cannot grow noise while looking thorough."""
import json
import os
import shutil

import pytest

from oto.intake import survey as sv, termscore

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "survey")
CORPORA = ("fleet", "incidents")


def _write(tmp_path, documents):
    corpus = tmp_path / "documents"
    corpus.mkdir()
    for name, text in documents.items():
        (corpus / (name + ".md")).write_text(text, encoding="utf-8")
    return str(corpus)


def _by_term(result):
    return {c["term"]: c for c in result["candidates"]}


HEADER = "> **Source:** `inbox/{0}.docx` · **Type:** Word document · Converted to Markdown by the OTO extraction pipeline.\n"


# ---- each fix, on and off ----

def test_the_provenance_header_is_not_the_corpus(tmp_path):
    corpus = _write(tmp_path, {n: "# %s\n\n%s\nThe Fraud Unit met.\n" % (n, HEADER.format(n)) for n in ("a", "b")})
    assert not {"Converted", "Markdown", "OTO", "Type", "Source"} & set(_by_term(sv.survey(corpus)))
    # The header's last sentence is identical in every converted file, so boilerplate removes it too.
    assert "Markdown" in _by_term(sv.survey(corpus, off=("header", "boilerplate"))), "with both off, the header is counted"


def test_a_code_is_one_identifier_not_an_acronym_and_a_phrase(tmp_path):
    corpus = _write(tmp_path, {"a": "The Supervisor opened Work Order WO-2291 for PM-B. BRK-221 is low.\n",
                               "b": "Work Order WO-2291 covers PM-B and BRK-221 at the depot.\n"})
    found = _by_term(sv.survey(corpus))
    assert found["WO-2291"]["kind"] == "code" and found["PM-B"]["kind"] == "code" and found["BRK-221"]["kind"] == "code"
    assert "PM" not in found and "BRK" not in found, "a code's prefix is not an acronym"
    assert "Work Order" in found and not any(t.startswith("Work Order WO") for t in found), "a code ends a phrase"
    without = _by_term(sv.survey(corpus, off=("codes",)))
    assert "PM" in without and without["PM"]["kind"] == "acronym"


def test_a_name_never_crosses_a_paragraph_or_a_heading(tmp_path):
    corpus = _write(tmp_path, {"a": "## Measures\nMean Time To Recovery is tracked.\n\n## Statements\n\n1. The Fraud Unit met.\n",
                               "b": "## Measures\nMean Time To Recovery fell.\n\n## Statements\n\n1. The Fraud Unit closed.\n"})
    found = _by_term(sv.survey(corpus))
    assert "Mean Time To Recovery" in found and "Measures Mean Time To Recovery" not in found
    assert "Statements 1" not in found
    assert "Measures Mean Time To Recovery" in _by_term(sv.survey(corpus, off=("paragraphs",)))


def test_a_sentence_repeated_word_for_word_across_documents_is_template(tmp_path):
    template = "This note records statements made in conversation, in the speaker's words. "
    corpus = _write(tmp_path, {"a": template + "The Fraud Unit met.\n", "b": template + "The Fraud Unit closed it.\n"})
    found = _by_term(sv.survey(corpus))
    assert "note records statements" not in found and "speaker's words" not in found and "Fraud Unit" in found
    assert "note records statements" in _by_term(sv.survey(corpus, off=("boilerplate",)))


def test_the_capture_header_is_otos_words_too(tmp_path):
    header = "> **Captured:** 2025-09-01 · **By:** Dana Reyes · **Recorded by:** an agent · **About:** pm.pm-b\n"
    corpus = _write(tmp_path, {"a": "# A\n\n" + header + "The Fraud Unit met.\n", "b": "# B\n\n" + header + "The Fraud Unit met.\n"})
    assert not {"Recorded", "About", "Captured"} & set(_by_term(sv.survey(corpus)))


def test_an_all_capitals_word_is_an_acronym_not_also_a_phrase(tmp_path):
    corpus = _write(tmp_path, {"a": "The service breached its SLO today.\n", "b": "Every team owns an SLO now.\n"})
    found = sv.survey(corpus)
    assert "SLO" in {c["term"] for c in found["acronyms"]} and "SLO" not in {c["term"] for c in found["terms"]}
    assert "SLO" in {c["term"] for c in sv.survey(corpus, off=("acronyms",))["terms"]}


def test_plural_and_case_variants_are_one_candidate(tmp_path):
    corpus = _write(tmp_path, {"a": "Open a Work Order. The two Work Orders wait. The Claims Manager met the claims manager.\n",
                               "b": "A Work Order closed. Ask the claims manager first.\n"})
    found = _by_term(sv.survey(corpus))
    assert found["Work Order"]["count"] == 3 and "Work Orders" in found["Work Order"]["variants"]
    assert "Work Orders" not in found
    assert found["Claims Manager"]["count"] == 3 and "claims manager" in found["Claims Manager"]["variants"]
    unmerged = _by_term(sv.survey(corpus, off=("plurals",)))["Work Order"]
    assert unmerged["count"] == 2 and "Work Orders" not in unmerged["variants"]


def test_a_lowercase_term_recurring_across_documents_is_found(tmp_path):
    corpus = _write(tmp_path, {"a": "The service burned its error budget. A rollback plan exists.\n",
                               "b": "When the error budget is spent, deploys stop. Each rollback plan is tested.\n",
                               "c": "Only one soft limit appears here.\n"})
    found = _by_term(sv.survey(corpus))
    assert found["error budget"]["documents"] == ["a", "b"] and "rollback plan" in found
    assert "soft limit" not in found, "seen in one document only"
    assert "error budget" not in _by_term(sv.survey(corpus, off=("lowercase",)))


def test_an_acronym_defined_in_the_text_carries_its_expansion_and_quote(tmp_path):
    corpus = _write(tmp_path, {"a": "Mean Time To Recovery (MTTR) rose. The SLO (service level objective) was breached.\n",
                               "b": "MTTR fell. The SLO held. Mean Time To Recovery is tracked weekly.\n"})
    found = _by_term(sv.survey(corpus))
    assert found["MTTR"]["expansion"]["text"] == "Mean Time To Recovery"
    assert found["MTTR"]["expansion"]["doc"] == "a" and "(MTTR)" in found["MTTR"]["expansion"]["quote"]
    assert found["SLO"]["expansion"]["text"] == "service level objective"
    assert "Mean Time To Recovery" not in found and "Mean Time To Recovery" in found["MTTR"]["variants"], \
        "the long form is the acronym's row, not a second one to review"
    assert "expansion" not in _by_term(sv.survey(corpus, off=("expansions",)))["MTTR"]


# ---- the candidate list ----

def test_every_candidate_is_counted_and_quoted(tmp_path):
    corpus = _write(tmp_path, {"a": "The Fraud Unit met. The Claims Manager reports to the Fraud Unit.\n",
                               "b": "The Fraud Unit closed it.\n"})
    result = sv.survey(corpus)
    unit = _by_term(result)["Fraud Unit"]
    assert (unit["evidence"], unit["stage"], unit["kind"]) == ("counted", "counted", "phrase")
    assert [q["doc"] for q in unit["quotes"]] == ["a", "b"] and all("Fraud Unit" in q["text"] for q in unit["quotes"])
    assert {"term": "Fraud Unit", "count": 3, "documents": ["a", "b"]}.items() <= result["terms"][0].items(), \
        "the rows the survey always returned keep their shape"


# ---- the measurement ----

def test_scoring_counts_found_missed_and_noise():
    result = {"candidates": [{"term": "Work Order", "variants": ["Work Orders"]}, {"term": "Fraud Unit", "variants": []},
                             {"term": "Converted", "variants": []}]}
    gold = [{"term": "Work Orders"}, {"term": "Fraud Unit"}, {"term": "Claims Manager"}]
    score = termscore.score(result, gold)
    assert score["found"] == ["Fraud Unit", "Work Orders"] and score["missed"] == ["Claims Manager"]
    assert score["noise"] == ["Converted"]
    assert score["recall"] == pytest.approx(2 / 3) and score["precision"] == pytest.approx(2 / 3)
    assert score["review_load"] == pytest.approx(3 / 2), "candidates read per real term found"


def test_a_gold_list_says_who_wrote_it(tmp_path):
    path = tmp_path / "terms.jsonl"
    path.write_text('{"term": "Fraud Unit"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="_meta"):
        termscore.load(str(path))


# ---- the rules CI holds the stage to, on two unrelated corpora ----

def _scored(name, off=()):
    meta, gold = termscore.load(os.path.join(FIXTURES, name, "terms.jsonl"))
    return termscore.score(sv.survey(os.path.join(FIXTURES, name, "documents"), off=off), gold)


def test_the_stage_beats_the_survey_it_replaces_on_both_corpora():
    for name in CORPORA:
        now, before = _scored(name), _scored(name, off=sv.FIXES)
        assert now["recall"] > before["recall"], name
        assert now["review_load"] < before["review_load"], name


def test_every_fix_earns_its_place():
    """Switching one fix off must not help: across both corpora it may not raise recall, and it must
    lower recall or precision, or raise the review load. A fix that fails this is removed, not kept."""
    full = [_scored(name) for name in CORPORA]
    for fix in sv.FIXES:
        off = [_scored(name, off=(fix,)) for name in CORPORA]
        recall_on, recall_off = sum(s["recall"] for s in full), sum(s["recall"] for s in off)
        precision_on, precision_off = sum(s["precision"] for s in full), sum(s["precision"] for s in off)
        load_on, load_off = sum(s["review_load"] for s in full), sum(s["review_load"] for s in off)
        assert recall_off <= recall_on + 1e-9, "%s: recall is higher without it" % fix
        assert recall_off < recall_on - 1e-9 or precision_off < precision_on - 1e-9 or load_off > load_on + 1e-9, \
            "%s adds nothing measurable" % fix


def test_no_corpus_falls_below_its_recorded_floor():
    with open(os.path.join(FIXTURES, "floors.json"), encoding="utf-8") as f:
        floors = json.load(f)
    for name in CORPORA:
        score = _scored(name)
        assert score["recall"] >= floors[name]["recall"] - 1e-9, name
        assert score["precision"] >= floors[name]["precision"] - 1e-9, name
        assert score["review_load"] <= floors[name]["review_load"] + 1e-9, name


# ---- the command ----

def test_the_command_scores_and_ablates_against_the_projects_gold_list(tmp_path, capsys):
    from oto.cli import main
    from oto.scaffold import init
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    shutil.copytree(os.path.join(FIXTURES, "incidents", "documents"), os.path.join(root, "build", "documents"), dirs_exist_ok=True)
    os.makedirs(os.path.join(root, "gold"), exist_ok=True)
    shutil.copy(os.path.join(FIXTURES, "incidents", "terms.jsonl"), os.path.join(root, "gold", "terms.jsonl"))
    capsys.readouterr()
    assert main(["survey", "--project", root, "--score", "--ablations"]) == 0
    out = capsys.readouterr().out
    assert "MODEL-AUTHORED" in out, "the gold list's provenance leads the score"
    assert "recall" in out and "precision" in out and "review load" in out
    assert "without codes" in out and "none (the survey before this stage)" in out
