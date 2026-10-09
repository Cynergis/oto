"""The two serving backends answer alike. The same project is built into SQLite and loaded into
Neo4j, the same queries run through the engine over each store, and the text must match to the
character. Passage search is the one exception: the two full-text engines tokenize and rank
differently (FTS5 splits `decision__single` into words, Lucene keeps it whole), so its result
sets must overlap substantially rather than match.

Runs only where a Neo4j is reachable (NEO4J_URI and NEO4J_PASSWORD, as in the CI job); the
SQLite half is covered without one in test_store.py.
"""
import json
import os
import re
import tempfile

import pytest

from oto.builder import build
from oto.cli import main
from oto.project import Project
from oto.scaffold import init
from oto.serve.store import SqliteStore, Neo4jStore

LIVE = os.environ.get("NEO4J_URI") and (os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_AUTH"))
pytestmark = pytest.mark.skipif(not LIVE, reason="no Neo4j reachable: set NEO4J_URI and NEO4J_PASSWORD")

PROJECT = "equiv"

#: (engine function, kwargs). Every tool the server exposes, in the shapes a reader uses them.
QUERIES = [
    ("entity_text", {"term": "system.payments"}),
    ("entity_text", {"term": "Payments"}),                       # by label
    ("entity_text", {"term": "datastore.ledger", "history": True}),
    ("entity_text", {"term": "system.payments", "as_of": "2026-01-01"}),
    ("entity_text", {"term": "nothing-like-this-xyz"}),
    ("neighbors_text", {"term": "system.payments"}),
    ("neighbors_text", {"term": "system.payments", "rel": "part_of"}),
    ("neighbors_text", {"term": "system.payments", "rel": "part of"}),   # a relation by its label
    ("define_text", {"term": "Component"}),
    ("define_text", {"term": "Asset"}),
    ("by_type_text", {"type_": "Asset"}),                       # a class covers the kinds of it
    ("count_text", {"type_": "Asset"}),
    ("group_by_text", {"by": "type", "type_": "Asset"}),
    ("group_by_text", {"by": "status", "level": "top"}),
    ("define_text", {"term": "part of"}),
    ("define_text", {"term": "nothing-like-this-xyz"}),
    ("explain_text", {"term": "system.payments"}),
    ("explain_text", {"term": "datastore.ledger"}),
    ("policy_text", {}),
    ("by_type_text", {"type_": "Component"}),
    ("by_type_text", {"type_": "Decision", "limit": 3}),
    ("by_type_text", {"type_": "Nope"}),
    ("count_text", {}),
    ("count_text", {"type_": "Component"}),
    ("count_text", {"type_": "Decision", "attr": "status", "value": "accepted"}),
    ("group_by_text", {"by": "type"}),
    ("pending_text", {}),                                        # the lane comes from the project, not the store
    ("actions_text", {}),                                        # the catalog comes from the Action nodes
    ("actions_text", {"on": "component.payment-api"}),
    ("actions_text", {"on": "team.payments"}),
    ("actions_text", {"action": "action.ping-component"}),
    ("actions_text", {"ready": True}),
    ("group_by_text", {"by": "status"}),
    ("group_by_text", {"by": "status", "type_": "Decision"}),
    ("stale_text", {}),
    ("overview_text", {"limit": 5}),
    ("resolve_text", {"term": "payments"}),
    ("resolve_text", {"term": "the payments system"}),
    ("resolve_text", {"term": "unknown jargon"}),
    ("docs_text", {}),
    ("docs_text", {"query": "zzz"}),
    ("questions_text", {}),                                      # the questions ride in the store
    ("ask_text", {"qid": "CQ1", "params": {"SYSTEM": "Payments platform"}}),
    ("ask_text", {"qid": "CQ2"}),
    ("ask_text", {"qid": "CQ9"}),
]
SEARCHES = ["payments ledger", "runbook", "risk"]


def _project(root):
    init(root, slug=PROJECT, name="Equivalence", ontology="software-architecture")
    project = Project.standard(root)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "payments", "aka": ["the payments system"], "targets": ["system.payments"],
                                "status": "current", "note": "the platform, not the team"}]}, f)
    os.makedirs(os.path.join(root, "actions"), exist_ok=True)
    with open(os.path.join(root, "actions", "action.ping-component.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "action.ping-component", "label": "Ping a component", "description": "Reads a component's health endpoint.",
                   "subject": "Component", "executed_by": "team.payments",
                   "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
                   "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                   "bind": {"name": "$label"}, "when": [{"node": "c", "type": "Component"}, {"edge": ["c", "runs_in", "e"]}],
                   "invoke": {"transport": "http", "method": "GET", "url": "https://health.example/{name}"},
                   "needs": [], "result": {"kind": "document"}}, f)
    with open(os.path.join(root, "ping.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "ok"}, f)
    assert main(["actions", "record", "action.ping-component", "--on", "component.payment-api", "--by", "Equivalence",
                 "--at", "2026-09-22", "--response", os.path.join(root, "ping.json"), "--project", root]) == 0
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)
    with open(os.path.join(root, "notes", "ledger.md"), "w", encoding="utf-8") as f:
        f.write("# The ledger\n\nThe payments ledger records every transfer; a risk to it reaches the system.\n")
    from oto.reason import questions as _questions
    _questions.save(project, {
        "CQ1": {"who": "on-call", "question": "Which components make up $SYSTEM?", "why": "incidents start from a system",
                "params": {"SYSTEM": {"type": "System"}},
                "ask": {"when": [{"edge": ["c", "part_of", "$SYSTEM"]}, {"node": "c", "type": "Asset"}], "select": ["c", "c.type"]},
                "gaps": {"when": [{"not_edge": ["*", "part_of", "$SYSTEM"]}], "say": "nothing is part of it"}},
        "CQ2": {"who": "architect", "question": "Which data stores have no decision behind them?", "why": "retirement",
                "ask": {"when": [{"node": "d", "type": "DataStore"}, {"not_edge": ["d", "decided_by", "*"]}], "select": ["d"]},
                "gate": "empty"}})
    cfg = json.load(open(project.config_path, encoding="utf-8"))
    cfg["targets"] = ["sqlite", "neo4j"]
    cfg["neo4j"] = {"uri": os.environ["NEO4J_URI"], "database": os.environ.get("NEO4J_DATABASE") or "neo4j", "batch": 3}
    cfg["serve"] = {"backend": "neo4j"}
    json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
    return project


def _answers(engine, store, root=None):
    engine.use(store)
    if root:
        engine.PROJECT_ROOT = root
    try:
        out = {}
        for name, kwargs in QUERIES:
            out[(name, json.dumps(kwargs, sort_keys=True))] = getattr(engine, name)(**kwargs)
        searches = {q: set(re.findall(r"\S+$", line)[0] for line in engine.search_text(q, 50).splitlines()[1:])
                    for q in SEARCHES}
        return out, searches
    finally:
        engine.use(None)


def test_every_tool_answers_the_same_from_sqlite_and_neo4j():
    from oto.serve import engine

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        project.options = {"verify": True}
        build(project)                                        # sqlite and neo4j, verified
        sqlite = SqliteStore(project.layout.database)
        neo = Neo4jStore.from_config(json.load(open(project.config_path, encoding="utf-8")), PROJECT)
        try:
            neo.ping()
            assert neo.loaded() and neo.meta("schema_version") == sqlite.meta("schema_version")
            assert neo.meta("build_seq") == sqlite.meta("build_seq")
            a, a_search = _answers(engine, sqlite, root)
            b, b_search = _answers(engine, neo, root)
            differences = [k for k in a if a[k] != b[k]]
            assert not differences, "\n\n".join(
                "%s %s\n--- sqlite ---\n%s\n--- neo4j ---\n%s" % (k[0], k[1], a[k], b[k]) for k in differences)
            # the whole graph as data: identical apart from the passages' order-free set
            from oto.serve import payload as _payload
            pa = _payload.build(sqlite, root, None, passages=True)
            pb = _payload.build(neo, root, None, passages=True)
            assert {p["path"] for p in pa.pop("passages")} == {p["path"] for p in pb.pop("passages")}
            pa["backend"] = pb["backend"] = None
            assert pa == pb, "the payload differs between the stores"
            for q in SEARCHES:
                both, either = a_search[q] & b_search[q], a_search[q] | b_search[q]
                assert either and len(both) / len(either) >= 0.6, \
                    "passage search for %r diverges: sqlite %r, neo4j %r" % (q, sorted(a_search[q]), sorted(b_search[q]))
            assert "notes/ledger.md" in a_search["risk"] and "notes/ledger.md" in b_search["risk"]
        finally:
            sqlite.close()
            neo.close()


def test_the_engine_serves_neo4j_when_the_project_says_so():
    """`oto query` with `serve.backend: neo4j` answers from Neo4j, and `--backend sqlite` overrides it."""
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        env = dict(os.environ, OTO_STORE="")
        env.pop("OTO_STORE")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def query(*args):
            r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root] + list(args),
                               cwd=repo, env=dict(env, PYTHONPATH=repo), capture_output=True, text=True)
            return r.returncode, r.stdout, r.stderr

        code, out, err = query("entity", "system.payments")
        assert code == 0 and "[System — " in out and "serving Neo4j" in err, err
        code, out, err = query("--backend", "sqlite", "entity", "system.payments")
        assert code == 0 and "[System — " in out and "loaded into memory" in err, err
        # An unreachable Neo4j is an honest error, never a silent fallback.
        code, out, err = query("--backend", "neo4j", "entity", "system.payments")
        assert code == 0
        bad = dict(env, NEO4J_URI="bolt://127.0.0.1:1")
        r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root, "entity", "system.payments"],
                           cwd=repo, env=dict(bad, PYTHONPATH=repo), capture_output=True, text=True, timeout=120)
        assert r.returncode == 1 and "cannot reach Neo4j" in r.stdout and "[System — " not in r.stdout
