"""A number, a date or a code on a fact must be stated by its source. Absent from the document it cites, it
was misread or invented, and it blocks; present in the document but not in the quotes, the evidence is
incomplete, and it is a gap. Words are judgements, not literals, and are not checked."""
import json
import os

import pytest

from oto.curate import values

DOC = """# Incident review

Date of incident: 2025-08-02.

The Maintenance Supervisor opened Work Order WO-2291 the same day.
From 1 September the PM-B interval is 20,000 km, not 24,000. The bus was 1,800 km past it.
Reviewed on 5 August 2025. Rear pads were at 12% of their thickness.
"""


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "review.md").write_text(DOC, encoding="utf-8")
    return str(tmp_path)


def _node(nid, attributes, quotes, doc="review"):
    return {"id": nid, "type": "Thing", "label": nid, "attributes": attributes,
            "evidence": [{"doc": doc, "where": "x", "quote": q} for q in quotes]}


def _check(corpus, node, live_node=None):
    live = {"nodes": [live_node] if live_node else []}
    return values.check(live, {"nodes": [node]}, corpus)


def test_a_value_its_quote_states_passes_in_any_usual_format(corpus):
    node = _node("pm.b", {"interval_km": 20000, "past_km": 1800.0, "worn_pct": 12, "code": "WO-2291",
                          "reviewed_on": "2025-08-05"},
                 ["From 1 September the PM-B interval is 20,000 km, not 24,000.", "The bus was 1,800 km past it.",
                  "Rear pads were at 12% of their thickness.", "opened Work Order WO-2291 the same day",
                  "Reviewed on 5 August 2025."])
    assert _check(corpus, node) == []


def test_a_value_the_document_never_states_blocks(corpus):
    found = _check(corpus, _node("pm.b", {"interval_km": 2000, "code": "WO-2219"},
                                 ["From 1 September the PM-B interval is 20,000 km, not 24,000."]))
    assert [(s, subject) for s, subject, _ in found] == [("blocking", "pm.b"), ("blocking", "pm.b")]
    messages = " | ".join(m for _, _, m in found)
    assert "interval_km = 2000 appears nowhere in review" in messages and "code = 'WO-2219'" in messages


def test_a_value_in_the_document_but_not_the_quotes_is_a_gap(corpus):
    found = _check(corpus, _node("wo.2291", {"opened_on": "2025-08-02", "number": "WO-2291"},
                                 ["The Maintenance Supervisor opened Work Order WO-2291 the same day."]))
    assert len(found) == 1 and found[0][0] == "gap"
    assert "opened_on = '2025-08-02' is in review but not in the quotes" in found[0][2]


def test_a_date_written_without_its_year_holds_but_a_different_day_or_year_does_not(tmp_path):
    (tmp_path / "memo.md").write_text("The insured vehicle was hit on 28 Au-\ngust, at the junction. Paid on 3 May 2025.\n",
                                      encoding="utf-8")
    quotes = ["The insured vehicle was hit on 28 August, at the junction."]
    assert values.check({"nodes": []}, {"nodes": [_node("inc.9", {"occurred_on": "2026-08-28"}, quotes, doc="memo")]},
                        str(tmp_path)) == [], "a year is often the document's own, not written in the sentence"
    wrong_day = values.check({"nodes": []}, {"nodes": [_node("inc.9", {"occurred_on": "2026-08-29"}, quotes, doc="memo")]},
                             str(tmp_path))
    assert [s for s, _, _ in wrong_day] == ["blocking"]
    wrong_year = values.check({"nodes": []}, {"nodes": [_node("pay.1", {"paid_on": "2026-05-03"}, ["Paid on 3 May 2025."],
                                                              doc="memo")]}, str(tmp_path))
    assert [s for s, _, _ in wrong_year] == ["blocking"], "a year that is written must be the value's"


def test_a_url_or_an_address_is_a_reference_not_a_literal(corpus):
    node = _node("api.v2", {"url": "http://127.0.0.1:8797/payments/v2", "contact": "ops2@example.com"},
                 ["opened Work Order WO-2291 the same day"])
    assert _check(corpus, node) == []


def test_words_are_not_checked_and_neither_is_a_fact_with_no_quote(corpus):
    assert _check(corpus, _node("wo.2291", {"state": "open", "urgent": True}, ["opened Work Order WO-2291"])) == []
    assert _check(corpus, _node("wo.2291", {"interval_km": 99}, [])) == [], "no evidence is the quote check's finding"


def test_only_what_the_change_brings_is_checked(corpus):
    known = _node("pm.b", {"interval_km": 2000}, ["From 1 September the PM-B interval is 20,000 km, not 24,000."])
    assert _check(corpus, dict(known), live_node=known) == [], "an unchanged fact is not re-judged"
    changed = dict(known, attributes={"interval_km": 2000, "worn_pct": 55})
    found = _check(corpus, changed, live_node=known)
    assert len(found) == 1 and "worn_pct = 55" in found[0][2]


def test_a_document_the_project_does_not_hold_is_not_judged(corpus):
    assert _check(corpus, _node("pm.b", {"interval_km": 2000}, ["anything"], doc="elsewhere")) == []


def test_curate_check_blocks_a_misread_number(tmp_path, capsys):
    from oto.cli import main
    from oto.scaffold import init
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump({"classes": {"Level": {"definition": "A level."}}, "properties": {}, "temporal": {},
                   "attributes": {"Level": {"interval_km": {"type": "integer", "definition": "Distance."}}}}, f)
    os.makedirs(os.path.join(root, "build", "documents"), exist_ok=True)
    with open(os.path.join(root, "build", "documents", "review.md"), "w", encoding="utf-8") as f:
        f.write(DOC)
    assert main(["curate", "start", "--project", root]) == 0
    node = dict(_node("pm.b", {"interval_km": 2000}, ["From 1 September the PM-B interval is 20,000 km, not 24,000."]),
                type="Level", as_of="2025-09-01", valid_from="2025-09-01", source_doc="review", sources=["review"], status="current")
    with open(os.path.join(root, "graph.candidate.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": [node], "edges": []}, f)
    capsys.readouterr()
    assert main(["curate", "check", "--project", root]) == 1
    assert "interval_km = 2000 appears nowhere in review" in capsys.readouterr().out
