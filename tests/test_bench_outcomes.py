"""Every answer is right, wrong or abstained, and a confident wrong answer costs more than "I don't know".
The graph system binds only an exact name, and a passage retriever is judged by the source it puts first."""
import json
import os
import tempfile

import pytest

from oto.bench import metrics, run as _run, systems
from oto.builder import build
from oto.project import Project
from oto.scaffold import init


def _entity(resolved=None, status="current", sources=(), abstained=False, match="label"):
    return {"answer_kind": "entity", "resolved_entity": resolved, "answer_status": None if abstained else status,
            "surfaced_sources": list(sources), "abstained": abstained, "match": None if abstained else match}


def _passage(sources=(), abstained=False):
    return {"answer_kind": "passage", "resolved_entity": None, "answer_status": "unknown",
            "surfaced_sources": list(sources), "abstained": abstained or not sources}


FACT = {"id": "f", "type": "factual", "expected_entities": ["m.press"], "supporting_sources": ["handbook"]}
NEG = {"id": "n", "type": "negative", "expected_status": "absent", "supporting_sources": ["handbook"]}
NOW = {"id": "t", "type": "temporal", "expected_status": "current", "expected_entities": ["m.drill-v2"],
       "supporting_sources": ["memo"]}
SOURCES_ONLY = {"id": "s", "type": "factual", "answer": "18 on hand", "supporting_sources": ["stock-sheet"]}


# ---- the outcome of one answer ----

def test_an_entity_answer_is_right_only_when_it_is_the_expected_entity():
    assert metrics.outcome(_entity("m.press"), FACT) == "right"
    assert metrics.outcome(_entity("s.north"), FACT) == "wrong", "a neighbour of the answer is not the answer"
    assert metrics.outcome(_entity(abstained=True), FACT) == "abstained"


def test_a_negative_question_is_answered_right_only_by_abstaining():
    assert metrics.outcome(_entity(abstained=True), NEG) == "right"
    assert metrics.outcome(_entity("m.press"), NEG) == "wrong"
    assert metrics.outcome(_passage(["handbook"]), NEG) == "wrong", "a retriever that always returns something guesses"
    assert metrics.outcome(_passage(abstained=True), NEG) == "right"


def test_a_temporal_question_needs_the_right_status_and_entity():
    assert metrics.outcome(_entity("m.drill-v2"), NOW) == "right"
    assert metrics.outcome(_entity("m.drill", status="superseded"), NOW) == "wrong"
    assert metrics.outcome(_passage(["memo"]), NOW) == "wrong", "a retriever has no notion of time"


def test_a_passage_answer_is_its_first_source():
    assert metrics.outcome(_passage(["handbook", "memo"]), FACT) == "right"
    assert metrics.outcome(_passage(["memo", "handbook"]), FACT) == "wrong"
    assert metrics.outcome(_entity("m.press", sources=["stock-sheet"]), SOURCES_ONLY) == "right"
    assert metrics.outcome(_passage(["memo"]), SOURCES_ONLY) == "wrong"


def test_a_wrong_answer_costs_more_than_an_abstention():
    rows = [{"system": "s", "outcome": o, "strict_entity": None} for o in ("right", "right", "wrong", "abstained")]
    score = _run.answers(rows)["s"]
    assert (score["right"], score["wrong"], score["abstained"]) == (2, 1, 1)
    assert score["precision"] == pytest.approx(2 / 3) and score["coverage"] == pytest.approx(3 / 4)
    assert score["score"] == pytest.approx((2 - 1) / 4)
    guesser = _run.answers([{"system": "g", "outcome": o, "strict_entity": None} for o in ("right", "right", "wrong", "wrong")])["g"]
    assert guesser["score"] < score["score"], "answering everything must not beat abstaining when unsure"


def test_a_cutoff_sweep_regrades_without_rerunning():
    rows = [{"system": "dense", "qid": "a", "outcome": "right", "confidence": 0.8, "negative": False},
            {"system": "dense", "qid": "b", "outcome": "wrong", "confidence": 0.5, "negative": False},
            {"system": "dense", "qid": "c", "outcome": "wrong", "confidence": 0.4, "negative": True}]
    at = {row["cutoff"]: row for row in _run.sweep(rows, (0.0, 0.6))}
    assert (at[0.0]["right"], at[0.0]["wrong"], at[0.0]["abstained"]) == (1, 2, 0)
    assert (at[0.6]["right"], at[0.6]["wrong"], at[0.6]["abstained"]) == (2, 0, 1), \
        "below the cutoff it abstains: right on the negative, abstained on the other"


# ---- the systems, on a built project ----

ONTOLOGY = {"classes": {"Machine": {"definition": "A machine."}, "Site": {"definition": "A site."}},
            "properties": {"installed_at": {"domain": "Machine", "range": "Site", "definition": "Where it runs."}},
            "temporal": {}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook", "status": "current", "sources": ["handbook"]}


def _node(nid, label, aliases=(), summary="", **extra):
    return dict(dict(id=nid, type="Machine", label=label, aliases=list(aliases), summary=summary,
                     attributes={}, tags=[], **STAMP), **extra)


@pytest.fixture(scope="module")
def database():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        graph = {"nodes": [_node("m.press", "Press 01", aliases=["PRS-01"], summary="A stamping press."),
                           _node("m.lathe-a", "Lathe"), _node("m.lathe-b", "Lathe"),
                           _node("m.drill", "Drill 7", status="superseded", valid_to="2026-03-01", superseded_by="m.drill-v2"),
                           _node("m.drill-v2", "Drill 7", supersedes="m.drill", valid_from="2026-03-01", source_doc="memo", sources=["memo"])],
                 "edges": []}
        lexicon = {"entries": [{"term": "stamping machine", "aka": [], "targets": ["m.press"], "status": "current", "note": ""}]}
        for name, payload in (("ontology.config.json", ONTOLOGY), ("graph.json", graph), ("lexicon.json", lexicon)):
            with open(os.path.join(root, name), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        with open(os.path.join(root, "notes", "handbook.md"), "w", encoding="utf-8") as f:
            f.write("# Handbook\n\nThe press stamps panels. Lathes turn shafts.\n")
        project = Project.standard(root)
        build(project)
        yield project.layout.database


def test_the_graph_system_binds_an_exact_name_and_says_how(database):
    oto = systems.OtoSystem(database)
    for words, grade in (("Where is Press 01?", "label"), ("Where is PRS-01?", "alias"),
                         ("Where is the stamping machine?", "lexicon")):
        result = oto.answer({"id": "q", "question": words})
        assert (result["resolved_entity"], result["match"], result["abstained"]) == ("m.press", grade, False), words
    assert oto.answer({"id": "q", "question": "anything", "entity": "Press 01"})["resolved_entity"] == "m.press"


def test_the_graph_system_abstains_on_a_text_hit_or_an_ambiguous_name(database):
    oto = systems.OtoSystem(database)
    near = oto.answer({"id": "q", "question": "Which stamping press is it?"})
    assert near["abstained"] and near["resolved_entity"] is None and near["match"] == "text"
    two = oto.answer({"id": "q", "question": "Where is the Lathe?"})
    assert two["abstained"] and two["match"] == "ambiguous"
    versions = oto.answer({"id": "q", "question": "What is Drill 7 now?"})
    assert versions["resolved_entity"] == "m.drill-v2" and not versions["abstained"], "versions of one name are not ambiguous"


def test_a_generated_card_is_credited_to_its_entitys_sources(database):
    result = systems.LexicalSystem(database).answer({"id": "q", "question": "stamping press panels"})
    assert result["surfaced_sources"] and all("__" not in s for s in result["surfaced_sources"]), result["surfaced_sources"]
    assert "handbook" in result["surfaced_sources"]
