"""The four additions that make an answer checkable: evidence locators, re-attestation after a
new document version, supersession chains that point both ways, and resolve against the candidate."""
import json
import os
import tempfile

import pytest

from oto.cli import main
from oto.curate import batch, diff, reattest, session
from oto.intake import pipeline
from oto.project import Project
from oto.scaffold import init

TODAY = "2026-09-12"
VOCAB = {"classes": {"Role": "a role", "Procedure": "a procedure"},
         "properties": {"performs": ["Role", "Procedure", None, "does it"]}, "temporal": {}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook",
         "status": "current", "sources": ["handbook"]}


def _node(nid, kind="Role", **over):
    base = dict(id=nid, type=kind, label=nid, aliases=[], summary="s", attributes={}, tags=[], **STAMP)
    base.update(over)
    return base


def _project(root, nodes=None, edges=None):
    init(root, name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(VOCAB, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes if nodes is not None else [_node("role.adjuster", label="Claims adjuster")],
                   "edges": edges or []}, f)
    return Project.standard(root)


# ---- A. evidence ----

def test_evidence_is_kept_on_merge_and_accumulates():
    live = {"nodes": [_node("role.adjuster", evidence=[{"doc": "handbook", "where": "p.3", "quote": "reviews FNOL"}])],
            "edges": []}
    graph, report = batch.merge(live, {"source_doc": "memo", "nodes": [
        {"id": "role.adjuster", "evidence": [{"doc": "memo", "where": "§2"}]},
        {"id": "procedure.fnol", "type": "Procedure", "label": "FNOL",
         "evidence": [{"doc": "memo", "where": "§1", "quote": "first notice of loss"}]}]}, TODAY)
    adjuster = [n for n in graph["nodes"] if n["id"] == "role.adjuster"][0]
    assert adjuster["evidence"] == [{"doc": "handbook", "where": "p.3", "quote": "reviews FNOL"},
                                    {"doc": "memo", "where": "§2"}]
    assert [n for n in graph["nodes"] if n["id"] == "procedure.fnol"][0]["evidence"][0]["where"] == "§1"


def test_check_reports_a_new_fact_without_evidence_as_a_gap():
    live = {"nodes": [_node("role.adjuster")], "edges": []}
    candidate = {"nodes": [_node("role.adjuster"), _node("role.manager")], "edges": []}
    findings = diff.check(live, candidate, VOCAB)
    gaps = [f for f in findings if f.severity == diff.Finding.GAP and f.subject == "role.manager"]
    assert any("no evidence" in f.detail for f in gaps)
    candidate["nodes"][1]["evidence"] = [{"doc": "handbook", "where": "p.4"}]
    findings = diff.check(live, candidate, VOCAB)
    assert not any("no evidence" in f.detail for f in findings)
    assert not any(f.subject == "role.adjuster" for f in findings), "only what the change introduces"


def test_evidence_reaches_the_entity_page_and_the_answer(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, nodes=[_node("role.adjuster", label="Claims adjuster",
                                              evidence=[{"doc": "handbook", "where": "p.3",
                                                         "quote": "reviews each FNOL within two days"}])])
        assert main(["build", "--project", root]) == 0
        page = open(os.path.join(project.layout.entities, "role__adjuster.md"), encoding="utf-8").read()
        assert "## Evidence" in page and "handbook p.3" in page
        capsys.readouterr()
        assert main(["query", "--project", root, "entity", "Claims adjuster"]) == 0
        out = capsys.readouterr().out
        assert "Evidence:" in out and 'handbook p.3: "reviews each FNOL within two days"' in out


# ---- B. re-attestation ----

def _ingest_and_build(project, name, text):
    with open(os.path.join(project.layout.inbox, name), "w", encoding="utf-8") as f:
        f.write(text)
    run_id = pipeline.ingest(project)["run_id"]
    assert main(["build", "--project", os.path.dirname(project.src)]) == 0
    return run_id


def test_a_new_document_version_makes_its_facts_pending_until_re_attested():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _ingest_and_build(project, "handbook.md", "# Handbook\n\nVersion one.\n")
        pipeline.complete(project)
        assert reattest.pending(project, session.live(project)) == []

        run_id = _ingest_and_build(project, "handbook.md", "# Handbook\n\nVersion two.\n")
        pending = reattest.pending(project, session.live(project))
        assert [p["id"] for p in pending] == ["role.adjuster"] and pending[0]["run_id"] == run_id
        with pytest.raises(pipeline.NotReady, match="re-attested"):
            pipeline.complete(project)

        # Listing the fact again from the new version re-attests it: as_of moves to the run's date.
        session.start(project)
        import datetime
        graph, _report = batch.merge(session.candidate(project),
                                     {"source_doc": "handbook", "nodes": [{"id": "role.adjuster"}]},
                                     datetime.date.today().isoformat())   # re-attested on the run's day
        session._write(session.candidate_path(project), graph)
        assert not reattest.pending(project, graph)
        session.apply(project)
        assert main(["build", "--project", root]) == 0
        pipeline.complete(project)


def test_check_and_status_surface_pending_reattestation(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        _ingest_and_build(project, "handbook.md", "# H\n\nOne.\n")
        pipeline.complete(project)
        _ingest_and_build(project, "handbook.md", "# H\n\nTwo.\n")
        capsys.readouterr()
        assert main(["status", "--project", root]) == 0
        assert "re-attest   1 fact(s)" in capsys.readouterr().out
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "check", "--project", root]) == 0
        assert "re-attest it, or retire it" in capsys.readouterr().out


# ---- C. chain consistency and conformance ----

def test_a_one_way_supersession_chain_is_blocking():
    live = {"nodes": [_node("role.adjuster")], "edges": []}
    old = _node("role.adjuster", status="superseded", valid_to="2026-06-01", superseded_by="role.handler")
    new = _node("role.handler", valid_from="2026-06-01")            # forgot `supersedes`
    findings = diff.check(live, {"nodes": [old, new], "edges": []}, VOCAB)
    assert any(f.severity == diff.Finding.BLOCKING and "point both ways" in f.detail for f in findings)
    new["supersedes"] = "role.adjuster"
    findings = diff.check(live, {"nodes": [old, new], "edges": []}, VOCAB)
    assert not any("point both ways" in f.detail for f in findings)


def test_a_supersedes_pointing_at_a_still_current_node_is_blocking():
    live = {"nodes": [_node("role.adjuster")], "edges": []}
    candidate = {"nodes": [_node("role.adjuster"), _node("role.handler", supersedes="role.adjuster")], "edges": []}
    findings = diff.check(live, candidate, VOCAB)
    assert any("still 'current': retire it" in f.detail for f in findings)


def test_a_date_handoff_mismatch_is_a_gap():
    live = {"nodes": [_node("role.adjuster")], "edges": []}
    old = _node("role.adjuster", status="superseded", valid_to="2026-06-01", superseded_by="role.handler")
    new = _node("role.handler", supersedes="role.adjuster", valid_from="2026-07-01")
    findings = diff.check(live, {"nodes": [old, new], "edges": []}, VOCAB)
    assert any(f.severity == diff.Finding.GAP and "hand over" in f.detail for f in findings)


def test_a_domain_violation_in_the_candidate_is_reported():
    live = {"nodes": [], "edges": []}
    candidate = {"nodes": [_node("procedure.fnol", "Procedure"), _node("procedure.intake", "Procedure")],
                 "edges": [{"from": "procedure.fnol", "rel": "performs", "to": "procedure.intake"}]}
    findings = diff.check(live, candidate, VOCAB)
    hit = [f for f in findings if f.subject == "performs"]
    assert hit and "domain is Procedure" in hit[0].detail and "declared Role" in hit[0].detail
    assert hit[0].severity == diff.Finding.GAP, "advisory, like oto ontology check"


# ---- D. resolve against the candidate ----

def test_resolve_finds_ids_that_only_the_candidate_holds(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        assert main(["curate", "start", "--project", root]) == 0
        graph, _ = batch.merge(session.candidate(project), {"source_doc": "memo", "nodes": [
            {"id": "procedure.fnol", "type": "Procedure", "label": "First notice of loss", "aliases": ["FNOL"]}]}, TODAY)
        session._write(session.candidate_path(project), graph)
        capsys.readouterr()
        assert main(["curate", "resolve", "--project", root, "--term", "fnol"]) == 0
        out = capsys.readouterr().out
        assert "procedure.fnol" in out and "candidate only" in out
        assert main(["curate", "resolve", "--project", root, "--term", "adjuster"]) == 0
        out = capsys.readouterr().out
        assert "role.adjuster" in out and "candidate only" not in out
        assert main(["curate", "resolve", "--project", root, "--term", "nothing here"]) == 0
        assert "new id is warranted" in capsys.readouterr().out
