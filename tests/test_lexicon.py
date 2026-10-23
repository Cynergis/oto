"""Embeddings suggest what a word means; only a named person decides. A suggestion never reaches the
lexicon on its own, and an accepted entry makes the word resolve deterministically, for every reader."""
import json
import os
import tempfile

import pytest

from oto.cli import main
from oto.model import lexicon as _lexicon
from oto.project import Project
from oto.scaffold import init

ONTOLOGY = {"classes": {"Machine": {"definition": "A machine."}, "Site": {"definition": "A place where machines run."}},
            "properties": {"installed_at": {"domain": "Machine", "range": "Site", "definition": "Where it runs."}},
            "temporal": {}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook", "status": "current", "sources": ["handbook"]}
GRAPH = {"nodes": [dict(id="m.press", type="Machine", label="Press 01", aliases=["PRS-01"], summary="A stamping press.", **STAMP),
                   dict(id="m.lathe", type="Machine", label="Lathe 3", aliases=[], summary="Turns shafts.", **STAMP),
                   dict(id="s.north", type="Site", label="North Plant", aliases=[], summary="The north works.", **STAMP)],
         "edges": [{"from": "m.press", "rel": "installed_at", "to": "s.north"}]}

#: A stand-in for an embedding model: each axis is a meaning, and a text points along the axes its words
#: belong to. Deterministic, so the tests say what the logic does, not what a model happens to return.
AXES = ({"press", "stamping", "stamp", "stamper"}, {"site", "plant", "works", "depot", "yard"},
        {"lathe", "turns", "turning", "shafts"})


def fake_embed(texts):
    out = []
    for text in texts:
        words = set(text.lower().replace(".", " ").replace(",", " ").replace("(", " ").replace(")", " ").split())
        out.append([float(len(words & axis)) for axis in AXES])
    return out


@pytest.fixture
def project():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        for name, payload in (("ontology.config.json", ONTOLOGY), ("graph.json", GRAPH)):
            with open(os.path.join(root, name), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        yield Project.standard(root)


def _lexicon_file(project):
    path = os.path.join(project.data, "lexicon.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"entries": []}


def test_a_suggestion_names_its_target_and_runner_up_and_writes_nothing_live(project):
    result = _lexicon.suggest(project, terms=["stamper", "depot"], embed=fake_embed, min_similarity=0.5)
    by_term = {s["term"]: s for s in result["suggestions"]}
    assert by_term["stamper"]["target"] == "m.press" and by_term["depot"]["target"] == "s.north"
    assert 0.5 <= by_term["stamper"]["similarity"] <= 1.0 and "runner_up" in by_term["stamper"]
    assert _lexicon_file(project)["entries"] == [], "a suggestion is not an entry"
    saved = json.load(open(os.path.join(project.data, _lexicon.SUGGESTIONS), encoding="utf-8"))
    assert {s["term"] for s in saved["suggestions"]} == {"stamper", "depot"}


def test_a_real_models_float32_vectors_are_written_as_plain_numbers(project):
    np = pytest.importorskip("numpy")
    result = _lexicon.suggest(project, terms=["stamper"], min_similarity=0.5,
                              embed=lambda texts: [np.array(v, dtype="float32") for v in fake_embed(texts)])
    assert result["suggestions"][0]["target"] == "m.press"
    saved = json.load(open(os.path.join(project.data, _lexicon.SUGGESTIONS), encoding="utf-8"))
    assert isinstance(saved["suggestions"][0]["similarity"], float)


def test_a_word_equally_near_two_entities_is_unclear_not_proposed(project):
    result = _lexicon.suggest(project, terms=["press lathe"], embed=fake_embed, min_similarity=0.5, min_margin=0.05)
    assert result["suggestions"] == []
    unclear = result["unclear"][0]
    assert unclear["term"] == "press lathe" and {c["target"] for c in unclear["candidates"]} == {"m.press", "m.lathe"}
    with pytest.raises(ValueError, match="no suggestion"):
        _lexicon.accept(project, "press lathe", by="Sam")
    assert _lexicon.accept(project, "press lathe", by="Sam", target="m.press")["targets"] == ["m.press"], \
        "a person settles it by naming the target"


def test_a_name_the_graph_already_has_is_not_suggested_and_a_weak_match_is_not_proposed(project):
    result = _lexicon.suggest(project, terms=["PRS-01", "north plant", "invoice"], embed=fake_embed, min_similarity=0.5)
    assert result["suggestions"] == []
    assert result["known"] == ["PRS-01", "north plant"] and result["unmatched"] == ["invoice"]


def test_accepting_needs_a_person_and_writes_a_dated_attributed_entry(project):
    _lexicon.suggest(project, terms=["stamper"], embed=fake_embed, min_similarity=0.5)
    with pytest.raises(ValueError, match="--by"):
        _lexicon.accept(project, "stamper", by="")
    entry = _lexicon.accept(project, "stamper", by="Sam Lee, analyst", at="2026-10-22")
    assert entry["targets"] == ["m.press"] and entry["status"] == "current"
    assert "accepted by Sam Lee, analyst on 2026-10-22" in entry["note"] and "similarity" in entry["note"]
    assert _lexicon_file(project)["entries"] == [entry]
    assert _lexicon.pending(project) == [], "an accepted suggestion leaves the queue"


def test_accept_refuses_an_unknown_target_and_a_term_mapped_elsewhere(project):
    with pytest.raises(ValueError, match="not in the graph"):
        _lexicon.accept(project, "stamper", by="Sam", target="m.ghost")
    _lexicon.accept(project, "stamper", by="Sam", target="m.press")
    with pytest.raises(ValueError, match="already maps"):
        _lexicon.accept(project, "stamper", by="Sam", target="m.lathe")
    with pytest.raises(ValueError, match="no suggestion"):
        _lexicon.accept(project, "yard", by="Sam")


def test_a_rejected_suggestion_is_not_made_again(project):
    _lexicon.suggest(project, terms=["depot"], embed=fake_embed, min_similarity=0.5)
    _lexicon.reject(project, "depot", by="Dana Reyes")
    again = _lexicon.suggest(project, terms=["depot"], embed=fake_embed, min_similarity=0.5)
    assert again["suggestions"] == [] and again["rejected"] == ["depot"]


def test_terms_come_from_the_corpus_when_none_are_given(project):
    corpus = project.layout.corpus
    os.makedirs(corpus, exist_ok=True)
    with open(os.path.join(corpus, "memo.md"), "w", encoding="utf-8") as f:
        f.write("# Memo\n\nThe Stamp Shop runs two shifts. The Stamp Shop moved in May. Press 01 is in the Stamp Shop.\n")
    result = _lexicon.suggest(project, embed=fake_embed, min_similarity=0.5)
    assert [s["term"] for s in result["suggestions"]] == ["Stamp Shop"]
    assert result["suggestions"][0]["target"] == "m.press" and result["suggestions"][0]["seen_in"] == ["memo"]


def test_a_vocabulary_term_or_a_document_title_is_not_an_entity_alias(project):
    corpus = project.layout.corpus
    os.makedirs(corpus, exist_ok=True)
    with open(os.path.join(corpus, "stamping-handbook.md"), "w", encoding="utf-8") as f:
        f.write("# Stamping Handbook\n\nA press is a Machine in a Site. The Stamping Handbook covers the press.\n"
                "We list every Machine and every Site.\n")
    result = _lexicon.suggest(project, embed=fake_embed, min_similarity=0.5)
    assert result["suggestions"] == [] and result["unclear"] == []
    assert set(result["vocabulary"]) == {"Machine", "Site"} and result["documents"] == ["Stamping Handbook"]


def test_the_command_lists_accepts_and_the_build_carries_the_entry(project, capsys):
    from oto.builder import build
    from oto.serve.store import SqliteStore
    root = project.data
    _lexicon.suggest(project, terms=["stamper"], embed=fake_embed, min_similarity=0.5)
    assert main(["lexicon", "list", "--project", root]) == 0
    assert "stamper" in capsys.readouterr().out
    assert main(["lexicon", "accept", "--project", root, "--term", "stamper"]) == 1, "no person, no entry"
    assert main(["lexicon", "accept", "--project", root, "--term", "stamper", "--by", "Sam Lee"]) == 0
    build(project)
    store = SqliteStore(project.layout.database)
    try:
        assert [r["target"] for r in store.lexicon("stamper")] == ["m.press"]
    finally:
        store.close()
