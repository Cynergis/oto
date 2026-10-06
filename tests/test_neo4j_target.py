"""The Neo4j loader: its queries and cleanup against a fake driver, and the real thing where a
database is reachable (NEO4J_URI, NEO4J_PASSWORD)."""
import json
import os
import tempfile

import pytest

from oto.builder import build
from oto.cli import main
from oto.project import Project
from oto.scaffold import init
from oto.targets import neo4j as target, neo4j_map as m


class FakeDriver:
    """Records every statement. Answers the load-number query with a fixed count."""
    def __init__(self):
        self.calls = []
    def execute_query(self, query, params=None, database_=None):
        self.calls.append((query, params or {}, database_))
        if "RETURN p.loads AS loads" in query:
            return [{"loads": 3}], None, None
        if "RETURN n.key AS key" in query:
            return [], None, None
        if "RETURN type(r) AS type" in query:
            return [], None, None
        return [], None, None
    def verify_connectivity(self):
        pass
    def close(self):
        pass


def _project(root, configure=True):
    init(root, name="Arch", ontology="software-architecture")
    project = Project.standard(root)
    # Give the shipped rules a hop to take, so the plan carries a derived relationship.
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "payments", "aka": ["the payments system"], "targets": ["system.payments"],
                                "status": "current", "note": ""}]}, f)
    if configure:
        cfg = json.load(open(project.config_path, encoding="utf-8"))
        cfg["targets"] = ["sqlite", "neo4j"]
        cfg["neo4j"] = {"uri": "bolt://localhost:7687", "database": "neo4j", "batch": 2}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
    return project


def test_unconfigured_projects_skip_the_stage_and_never_import_the_driver(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, configure=False)
        build(project)
        assert "neo4j: not configured" in capsys.readouterr().out


def test_the_stage_is_forced_with_a_build_flag_and_needs_a_password(monkeypatch):
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, configure=False)
        cfg = json.load(open(project.config_path, encoding="utf-8"))
        cfg["neo4j"] = {"uri": "bolt://localhost:7687"}
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        project.options = {"targets": {"neo4j"}, "verify": False}
        assert target.configured(project)
        monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
        monkeypatch.delenv("NEO4J_AUTH", raising=False)
        with pytest.raises(Exception, match="NEO4J_PASSWORD"):
            target.settings(project)
        monkeypatch.setenv("NEO4J_AUTH", "neo4j/secret")
        assert target.settings(project)["auth"] == ("neo4j", "secret")


def test_load_writes_constraints_batches_and_retires_the_previous_load():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project, only={"knowledge", "rules"})
        planned = target.build_plan(project)
        driver = FakeDriver()
        statements = target.load(driver, "neo4j", planned, batch=2)
        queries = [q for q, _p, _d in driver.calls]
        assert any("CREATE CONSTRAINT oto_entity_key IF NOT EXISTS" in q for q in queries)
        assert any("CREATE FULLTEXT INDEX oto_entity_text" in q for q in queries)
        assert any("CREATE FULLTEXT INDEX oto_passage_text" in q for q in queries), "passage search needs its index"
        assert any("MERGE (p:Passage {key: row.key})" in q for q in queries), "the corpus is loaded for kg_search"
        assert any("MERGE (l:Lexicon {key: row.key})" in q for q in queries)
        assert any("MERGE (d:Source {key: row.key})" in q for q in queries), "a source document is :Source, never :Document"
        assert not any("MERGE (d:Document" in q for q in queries)
        head = [p for q, p, _d in driver.calls if "MERGE (p:OtoProject" in q][0]
        assert head["schema"] == 6, "the engine refuses a load from the future by this number"
        assert all(d == "neo4j" for _q, _p, d in driver.calls)
        node_batches = [(q, p) for q, p, _d in driver.calls if "MERGE (n:Entity {key: row.key})" in q]
        assert node_batches and all(len(p["rows"]) <= 2 for _q, p in node_batches), "batched"
        assert any("n:`Component`" in q for q, _p in node_batches)
        rel_batches = [(q, p) for q, p, _d in driver.calls if "MERGE (a)-[r:`" in q]
        assert any("[r:`part_of` {kind: row.kind}]" in q for q, _p in rel_batches)
        assert any("[r:`threatens`" in q and any(r["kind"] == "derived" for r in p["rows"]) for q, p in rel_batches), \
            "derived relationships load with kind=derived"
        cleanup = [q for q in queries if "DETACH DELETE n" in q or "DELETE r" in q]
        assert len(cleanup) == 2 and queries.index(cleanup[0]) > max(queries.index(q) for q, _p in rel_batches), \
            "the previous load is retired only after the new facts are in"
        load_ids = {p["load"] for q, p, _d in driver.calls if "load" in p}
        assert load_ids == {"%s:3" % planned["build_seq"]}
        assert statements == len(driver.calls)


def test_verify_reports_what_differs():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project, only={"knowledge", "rules"})
        planned = target.build_plan(project)

        class Answering(FakeDriver):
            def execute_query(self, query, params=None, database_=None):
                if "RETURN n.key AS key" in query:
                    rows = [{"key": n["props"]["key"], "label": n["props"]["label"], "labels": ["Entity", n["label"]],
                             "status": n["props"]["status"]} for n in planned["nodes"][1:]]
                    rows[0] = dict(rows[0], status="superseded")
                    return rows, None, None
                if "RETURN type(r) AS type" in query:
                    want = {}
                    for r in planned["rels"]:
                        want[r["type"]] = want.get(r["type"], 0) + 1
                    want["EVIDENCED_BY"] = len(planned["evidence"])
                    return [{"type": t, "n": n} for t, n in want.items()], None, None
                return super().execute_query(query, params, database_)

        differences = target.verify(Answering(), "neo4j", planned)
        assert any(d.startswith("missing entity ") for d in differences)
        assert any("differs: planned" in d for d in differences)
        assert not any(d.startswith("relationship part_of") for d in differences)


def test_the_plan_matches_the_store_it_sits_beside():
    """Whatever SQLite holds, Neo4j is planned to hold: same entities, same relations, derived ones marked."""
    import sqlite3

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project, only={"knowledge", "rules", "ontology", "semantic", "sqlite"})
        planned = target.build_plan(project)
        con = sqlite3.connect(project.layout.database)
        ids = {r[0] for r in con.execute("SELECT id FROM nodes")}
        assert {n["props"]["id"] for n in planned["nodes"]} == ids
        derived = con.execute("SELECT count(*) FROM edges WHERE status='derived'").fetchone()[0]
        assert sum(1 for r in planned["rels"] if r["props"]["kind"] == "derived") == derived


def test_the_base_install_never_imports_the_driver():
    import subprocess, sys
    code = "import sys, oto.cli, oto.builder, oto.targets.neo4j_map; print('neo4j' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PATH": os.environ.get("PATH", ""), "OTO_ONTOLOGIES": os.environ.get("OTO_ONTOLOGIES", "")})
    assert out.stdout.strip() == "False", out.stderr


@pytest.mark.skipif(not os.environ.get("NEO4J_URI") or not (os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_AUTH")),
                    reason="no Neo4j reachable: set NEO4J_URI and NEO4J_PASSWORD")
def test_a_real_load_verifies_and_a_second_load_retires_what_left(capsys):
    pytest.importorskip("neo4j")
    from neo4j import GraphDatabase

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        cfg = json.load(open(project.config_path, encoding="utf-8"))
        cfg["neo4j"]["uri"] = os.environ["NEO4J_URI"]
        cfg["neo4j"]["database"] = os.environ.get("NEO4J_DATABASE", "neo4j")
        cfg["slug"] = "ototest-%d" % os.getpid()
        json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
        project = Project.standard(root)
        assert main(["build", "--project", root, "--verify"]) == 0
        assert "neo4j: verified" in capsys.readouterr().out
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["edges"] = [e for e in graph["edges"] if e["rel"] != "operated_by"]
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        assert main(["build", "--project", root, "--verify"]) == 0
        conf = target.settings(project)
        driver = GraphDatabase.driver(conf["uri"], auth=conf["auth"])
        try:
            records, _s, _k = driver.execute_query(
                "MATCH ({project: $p})-[r:operated_by]->() RETURN count(r) AS n", {"p": cfg["slug"]}, database_=conf["database"])
            assert records[0]["n"] == 0, "a retired relationship must be gone after the next load"
            driver.execute_query("MATCH (n {project: $p}) DETACH DELETE n", {"p": cfg["slug"]}, database_=conf["database"])
        finally:
            driver.close()
