"""Batch merge into the candidate: additive by rule, refused on a changed fact."""
import json
import os
import tempfile

from oto.cli import main
from oto.curate import batch, session
from oto.project import Project
from oto.scaffold import init

TODAY = "2026-09-12"
VOCAB = {"classes": {"Role": "a role", "Procedure": "a procedure"},
         "properties": {"performs": ["Role", "Procedure", None, "does it"]}}


def _candidate():
    return {"nodes": [{"id": "role.adjuster", "type": "Role", "label": "Claims adjuster",
                       "aliases": ["adjuster"], "summary": "Settles claims.", "attributes": {},
                       "tags": [], "status": "current", "as_of": "2026-01-01",
                       "valid_from": "2026-01-01", "source_doc": "handbook", "sources": ["handbook"]}],
            "edges": []}


def test_a_new_node_is_added_with_defaults_filled():
    graph, report = batch.merge(_candidate(), {"source_doc": "memo", "nodes": [
        {"id": "procedure.fnol", "type": "Procedure", "label": "First notice of loss"}]}, TODAY)
    assert report["added"] == ["procedure.fnol"]
    node = [n for n in graph["nodes"] if n["id"] == "procedure.fnol"][0]
    assert node["status"] == "current"
    assert node["as_of"] == TODAY and node["valid_from"] == TODAY
    assert node["source_doc"] == "memo" and node["sources"] == ["memo"]
    assert node["aliases"] == [] and node["attributes"] == {}


def test_the_same_fact_from_a_second_document_gains_a_source_not_a_duplicate():
    graph, report = batch.merge(_candidate(), {"source_doc": "memo", "nodes": [
        {"id": "role.adjuster", "type": "Role", "label": "Claims adjuster", "aliases": ["the adjuster"]}]}, TODAY)
    assert report["added"] == [] and report["merged"] == [("role.adjuster", 1, 1)]
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["sources"] == ["handbook", "memo"]
    assert "the adjuster" in graph["nodes"][0]["aliases"]


def test_a_changed_fact_is_a_conflict_and_the_batch_is_refused():
    _graph, report = batch.merge(_candidate(), {"nodes": [
        {"id": "role.adjuster", "type": "Role", "label": "Senior adjuster"}]}, TODAY)
    assert report["conflicts"] == [("role.adjuster", ["label"])]
    assert batch.refused(report)


def test_a_retirement_updates_only_temporal_fields():
    """The old half of a supersession: status, valid_to, superseded_by, and nothing factual."""
    graph, report = batch.merge(_candidate(), {"source_doc": "memo", "nodes": [
        {"id": "role.adjuster", "status": "superseded", "valid_to": "2026-06-01",
         "superseded_by": "role.adjuster.2", "change_note": "title changed"},
        {"id": "role.adjuster.2", "type": "Role", "label": "Claims handler",
         "supersedes": "role.adjuster", "valid_from": "2026-06-01"}]}, TODAY)
    old = [n for n in graph["nodes"] if n["id"] == "role.adjuster"][0]
    assert old["status"] == "superseded" and old["superseded_by"] == "role.adjuster.2"
    assert old["label"] == "Claims adjuster"
    assert report["updated"] == [("role.adjuster", ["valid_to", "status", "superseded_by", "change_note"])] \
        or set(report["updated"][0][1]) == {"valid_to", "status", "superseded_by", "change_note"}
    assert report["added"] == ["role.adjuster.2"]
    assert not batch.refused(report)


def test_a_new_id_with_an_existing_name_is_a_suspect():
    _graph, report = batch.merge(_candidate(), {"nodes": [
        {"id": "role.claims-adjuster", "type": "Role", "label": "Adjuster"}]}, TODAY)
    assert report["suspects"] == [("role.claims-adjuster", ["role.adjuster"])]
    assert not batch.refused(report)


def test_edges_are_added_once_and_dangling_ones_are_reported():
    proposal = {"nodes": [{"id": "procedure.fnol", "type": "Procedure", "label": "FNOL"}],
                "edges": [{"from": "role.adjuster", "rel": "performs", "to": "procedure.fnol"},
                          {"from": "role.adjuster", "rel": "performs", "to": "procedure.fnol"},
                          {"from": "role.adjuster", "rel": "performs", "to": "procedure.later"}]}
    graph, report = batch.merge(_candidate(), proposal, TODAY)
    assert report["edges_added"] == 2 and report["edges_existing"] == 1
    assert report["edges_dangling"] == ["role.adjuster -performs-> procedure.later"]
    assert len(graph["edges"]) == 2


def test_a_node_without_a_type_or_label_is_a_problem():
    _graph, report = batch.merge(_candidate(), {"nodes": [{"id": "x"}]}, TODAY)
    assert report["problems"] and batch.refused(report)


def test_the_input_graph_is_not_modified():
    before = _candidate()
    snapshot = json.dumps(before, sort_keys=True)
    batch.merge(before, {"nodes": [{"id": "role.adjuster", "aliases": ["a"], "status": "proposed"}]}, TODAY)
    assert json.dumps(before, sort_keys=True) == snapshot


# ---- through the command line ----

def _project(root):
    init(root, slug="kb", name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(VOCAB, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(_candidate(), f)
    return Project.standard(root)


def test_add_needs_a_candidate_and_writes_only_the_candidate(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        proposal = os.path.join(root, "p.json")
        with open(proposal, "w", encoding="utf-8") as f:
            json.dump({"source_doc": "memo", "nodes": [
                {"id": "procedure.fnol", "type": "Procedure", "label": "First notice of loss"}],
                "edges": [{"from": "role.adjuster", "rel": "performs", "to": "procedure.fnol"}]}, f)
        assert main(["curate", "add", "--project", root, "--from", proposal]) == 1
        assert "no candidate" in capsys.readouterr().err
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "add", "--project", root, "--from", proposal]) == 0
        assert "+1 node(s)" in capsys.readouterr().out
        assert len(session.candidate(project)["nodes"]) == 2
        assert len(session.live(project)["nodes"]) == 1, "the live graph must not change"
        assert main(["curate", "check", "--project", root]) == 0


def test_a_refused_batch_leaves_the_candidate_untouched(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        main(["curate", "start", "--project", root])
        before = open(session.candidate_path(project), encoding="utf-8").read()
        proposal = os.path.join(root, "p.json")
        with open(proposal, "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "role.adjuster", "type": "Role", "label": "Renamed"}]}, f)
        assert main(["curate", "add", "--project", root, "--from", proposal]) == 1
        assert "supersession" in capsys.readouterr().out
        assert open(session.candidate_path(project), encoding="utf-8").read() == before


def test_dry_run_reports_without_writing(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        proposal = os.path.join(root, "p.json")
        with open(proposal, "w", encoding="utf-8") as f:
            json.dump({"source_doc": "memo", "nodes": [
                {"id": "procedure.fnol", "type": "Procedure", "label": "First notice of loss"}]}, f)
        assert main(["curate", "start", "--project", root]) == 0
        before = open(session.candidate_path(project), encoding="utf-8").read()
        capsys.readouterr()
        assert main(["curate", "add", "--project", root, "--from", proposal, "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "would add 1 node(s)" in out and "candidate is unchanged" in out
        assert open(session.candidate_path(project), encoding="utf-8").read() == before
        # A refusal is reported the same way, and still writes nothing.
        with open(proposal, "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "role.adjuster", "type": "Role", "label": "Renamed"}]}, f)
        assert main(["curate", "add", "--project", root, "--from", proposal, "--dry-run"]) == 1
        assert "would refuse" in capsys.readouterr().out
