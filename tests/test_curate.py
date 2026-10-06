"""Curation: nothing reaches the live graph without passing the gates."""
import json
import os
import tempfile

import pytest

from oto.curate import diff, session
from oto.project import Project
from oto.scaffold import init

STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "d",
         "status": "current", "sources": ["d"]}
VOCAB = {"classes": {"Claim": {"definition": "a claim"}, "Party": {"definition": "a party"}},
         "properties": {"filed_by": {"domain": "Claim", "range": "Party", "inverse": "filed", "definition": "who filed it"}}}


def _node(nid, kind="Claim", **over):
    base = dict(id=nid, type=kind, label=nid, aliases=[], summary="a summary",
                attributes={}, tags=[], **STAMP)
    base.update(over)
    return base


def _graph(nodes=None, edges=None):
    return {"nodes": nodes or [_node("c.1"), _node("p.1", "Party")],
            "edges": edges or [{"from": "c.1", "rel": "filed_by", "to": "p.1"}]}


def _project(root):
    init(root, slug="kb", name="KB")
    project = Project.standard(root)
    with open(project.ontology_config_path, "w", encoding="utf-8") as f:
        json.dump(VOCAB, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(_graph(), f)
    return project


# ---- the safety model ----

def test_starting_a_candidate_leaves_the_live_graph_alone():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        before = open(project.graph_path, encoding="utf-8").read()
        session.start(project)
        assert session.exists(project)
        assert open(project.graph_path, encoding="utf-8").read() == before


def test_starting_twice_refuses_rather_than_discarding_work():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        session.start(project)
        with pytest.raises(FileExistsError):
            session.start(project)
        session.start(project, force=True)      # explicit is fine


def test_apply_keeps_the_previous_graph_so_it_can_be_undone():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        session.start(project)
        candidate = session.candidate(project)
        candidate["nodes"].append(_node("c.2"))
        with open(session.candidate_path(project), "w", encoding="utf-8") as f:
            json.dump(candidate, f)

        session.apply(project)
        assert len(session.live(project)["nodes"]) == 3
        assert not session.exists(project), "the candidate should be consumed"

        session.undo(project)
        assert len(session.live(project)["nodes"]) == 2


def test_undo_with_nothing_to_undo_returns_none():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        assert session.undo(project) is None


# ---- what the check catches ----

def test_an_overwrite_with_no_supersession_is_reported():
    """The single most important check: overwriting destroys what was true before."""
    live = _graph()
    candidate = _graph()
    candidate["nodes"][0]["summary"] = "something entirely different"
    findings = diff.check(live, candidate, VOCAB)
    contradictions = [f for f in findings if f.severity == diff.Finding.CONTRADICTION]
    assert len(contradictions) == 1
    assert "supersession" in contradictions[0].detail


def test_a_proper_supersession_is_not_reported_as_a_contradiction():
    live = _graph()
    candidate = _graph()
    candidate["nodes"][0].update(status="superseded", valid_to="2026-02-01",
                                 superseded_by="c.1.v2", summary="the old wording")
    candidate["nodes"].append(_node("c.1.v2", summary="the new wording", supersedes="c.1"))
    findings = diff.check(live, candidate, VOCAB)
    assert not [f for f in findings if f.severity == diff.Finding.CONTRADICTION]


def test_an_undeclared_type_blocks():
    candidate = _graph(nodes=[_node("c.1"), _node("x.1", "NotDeclared")])
    findings = diff.check(_graph(), candidate, VOCAB)
    assert any("not declared" in f.detail for f in diff.blocking(findings))


def test_an_edge_pointing_nowhere_blocks():
    candidate = _graph(edges=[{"from": "c.1", "rel": "filed_by", "to": "missing"}])
    assert any("unknown node" in f.detail for f in diff.blocking(diff.check(_graph(), candidate, VOCAB)))


def test_a_duplicate_id_blocks():
    candidate = _graph(nodes=[_node("c.1"), _node("c.1"), _node("p.1", "Party")])
    assert any("duplicate" in f.detail for f in diff.blocking(diff.check(_graph(), candidate, VOCAB)))


def test_a_bad_date_blocks():
    candidate = _graph(nodes=[_node("c.1", as_of="March 2026"), _node("p.1", "Party")])
    assert any("YYYY-MM-DD" in f.detail for f in diff.blocking(diff.check(_graph(), candidate, VOCAB)))


def test_supersedes_pointing_at_nothing_blocks():
    candidate = _graph(nodes=[_node("c.1", supersedes="no.such.node"), _node("p.1", "Party")])
    assert any("unknown id" in f.detail for f in diff.blocking(diff.check(_graph(), candidate, VOCAB)))


def test_a_new_node_with_no_source_is_a_gap_not_a_block():
    """A build must not fail on this, but a fact that cites nothing is not knowledge."""
    node = _node("c.2")
    node.pop("sources")
    node.pop("source_doc")
    findings = diff.check(_graph(), _graph(nodes=_graph()["nodes"] + [node]), VOCAB)
    gaps = [f for f in findings if f.severity == diff.Finding.GAP and f.subject == "c.2"]
    assert gaps
    assert not diff.blocking(findings)


def test_gaps_are_only_reported_for_what_the_change_introduces():
    """Re-reporting the existing graph's gaps would bury the ones that matter."""
    incomplete = _node("c.1")
    incomplete.pop("sources")
    live = _graph(nodes=[incomplete, _node("p.1", "Party")])
    findings = diff.check(live, live, VOCAB)
    assert not [f for f in findings if f.severity == diff.Finding.GAP]


def test_a_clean_change_produces_no_findings():
    """A clean new fact is dated, sourced, and says where in the document it comes from."""
    candidate = _graph(nodes=_graph()["nodes"] + [_node("c.2", evidence=[{"doc": "d", "where": "p.1"}])])
    assert diff.check(_graph(), candidate, VOCAB) == []


# ---- the summary and the privacy surface ----

def test_the_summary_counts_what_would_change():
    candidate = _graph(nodes=_graph()["nodes"] + [_node("c.2")],
                       edges=[{"from": "c.2", "rel": "filed_by", "to": "p.1"}])
    summary = diff.summarize(_graph(), candidate)
    assert summary["nodes_added"] == ["c.2"]
    assert len(summary["edges_added"]) == 1
    assert len(summary["edges_removed"]) == 1


def test_only_newly_introduced_text_is_scanned_for_personal_data():
    """Scanning the whole graph every time would bury what this change is about to add."""
    live = _graph(nodes=[_node("c.1", summary="SIN on file: 046 454 286"), _node("p.1", "Party")])
    candidate = _graph(nodes=[_node("c.1", summary="SIN on file: 046 454 286"),
                              _node("p.1", "Party"), _node("c.2", summary="a new and clean summary")])
    text = diff.authored_text(candidate, live)
    assert "046 454 286" not in text, "existing text must not be re-reported"
    assert "a new and clean summary" in text


def test_changed_text_is_scanned():
    live = _graph()
    candidate = _graph()
    candidate["nodes"][0]["summary"] = "Contact 416-555-0132"
    assert "416-555-0132" in diff.authored_text(candidate, live)


def test_the_curate_skill_states_the_rule():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "curate", "SKILL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "Never overwrite" in text
    assert "Never edit the live graph" in text


# ---- knowledge that came from a person ----

def _with_assertions(root):
    from oto.curate import assertions
    project = _project(root)
    entry = assertions.record(project, text="The owner changed in March.",
                              by="R. Handler, claims lead", at="2026-03-01")
    return project, entry


def test_an_assertion_needs_an_author_and_a_date():
    """An unattributed claim cannot be followed up, and a guessed date makes the graph lie."""
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with pytest.raises(ValueError):
            assertions.record(project, text="something", by="", at="2026-03-01")
        with pytest.raises(ValueError):
            assertions.record(project, text="something", by="someone", at="")
        with pytest.raises(ValueError):
            assertions.record(project, text="  ", by="someone", at="2026-03-01")


def test_the_assertion_log_is_append_only_and_ids_increment():
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project, first = _with_assertions(root)
        second = assertions.record(project, text="And the deductible too.",
                                   by="R. Handler", at="2026-04-01")
        assert first["id"] == "a-0001" and second["id"] == "a-0002"
        entries = assertions.read(project)
        assert [e["id"] for e in entries] == ["a-0001", "a-0002"]
        assert entries[0]["text"] == "The owner changed in March."


def test_citing_an_assertion_that_does_not_exist_blocks():
    """Without this check the identifier is decoration, and a fake citation looks checkable."""
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project, _entry = _with_assertions(root)
        node = _node("c.2", source_type="human_assertion", sources=["assertion:a-9999"])
        candidate = _graph(nodes=_graph()["nodes"] + [node])
        findings = diff.check(_graph(), candidate, VOCAB,
                              known_assertions=assertions.known_ids(project))
        assert any("not in the log" in f.detail for f in diff.blocking(findings))


def test_citing_a_real_assertion_passes():
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project, entry = _with_assertions(root)
        node = _node("c.2", source_type="human_assertion",
                     sources=[assertions.reference(entry["id"])])
        node.pop("source_doc")
        candidate = _graph(nodes=_graph()["nodes"] + [node])
        findings = diff.check(_graph(), candidate, VOCAB,
                              known_assertions=assertions.known_ids(project))
        assert diff.blocking(findings) == []


def test_an_asserted_fact_is_not_asked_for_a_source_document():
    """It has a different kind of source. Demanding a document would push people to invent one."""
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project, entry = _with_assertions(root)
        node = _node("c.2", source_type="human_assertion",
                     sources=[assertions.reference(entry["id"])])
        node.pop("source_doc")
        findings = diff.check(_graph(), _graph(nodes=_graph()["nodes"] + [node]), VOCAB,
                              known_assertions=assertions.known_ids(project))
        gaps = [f.detail for f in findings if f.severity == diff.Finding.GAP and f.subject == "c.2"]
        assert not any("source_doc" in g for g in gaps)


def test_claiming_to_be_an_assertion_without_citing_one_blocks():
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project, _entry = _with_assertions(root)
        node = _node("c.2", source_type="human_assertion", sources=[])
        findings = diff.check(_graph(), _graph(nodes=_graph()["nodes"] + [node]), VOCAB,
                              known_assertions=assertions.known_ids(project))
        assert any("cites no assertion" in f.detail for f in diff.blocking(findings))


def test_an_unknown_source_type_blocks():
    from oto.curate import assertions

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        node = _node("c.2", source_type="rumour")
        findings = diff.check(_graph(), _graph(nodes=_graph()["nodes"] + [node]), VOCAB,
                              known_assertions=assertions.known_ids(project))
        assert any("source_type" in f.detail for f in diff.blocking(findings))


def test_provenance_is_counted_not_estimated():
    from oto.curate import assertions

    counts = assertions.summarize([
        _node("a"),                                             # no source_type: a document
        _node("b", source_type="document"),
        _node("c", source_type="human_assertion"),
        _node("d", source_type="inference"),
    ])
    assert counts == {"document": 2, "human_assertion": 1, "inference": 1, "unrecorded": 0}


def test_the_skill_covers_the_correction_path():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "curate", "SKILL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "Correcting from something a person said" in text
    assert "--by` is required" in text
    assert "never defaulted" in text


# ---- the ledger ----

def test_apply_appends_a_ledger_entry_with_the_retirements(capsys):
    from oto.cli import main
    from oto.curate import ledger

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        session.start(project)
        candidate = session.candidate(project)
        old = [n for n in candidate["nodes"] if n["id"] == "c.1"][0]
        old.update(status="superseded", valid_to="2026-06-01", superseded_by="c.2")
        candidate["nodes"].append(_node("c.2", supersedes="c.1", valid_from="2026-06-01",
                                        change_note="renumbered after the merger", sources=["memo"],
                                        source_doc="memo"))
        with open(session.candidate_path(project), "w", encoding="utf-8") as f:
            json.dump(candidate, f)
        capsys.readouterr()
        assert main(["curate", "apply", "--project", root, "--by", "A. Curator",
                     "--note", "Claim numbers now answerable; ownership still open."]) == 0
        entries = ledger.read(project)
        assert len(entries) == 1
        record = entries[0]
        assert record["by"] == "A. Curator" and "still open" in record["note"]
        assert record["nodes"]["added"] == 1 and record["nodes"]["changed"] == 0, "a retirement is not a factual change"
        assert record["retired"] == [{"id": "c.1", "superseded_by": "c.2", "valid_to": "2026-06-01",
                                      "change_note": "renumbered after the merger"}]
        assert record["sources"] == ["memo"]
        assert main(["curate", "log", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "retired c.1 -> c.2: renumbered after the merger" in out and "A. Curator" in out


def test_the_ledger_is_append_only_across_applies():
    from oto.curate import ledger

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        for n in range(2):
            session.start(project)
            candidate = session.candidate(project)
            candidate["nodes"].append(_node("c.%d" % (10 + n)))
            with open(session.candidate_path(project), "w", encoding="utf-8") as f:
                json.dump(candidate, f)
            summary = diff.summarize(session.live(project), candidate)
            record = ledger.entry(summary, ledger.retirements(session.live(project), candidate))
            session.apply(project)
            ledger.append(project, record)
        assert [e["nodes"]["added"] for e in ledger.read(project)] == [1, 1]
