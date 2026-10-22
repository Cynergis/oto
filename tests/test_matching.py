"""A name binds to an entity only when it matches: by id, label, alias or the lexicon. A text hit, two
entities sharing a name, or a word nobody declared is said in words, never answered as if it matched."""
import importlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

from oto.builder import build
from oto.project import Project
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ONTOLOGY = {
    "classes": {"Machine": {"definition": "A machine."}, "Site": {"definition": "A place where machines run."}},
    "properties": {"installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts", "definition": "Where a machine runs."}},
    "temporal": {},
}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook", "status": "current", "sources": ["handbook"]}


def _node(nid, kind, label, aliases=(), summary="", **extra):
    return dict(dict(id=nid, type=kind, label=label, aliases=list(aliases), summary=summary, attributes={}, tags=[], **STAMP), **extra)


GRAPH = {
    "nodes": [
        _node("s.north", "Site", "North Plant"),
        _node("s.south", "Site", "South Plant"),
        _node("m.press", "Machine", "Press 01", aliases=["PRS-01"], summary="A stamping press."),
        _node("m.lathe-a", "Machine", "Lathe", summary="The lathe in the north hall."),
        _node("m.lathe-b", "Machine", "Lathe", summary="The lathe in the south hall."),
        _node("m.drill", "Machine", "Drill 7", status="superseded", valid_to="2026-03-01", superseded_by="m.drill-v2"),
        _node("m.drill-v2", "Machine", "Drill 7", supersedes="m.drill", as_of="2026-03-01", valid_from="2026-03-01"),
    ],
    "edges": [{"from": "m.press", "rel": "installed_at", "to": "s.north"},
              {"from": "m.lathe-a", "rel": "installed_at", "to": "s.north"},
              {"from": "m.lathe-b", "rel": "installed_at", "to": "s.south"},
              {"from": "m.drill", "rel": "installed_at", "to": "s.north"},
              {"from": "m.drill-v2", "rel": "installed_at", "to": "s.south"}],
}
LEXICON = {"entries": [{"term": "stamping machine", "aka": [], "targets": ["m.press"], "status": "current", "note": ""},
                       {"term": "kiln", "aka": [], "targets": [], "status": "not_ingested", "note": "no document yet"}]}
QUESTIONS = {"questions": {"Q1": {"question": "Where is machine $MACHINE installed?", "why": "To find a machine.",
                                  "params": {"MACHINE": {"type": "Machine"}},
                                  "ask": {"when": [{"edge": ["$MACHINE", "installed_at", "s"]}, {"node": "s", "type": "Site"}],
                                          "select": ["s.label"]},
                                  "gate": "any"}}}


@pytest.fixture(scope="module")
def root():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="Test KB")
        for name, payload in (("ontology.config.json", ONTOLOGY), ("graph.json", GRAPH),
                              ("lexicon.json", LEXICON), ("questions.json", QUESTIONS)):
            with open(os.path.join(root, name), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        build(Project.standard(root))
        yield root


def _query(root, *args):
    r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root] + list(args),
                       cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), capture_output=True, text=True)
    return r.stdout


def test_an_exact_name_answers_and_says_how_it_matched(root):
    assert "=== Press 01" in _query(root, "entity", "m.press")
    by_label = _query(root, "entity", "Press 01")
    assert "=== Press 01" in by_label and "matched by label 'Press 01'" in by_label
    by_alias = _query(root, "entity", "PRS-01")
    assert "=== Press 01" in by_alias and "matched by alias 'PRS-01'" in by_alias
    by_lexicon = _query(root, "entity", "Stamping Machine")
    assert "=== Press 01" in by_lexicon and "matched by lexicon 'Stamping Machine'" in by_lexicon


def test_a_text_hit_is_named_as_a_near_miss_never_answered(root):
    out = _query(root, "entity", "stamping press")
    assert "=== Press 01" not in out, "a text hit answered as if the name matched"
    assert "No entity matched 'stamping press'" in out
    assert "Closest by text, not a match: Press 01 (m.press)" in out
    assert "=== " not in _query(root, "neighbors", "stamping press")


def test_two_current_entities_sharing_a_name_are_ambiguous(root):
    out = _query(root, "entity", "Lathe")
    assert "=== Lathe" not in out
    assert "'Lathe' is ambiguous: it names 2 entities: Lathe (m.lathe-a), Lathe (m.lathe-b)" in out


def test_a_word_the_graph_does_not_record_says_so(root):
    out = _query(root, "entity", "driver")
    assert "No entity matched 'driver'" in out
    assert "the vocabulary declares no class, relation or attribute called 'driver'" in out
    as_class = _query(root, "entity", "Machine")
    assert "'Machine' is a class of the vocabulary, not an entity" in as_class and "kg_by_type Machine" in as_class
    unread = _query(root, "entity", "kiln")
    assert "=== " not in unread and "No entity matched 'kiln'" in unread, "a not-ingested lexicon entry binds nothing"


def test_a_supersession_answers_now_and_as_of_a_date(root):
    assert "South Plant" in _query(root, "entity", "Drill 7").split("Other matches")[0]
    before = _query(root, "entity", "Drill 7", "--as-of", "2026-02-01")
    assert "(m.drill)" in before.splitlines()[0] and "North Plant" in before
    after = _query(root, "entity", "Drill 7", "--as-of", "2026-04-01")
    assert "(m.drill-v2)" in after.splitlines()[0] and "South Plant" in after


def test_a_question_binds_only_a_match(root):
    assert "North Plant" in _query(root, "ask", "Q1", "MACHINE=stamping machine")
    near = _query(root, "ask", "Q1", "MACHINE=stamping press")
    assert "No entity matched 'stamping press' for MACHINE." in near and "status:" not in near
    assert "Closest by text, not a match: Press 01 (m.press)" in near
    two = _query(root, "ask", "Q1", "MACHINE=Lathe")
    assert "'Lathe' is ambiguous" in two and "status:" not in two


def test_resolve_reports_the_grade_and_never_calls_a_text_hit_a_match(root):
    exact = _query(root, "resolve", "PRS-01")
    assert "entity: Press 01  (m.press)  [current], matched by alias" in exact
    near = _query(root, "resolve", "stamping press")
    assert "no entity is named 'stamping press'; closest by text, not a match: Press 01 (m.press)" in near


def test_the_http_rows_carry_the_grade_and_refuse_a_near_miss(root):
    from oto.serve import payload as _payload
    project = Project.standard(root)
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine
    importlib.reload(engine)
    engine.ensure_fresh()
    exact = _payload.tool_data(engine, "kg_entity", {"term": "PRS-01"})
    assert exact["resolved"] == "m.press" and exact["match"] == "alias"
    near = _payload.tool_data(engine, "kg_entity", {"term": "stamping press"})
    assert near["resolved"] is None and near["match"] == "text" and near["candidates"] == ["m.press"]
    two = _payload.tool_data(engine, "kg_entity", {"term": "Lathe"})
    assert two["resolved"] is None and two["match"] == "ambiguous" and sorted(two["alternatives"]) == ["m.lathe-a", "m.lathe-b"]
