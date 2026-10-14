"""Quotes that hold: a fact cites the sentence that says it, and the sentence is in its document.
Nothing stands in for a missing quote; `oto curate check` refuses a quote its document does not hold
and reports, document by document, the facts that quote nothing or cannot be checked."""
import json
import os
import tempfile

from oto.apps import studio
from oto.cli import main
from oto.compile import capture as _capture
from oto.curate import evidence, propose as _propose
from oto.project import Project
from oto.scaffold import init

from test_capture import CAPTURE

MEMO = """# Intake memo

**C-9** was opened on 1 September.
The insured vehicle was hit on 28 Au-
gust, at the “north” junction – a rear-end collision. The adjuster's deﬁnition of the case is [final](http://x).

| Step | Who |
|---|---|
| Intake assigned to the adjuster. | adjuster |
"""


def test_a_quote_is_found_whatever_extraction_and_typing_changed_but_not_when_its_words_differ():
    text = evidence.normalise(MEMO)
    for quote in ("C-9 was opened on 1 September.", "The insured vehicle was hit on 28 August",
                  'at the "north" junction - a rear-end collision', "the adjuster's definition of the case is final",
                  "Intake assigned to the adjuster.", "C-9 was opened … hit on 28 August", "c-9 was opened...1 september"):
        assert evidence.found(quote, text), quote
    for quote in ("C-9 was opened on 2 September.", "hit on 28 August … C-9 was opened", "", "…"):
        assert not evidence.found(quote, text), quote


def test_nothing_stands_in_for_a_missing_place_or_quote():
    schema = _capture.for_ontology("auto-claims")
    item = {"type": "Claim", "id": "C-1", "label": "Claim C-1", "fields": {"claim_number": "C-1", "state": "open"}}
    proposal = _propose.propose({"doc": "memo", "as_of": "2026-09-01", "items": [item]}, schema)
    assert proposal["nodes"][0]["evidence"] == [{"doc": "memo"}], "not the item's id as a place, nor its name as a quote"


def _node(nid, evidence_, label="x"):
    return {"id": nid, "type": "Claim", "label": label, "evidence": evidence_}


def test_the_check_refuses_a_quote_not_in_its_document_and_reports_the_rest_by_document():
    with tempfile.TemporaryDirectory() as corpus:
        open(os.path.join(corpus, "memo.md"), "w", encoding="utf-8").write(MEMO)
        candidate = {"nodes": [
            _node("claim.a", [{"doc": "memo", "where": "p.1", "quote": "C-9 was opened on 1 September."}]),
            _node("claim.b", [{"doc": "memo", "where": "p.1", "quote": "C-9 was opened on 2 September."}]),
            _node("claim.c", [{"doc": "memo", "where": "table 1"}]),
            _node("claim.d", [{"doc": "memo", "where": "p.2"}]),
            _node("claim.e", [{"doc": "minutes", "where": "§1", "quote": "Anything at all."}]),
            {"id": "claim.f", "type": "Claim", "label": "f", "source_type": "human_assertion", "evidence": []}]}
        found = evidence.check({"nodes": []}, candidate, corpus)
        blocking = [f for f in found if f[0] == "blocking"]
        assert [f[1] for f in blocking] == ["claim.b"] and "is not in the document it cites (memo)" in blocking[0][2]
        gaps = {f[1]: f[2] for f in found if f[0] == "gap"}
        assert gaps["memo"].startswith("2 fact(s) from this document say where they come from but not the sentence") and "claim.c, claim.d" in gaps["memo"]
        assert "does not hold this document" in gaps["minutes"] and "claim.e" in gaps["minutes"]


def test_only_what_the_change_brings_is_judged_and_a_restated_fact_gains_its_quote():
    with tempfile.TemporaryDirectory() as corpus:
        open(os.path.join(corpus, "memo.md"), "w", encoding="utf-8").write(MEMO)
        old = [{"doc": "memo", "where": "p.1", "quote": "Claim C-9"}]
        live = {"nodes": [_node("claim.c-9", old, "Claim C-9")]}
        assert evidence.check(live, {"nodes": [_node("claim.c-9", old, "Claim C-9")]}, corpus) == [], "what was saved before is not re-judged"
        tightened = old + [{"doc": "memo", "where": "p.1", "quote": "C-9 was opened on 1 September."}]
        assert evidence.check(live, {"nodes": [_node("claim.c-9", tightened, "Claim C-9")]}, corpus) == []
        assert evidence.no_sentence(_node("claim.c-9", old, "Claim C-9")), "its name standing in for a quote is no sentence"
        assert not evidence.no_sentence(_node("claim.c-9", tightened, "Claim C-9"))


def test_each_studio_page_says_in_one_line_how_many_of_its_facts_quote_no_sentence():
    with tempfile.TemporaryDirectory() as base:
        page = os.path.join(base, "claims")
        os.makedirs(page)
        json.dump({"name": "claims", "title": "Claims", "place": "domain", "shows": ["Claim"], "open": ["AC"], "entry": "index.html"},
                  open(os.path.join(page, "app.json"), "w"))
        open(os.path.join(page, "index.html"), "w").write("<title>claims</title>")
        payload = {"vocabulary": {"classes": {"Claim": {}}}, "nodes": [
            _node("claim.a", [{"doc": "memo", "quote": "C-9 was opened on 1 September."}], "A"),
            _node("claim.b", [{"doc": "memo", "quote": "B"}], "B"), _node("claim.c", [{"doc": "memo"}], "C")]}
        data = studio.data([("claims", page)], payload, [])
        assert data["open"]["claims"] == [{"who": "", "items": [{"label": None, "gaps": [
            "2 facts on this page do not quote the sentence they come from yet."]}]}]


def test_curate_check_refuses_a_misquote_and_passes_the_exact_one(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Claims", ontology="auto-claims")
        project = Project.standard(root)
        os.makedirs(project.layout.corpus, exist_ok=True)
        open(os.path.join(project.layout.corpus, "intake-memo.md"), "w", encoding="utf-8").write(MEMO)
        misquoted = json.loads(json.dumps(CAPTURE))
        misquoted["items"][0]["quote"] = "C-9 was opened on 2 September."
        path = os.path.join(root, "capture.json")
        json.dump(misquoted, open(path, "w", encoding="utf-8"))
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "propose", "--project", root, "--from", path]) == 0
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, "proposals", "intake-memo.json")]) == 0
        capsys.readouterr()
        assert main(["curate", "check", "--project", root]) != 0
        out = capsys.readouterr().out
        assert "its quote is not in the document it cites (intake-memo)" in out and "ready to apply" not in out
        assert main(["curate", "apply", "--project", root, "--by", "test", "--note", "x"]) != 0, "apply refuses it too"
        assert main(["curate", "start", "--project", root, "--force"]) == 0
        json.dump(CAPTURE, open(path, "w", encoding="utf-8"))
        assert main(["curate", "propose", "--project", root, "--from", path]) == 0
        assert main(["curate", "add", "--project", root, "--from", os.path.join(root, "proposals", "intake-memo.json")]) == 0
        capsys.readouterr()
        assert main(["curate", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "ready to apply" in out and "not in the document" not in out
