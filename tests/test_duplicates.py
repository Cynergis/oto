"""A new entity close in meaning to one the graph holds, under another name, is shown as a possible
duplicate: advisory, opt-in, and never a reason to refuse. Only entities of the same class compare."""
import json
import os

import pytest

from oto.curate import duplicates

#: A stand-in embedding: each axis a meaning, so the tests say what the logic does, not what a model returns.
AXES = ({"garage", "depot", "yard"}, {"central", "centre", "middle"}, {"east", "eastern"},
        {"pad", "pads", "brake"}, {"rear", "back"}, {"front"})


def fake_embed(texts):
    out = []
    for text in texts:
        words = set(text.lower().replace(".", " ").replace(",", " ").replace("(", " ").replace(")", " ").split())
        out.append([float(len(words & axis)) for axis in AXES])
    return out


def _node(nid, kind, label, summary="", **extra):
    return dict({"id": nid, "type": kind, "label": label, "summary": summary, "status": "current"}, **extra)


LIVE = {"nodes": [_node("garage.central", "Garage", "Central Garage"), _node("garage.east", "Garage", "East Garage"),
                  _node("part.rear", "Part", "Rear brake pads"), _node("part.front", "Part", "Front brake pads")],
        "edges": []}


def _with(*nodes):
    return {"nodes": LIVE["nodes"] + list(nodes), "edges": []}


def test_a_new_entity_close_in_meaning_to_one_of_its_class_is_flagged():
    graph = _with(_node("garage.central-depot", "Garage", "Central Depot"))
    found = duplicates.find(graph, ["garage.central-depot"], embed=fake_embed, min_similarity=0.9)
    assert [(f["id"], [m["id"] for m in f["matches"]]) for f in found] == [("garage.central-depot", ["garage.central"])]
    assert 0.9 <= found[0]["matches"][0]["similarity"] <= 1.0


def test_another_class_is_never_compared_and_a_weak_match_is_not_shown():
    graph = _with(_node("role.central", "Role", "Central Garage"), _node("garage.west", "Garage", "West Yard"))
    assert duplicates.find(graph, ["role.central"], embed=fake_embed, min_similarity=0.9) == []
    assert duplicates.find(graph, ["garage.west"], embed=fake_embed, min_similarity=0.9) == []


def test_every_close_sibling_is_listed_for_the_person_to_choose():
    graph = _with(_node("part.pads", "Part", "Brake pads"))
    found = duplicates.find(graph, ["part.pads"], embed=fake_embed, min_similarity=0.7)
    assert sorted(m["id"] for m in found[0]["matches"]) == ["part.front", "part.rear"]


def test_a_successor_is_not_a_duplicate_of_what_it_supersedes():
    graph = _with(_node("garage.central-2026", "Garage", "Central Garage", supersedes="garage.central"))
    assert duplicates.find(graph, ["garage.central-2026"], embed=fake_embed, min_similarity=0.9) == []


def test_only_the_new_entities_are_judged():
    assert duplicates.find(_with(), [], embed=fake_embed, min_similarity=0.5) == []


@pytest.fixture
def project(tmp_path, monkeypatch):
    from oto.cli import main
    from oto.scaffold import init
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump({"classes": {"Garage": {"definition": "A garage."}}, "properties": {}, "temporal": {}}, f)
    stamp = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "memo", "sources": ["memo"], "aliases": [],
             "attributes": {}, "tags": []}
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": [dict(_node("garage.central", "Garage", "Central Garage"), **stamp)], "edges": []}, f)
    proposal = {"source_doc": "memo", "nodes": [dict(_node("garage.central-depot", "Garage", "Central Depot"), **stamp)], "edges": []}
    path = os.path.join(root, "proposals", "memo.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f)
    assert main(["curate", "start", "--project", root]) == 0
    monkeypatch.setattr(duplicates, "embed", fake_embed)
    monkeypatch.setattr(duplicates, "available", lambda: (True, ""))
    return root, path


def test_add_and_check_show_a_possible_duplicate_and_never_refuse_for_it(project, capsys):
    from oto.cli import main
    root, path = project
    capsys.readouterr()
    assert main(["curate", "add", "--project", root, "--from", path, "--dry-run", "--duplicates"]) == 0
    assert "MAYBE    garage.central-depot" in capsys.readouterr().out
    assert main(["curate", "add", "--project", root, "--from", path]) == 0
    capsys.readouterr()
    assert main(["curate", "check", "--project", root, "--duplicates"]) == 0, "advisory: a gap, never blocking"
    out = capsys.readouterr().out
    assert "possible duplicate by meaning of garage.central" in out
    assert main(["curate", "check", "--project", root]) == 0
    assert "possible duplicate" not in capsys.readouterr().out, "opt-in"


def test_without_the_model_it_says_not_run(project, capsys, monkeypatch):
    from oto.cli import main
    root, path = project
    monkeypatch.setattr(duplicates, "available", lambda: (False, "fastembed is not installed"))
    capsys.readouterr()
    assert main(["curate", "add", "--project", root, "--from", path, "--dry-run", "--duplicates"]) == 0
    assert "duplicates by meaning: not run (fastembed is not installed)" in capsys.readouterr().out


def test_siblings_whose_identifier_codes_differ_are_distinct_things():
    """PM-A beside PM-B, BRK-220 beside BRK-221: the descriptions differ only by the code, so a model
    scores them as near-identical, but two different codes name two different things."""
    graph = _with(_node("garage.pm-a", "Garage", "PM-A at Central Garage"),
                  _node("garage.pm-b", "Garage", "PM-B at Central Garage"),
                  _node("garage.brk-220", "Garage", "BRK-220 at Central Garage"),
                  _node("garage.brk-221", "Garage", "BRK-221 at Central Garage"))
    found = duplicates.find(graph, ["garage.pm-b", "garage.brk-221"], embed=fake_embed, min_similarity=0.9)
    assert {f["id"]: sorted(m["id"] for m in f["matches"]) for f in found} == \
        {"garage.pm-b": ["garage.central"], "garage.brk-221": ["garage.central"]}, \
        "a code missing on one side still compares"


def test_the_same_code_under_two_names_is_still_a_possible_duplicate():
    graph = _with(_node("garage.brk-221", "Garage", "BRK-221 at Central Garage"),
                  _node("garage.brk-221-depot", "Garage", "BRK-221 at Central Depot"))
    found = duplicates.find(graph, ["garage.brk-221-depot"], embed=fake_embed, min_similarity=0.9)
    assert "garage.brk-221" in [m["id"] for m in found[0]["matches"]]
