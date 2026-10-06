"""Serving: the value loop works end to end, and the transaction protects a failed build."""
import json
import os
import subprocess
import sys
import tempfile

import pytest

from oto.builder import build, generated_paths
from oto.project import Project
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ONTOLOGY = {
    "classes": {"Machine": {"definition": "A machine."}, "Site": {"definition": "A place where machines run."}},
    "properties": {"installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts", "definition": "Where a machine runs."}},
    "temporal": {},
}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "handbook",
         "status": "current", "sources": ["handbook"]}
GRAPH = {
    "nodes": [
        dict(id="m.1", type="Machine", label="Press 01", aliases=["Press One"],
             summary="A stamping press.", attributes={}, tags=["machine"], **STAMP),
        dict(id="s.1", type="Site", label="North Plant", aliases=[], summary="The north plant.",
             attributes={}, tags=["site"], **STAMP),
    ],
    "edges": [{"from": "m.1", "rel": "installed_at", "to": "s.1"}],
}


def _built_project(root):
    init(root, slug="kb", name="Test KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(ONTOLOGY, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(GRAPH, f)
    project = Project.standard(root)
    build(project)
    return project


def _query(root, *args):
    r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root] + list(args),
                       cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                       capture_output=True, text=True)
    return r.stdout


def test_query_resolves_an_alias():
    """A question rarely uses the canonical label. Alias resolution is the difference."""
    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        out = _query(root, "entity", "Press One")
        assert "Press 01" in out
        assert "[Machine — " in out, "the class is read with its definition"


def test_answers_carry_provenance_and_a_date():
    """An answer without a source or a date cannot be checked, which is the whole point."""
    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        out = _query(root, "entity", "Press 01")
        assert "status=current" in out
        assert "as_of=2026-01-01" in out
        assert "handbook" in out


def test_neighbors_traverses_a_declared_relation():
    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        assert "North Plant" in _query(root, "neighbors", "Press 01")


def test_server_exposes_its_tools_over_json_rpc():
    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        payload = "\n".join([
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"2024-11-05","capabilities":{}}}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        ]) + "\n"
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root],
                           input=payload, cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                           capture_output=True, text=True)
        tools = None
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            result = json.loads(line).get("result", {})
            if "tools" in result:
                tools = result["tools"]
        assert tools, "the server listed no tools"
        names = {t["name"] for t in tools}
        assert {"kg_entity", "kg_neighbors", "kg_search", "kg_resolve"} <= names


def test_server_identity_comes_from_the_project_slug():
    """Two projects on one machine must not collide on a server name."""
    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        payload = ('{"jsonrpc":"2.0","id":1,"method":"initialize",'
                   '"params":{"protocolVersion":"2024-11-05","capabilities":{}}}\n')
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root],
                           input=payload, cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO),
                           capture_output=True, text=True)
        info = json.loads(r.stdout.splitlines()[0])["result"]["serverInfo"]
        assert info["name"] == "kb-kg"


def test_a_failed_build_restores_the_previous_one():
    """The stages write as they go, so a late failure must not corrupt a good build."""
    import oto.builder as builder

    with tempfile.TemporaryDirectory() as root:
        project = _built_project(root)
        database = project.layout.database
        with open(database, "rb") as f:
            before = f.read()
        files_before = sum(len(files) for _, _, files in os.walk(os.path.join(root, "build")))

        original = builder.STAGES
        builder.STAGES = tuple(list(original[:-1]) + [("sqlite", "oto.does.not.exist")])
        try:
            with pytest.raises(ImportError):
                build(project)
        finally:
            builder.STAGES = original

        with open(database, "rb") as f:
            assert f.read() == before, "the database was corrupted by a failed build"
        files_after = sum(len(files) for _, _, files in os.walk(os.path.join(root, "build")))
        assert files_after == files_before
        assert not os.path.exists(os.path.join(root, "build", ".oto-previous"))


def test_generated_paths_excludes_the_corpus():
    """documents/ is an input to the compile stages. Stashing it would discard the corpus."""
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="Test KB")
        project = Project.standard(root)
        paths = generated_paths(project)
        assert project.layout.corpus not in paths
        assert project.layout.entities in paths
        assert project.layout.database in paths


# ---- the database schema version ----

def test_the_engine_refuses_a_database_from_the_future(tmp_path):
    """A version nothing checks protects nothing. This is the check that gives it meaning."""
    import sqlite3

    from oto.serve import engine
    from oto.targets import sqlite as target

    path = str(tmp_path / "future.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    con.execute("INSERT INTO meta VALUES ('schema_version', ?)",
                (str(engine.UNDERSTOOD_SCHEMA + 1),))
    con.commit()
    con.close()

    complaint = engine.schema_complaint(path)
    assert complaint is not None
    assert "will not" in complaint or "not" in complaint
    assert str(engine.UNDERSTOOD_SCHEMA) in complaint
    assert target.SCHEMA_VERSION <= engine.UNDERSTOOD_SCHEMA, (
        "the writer must never emit a version the engine cannot read")


def test_a_matching_or_older_database_is_accepted(tmp_path):
    """Refuse the future, tolerate the past. An older build still holds what the engine reads."""
    import sqlite3

    from oto.serve import engine

    for stamped in (None, 0, engine.UNDERSTOOD_SCHEMA):
        path = str(tmp_path / ("db-%s.db" % stamped))
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        if stamped is not None:
            con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(stamped),))
        con.commit()
        con.close()
        assert engine.schema_complaint(path) is None, "rejected schema_version=%r" % stamped


def test_the_refusal_message_does_not_tell_the_reader_to_rebuild(tmp_path, monkeypatch):
    """Rebuilding with a stale engine produces the same unreadable file. Wrong instruction."""
    from oto.serve import engine

    monkeypatch.setattr(engine, "DB_REFUSAL", "schema 99 vs 1")
    message = engine.no_data_message()
    assert "upgrade the engine" in message.lower()
    assert "will not help" in message.lower()

    monkeypatch.setattr(engine, "DB_REFUSAL", None)
    absent = engine.no_data_message()
    assert "oto build" in absent


# ---- the overview: the map for a global question ----

def test_overview_reports_counts_hubs_corpus_and_the_ledger(capsys):
    import json as _json

    from oto.cli import main
    from oto.curate import ledger as _ledger
    from oto.project import Project

    with tempfile.TemporaryDirectory() as root:
        _built_project(root)
        project = Project.standard(root)
        # A theme note under notes/themes/ is authored, and must reach the index.
        os.makedirs(os.path.join(project.layout.notes, "themes"), exist_ok=True)
        with open(os.path.join(project.layout.notes, "themes", "cadence.md"), "w", encoding="utf-8") as f:
            f.write("---\ntheme: cadence\nas_of: 2026-09-13\n---\n# Cadence\n\nA reading of the graph.\n")
        _ledger.append(project, _ledger.entry(
            {"nodes_added": ["m.1"], "nodes_removed": [], "nodes_changed": [], "edges_added": [], "edges_removed": []},
            [{"id": "old.1", "superseded_by": "m.1", "valid_to": "2026-01-01", "change_note": "renumbered"}],
            by="A. Curator", note="Presses now answerable.", sources=["handbook"]))
        assert main(["build", "--project", root]) == 0
        capsys.readouterr()
        out = _query(root, "overview")
        assert "=== Overview:" in out and "By class" in out and "Most connected" in out
        assert "Press" in out
        assert "notes/" in out, "the theme note must be counted in the corpus"
        assert "Recent changes (the ledger):" in out and "A. Curator" in out
        assert "retired old.1 -> m.1: renumbered" in out and "Presses now answerable." in out
        assert "map, not an answer" in out
        # The same tool over JSON-RPC.
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", root],
                           input='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kg_overview","arguments":{}}}\n',
                           capture_output=True, text=True, timeout=60)
        payload = _json.loads(r.stdout.strip().splitlines()[-1])
        assert payload["result"]["isError"] is False and "Overview" in payload["result"]["content"][0]["text"]


def test_the_query_skill_labels_a_synthesis_and_keeps_theme_notes():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill = open(os.path.join(root, "skills", "query-knowledge", "SKILL.md"), encoding="utf-8").read()
    for marker in ("kg_overview", "A reading of the graph as of", "Rests on", "notes/themes/", "Decline what a synthesis cannot ground"):
        assert marker in skill, marker


# ---- what a term means ----

WORDED = {
    "languages": ["en", "fr"],
    "classes": {"Machine": {"definition": {"en": "A machine.", "fr": "Une machine."}, "label": {"en": "machine", "fr": "machine"},
                            "alt_labels": {"en": ["press"], "fr": ["presse"]}, "scope_note": "Not the tooling it carries."},
                "Site": {"definition": "A place where machines run.", "label": {"fr": "site"}}},
    "properties": {"installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts",
                                    "definition": "Where a machine runs.", "label": {"en": "installed at", "fr": "installée à"},
                                    "inverse_label": {"en": "hosts", "fr": "héberge"}}},
    "attributes": {"Machine": {"serial": {"type": "string", "definition": "The maker's number.", "label": "serial number"}}},
    "temporal": {},
}
RATIONALE = {"classes": {"Machine": {"question": "What runs where?", "why": "Downtime questions name the machine, never the line it sits on.",
                                     "alternatives": "A line class; rejected, nobody asks about lines.", "validated_by": "R. Plant, 2026-05-01"}},
             "properties": {}}


def _worded_project(root):
    init(root, slug="kb", name="Test KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(WORDED, f)
    with open(os.path.join(root, "ontology.rationale.json"), "w", encoding="utf-8") as f:
        json.dump(RATIONALE, f)
    graph = json.loads(json.dumps(GRAPH))
    graph["nodes"][0].update(labels={"fr": "Presse 01"}, hidden_labels=["PRS-01"], attributes={"serial": "X-9"})
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f)
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "the big press", "aka": ["BP"], "targets": ["m.1"], "status": "current", "note": ""}]}, f)
    project = Project.standard(root)
    build(project)
    return project


def test_an_answer_reads_the_vocabulary_as_it_is_labelled():
    with tempfile.TemporaryDirectory() as root:
        _worded_project(root)
        card = _query(root, "entity", "Press 01")
        assert "[Machine — A machine.]" in card and "aka: Press One" in card
        assert "  - serial number: X-9" in card, "an attribute reads by its label"
        assert "  installed at → North Plant" in card
        site = _query(root, "entity", "North Plant")
        assert "  hosts → Press 01" in site, "an incoming edge reads from this side, by the inverse label"
        assert "Press 01" in _query(root, "entity", "Presse 01"), "a label in another language resolves"
        assert "Press 01" in _query(root, "entity", "PRS-01"), "a hidden label resolves"
        assert "PRS-01" not in _query(root, "entity", "Press 01"), "and is never shown"
        assert "Press 01" in _query(root, "neighbors", "North Plant", "héberge"), "a relation filter takes a label in any language"


def test_define_says_what_a_term_means_and_why_it_exists():
    with tempfile.TemporaryDirectory() as root:
        _worded_project(root)
        text = _query(root, "define", "presse")                # found by a French alternative label
        assert text.startswith("=== machine  [class Machine]  <https://kb.example/kg/ont/Machine> ===")
        assert 'labels: en "machine"; fr "machine"; also en "press"; also fr "presse"' in text
        assert "definition: A machine." in text and "scope: Not the tooling it carries." in text
        assert "in the graph: 1 node(s)" in text
        assert "why it exists: Downtime questions name the machine" in text and "the question it answers: What runs where?" in text
        assert "confirmed by: R. Plant, 2026-05-01" in text
        relation = _query(root, "define", "installed at")
        assert "from: Machine  →  to: Site" in relation and 'inverse: hosts ("hosts")' in relation and "in the graph: 1 edge(s)" in relation
        attribute = _query(root, "define", "serial number")
        assert "[attribute Machine.serial]" in attribute and "type: string  ·  declared on Machine" in attribute
        assert "not recorded" not in relation, "a relation's reasoning is optional"
        assert "No class, relation or attribute is called 'gizmo'" in _query(root, "define", "gizmo")


def test_a_question_about_a_class_covers_the_kinds_of_it():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="Test KB", ontology="software-architecture")
        build(Project.standard(root))
        listed = _query(root, "by-type", "Asset")
        assert listed.startswith("Asset (5; covers Component, DataStore, Interface, System):") and "[Component]" in listed
        assert "count = 5  (type=Asset (covers" in _query(root, "count", "--type", "Asset")
        assert "count = 2  (type=Component)" in _query(root, "count", "--type", "Component")
        card = _query(root, "entity", "Payment API")
        assert "a kind of Asset" in card
        defined = _query(root, "define", "Asset")
        assert "kinds of it: Component, DataStore, Interface, System" in defined and "in the graph: 0 node(s), 5 with the kinds of it" in defined
        assert "a kind of: Asset" in _query(root, "define", "component")


def test_a_controlled_value_is_read_by_its_concept():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="Test KB", ontology="auto-claims")
        build(Project.standard(root))
        card = _query(root, "entity", "C-5001")
        assert "  - state: Open — Reported and being handled: assessed, decided or paid." in card
        grouped = _query(root, "group", "state", "--type", "Task", "--level", "top")
        assert "values of TaskState rolled up to the top concepts" in grouped
        defined = _query(root, "define", "claim state")
        assert "[scheme ClaimState]" in defined and "  - reopened: Reopened — Opened again after closing" in defined and "(narrower than open)" in defined
        assert "values of: Claim.state" in defined
        concept = _query(root, "define", "Reopened")
        assert "[concept ClaimState.reopened]" in concept and "a concept of ClaimState, narrower than open" in concept

