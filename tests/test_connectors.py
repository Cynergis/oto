"""Connectors (roadmap Epic K, materialize): one interface the core calls, a manifest that says what
each store can do, a schema compiled from the vocabulary that changes nothing when applied again,
and a conformance kit no connector is listed without: round trip, idempotency, IRI stability,
retirement. SQLite is the connector every machine has; Neo4j runs where one is reachable."""
import io
import json
import os
import sqlite3
import contextlib

import pytest

from oto import connectors
from oto.builder import build
from oto.cli import main
from oto.connectors import conformance
from oto.project import Project
from oto.scaffold import init


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def project(tmp_path):
    root = str(tmp_path / "arch")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, name="Arch", ontology="software-architecture")
        p = Project.standard(root)
        with open(p.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["edges"].append({"from": "datastore.ledger", "rel": "part_of", "to": "system.payments"})
        with open(p.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        build(p, only={"knowledge", "rules", "ontology", "semantic"})
    return p


# ---- K1: the interface and the manifest ----

def test_the_shipped_connectors_are_listed_with_valid_manifests():
    assert connectors.available() == ["neo4j", "sqlite"]
    for name in connectors.available():
        manifest = connectors.get(name).MANIFEST
        assert connectors.manifest_problems(manifest) == [], name
        assert manifest["name"] == name and manifest["modes"] == (["materialize", "overlay"] if name == "sqlite" else ["materialize"])
        assert manifest["conformance"] == "kit@%d" % conformance.KIT_VERSION
    assert connectors.get("sqlite").MANIFEST["query_language"] == "sql" and connectors.get("neo4j").MANIFEST["query_language"] == "cypher"
    assert connectors.get("neo4j").MANIFEST["capabilities"]["full_text"] is True


@pytest.mark.parametrize("change, said", [
    (lambda m: m.pop("modes"), "`modes`"),
    (lambda m: m.update(modes=["overlay", "teleport"]), "teleport"),
    (lambda m: m.update(modes=[]), "at least one mode"),
    (lambda m: m["capabilities"].update(magic=True), "unknown capability"),
    (lambda m: m["capabilities"].update(transactions="yes"), "true or false"),
    (lambda m: m.update(conformance="passed@1.2.0"), "kit@"),
    (lambda m: m.update(auth="basic"), "a list"),
])
def test_every_mistake_in_a_manifest_is_named(change, said):
    manifest = json.loads(json.dumps(connectors.get("sqlite").MANIFEST))
    change(manifest)
    problems = connectors.manifest_problems(manifest)
    assert problems and any(said in p for p in problems), problems


def test_a_connector_must_implement_the_whole_interface():
    class Half(connectors.Connector):
        name = "half"
    missing = connectors.interface_problems(Half)
    assert missing and all(name in " ".join(missing) for name in ("connect", "apply_schema", "plan", "publish", "read_back", "snapshot"))
    assert connectors.interface_problems(connectors.get("sqlite")) == []
    assert connectors.interface_problems(connectors.get("neo4j")) == []


# ---- K3: the schema compiler ----

def test_the_neo4j_schema_is_compiled_from_the_vocabulary_and_applies_again_without_change(project):
    from tests.test_neo4j_target import FakeDriver
    neo = connectors.get("neo4j")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    statements = neo.schema_statements(vocabulary)
    assert all("IF NOT EXISTS" in s for s in statements), "re-applying the same ontology changes nothing"
    assert any("FOR (n:Entity) REQUIRE n.key IS UNIQUE" in s for s in statements), "a unique key at minimum"
    assert any("FOR (n:Component) REQUIRE n.key IS UNIQUE" in s for s in statements), "one per class the vocabulary declares"
    assert any("FOR (n:Document) REQUIRE n.key IS UNIQUE" in s for s in statements), "every declared class, Document included"
    driver = FakeDriver()
    applied = neo.apply_schema({"driver": driver, "database": "neo4j"}, vocabulary)
    assert applied == len(statements) and [q for q, _p, _d in driver.calls] == statements


def test_the_sqlite_schema_applies_twice_to_the_same_store(tmp_path):
    lite = connectors.get("sqlite")
    session = lite.connect({"path": str(tmp_path / "s.db")})
    try:
        lite.apply_schema(session, {"classes": {"Thing": {}}})
        first = lite.schema_snapshot(session)
        lite.apply_schema(session, {"classes": {"Thing": {}}})
        assert lite.schema_snapshot(session) == first and "nodes" in json.dumps(first)
    finally:
        lite.close(session)


# ---- K7: the conformance kit ----

def test_the_kit_passes_for_sqlite_and_says_what_it_checked(project, tmp_path):
    lite = connectors.get("sqlite")
    paths = iter([str(tmp_path / "a.db"), str(tmp_path / "b.db")])
    report = conformance.run(lite, project, lambda name: lite.connect({"path": next(paths)}))
    assert report["passed"] is True and report["connector"] == "sqlite" and report["kit"] == conformance.KIT_VERSION
    assert [c["name"] for c in report["checks"]] == ["manifest", "interface", "schema", "round trip", "idempotency",
                                                     "iri stability", "retirement", "overlay introspect", "overlay read-only", "overlay log"]
    assert all(c["passed"] for c in report["checks"]), report["checks"]


def test_the_kit_fails_a_connector_that_breaks_the_rules(project, tmp_path):
    lite = connectors.get("sqlite")

    class Drifting(connectors.Connector):
        """Writes the right rows, but mints a different id per session and duplicates on a second publish."""
        name = "drifting"
        MANIFEST = dict(lite.MANIFEST, name="drifting")
        connect, close, apply_schema, schema_snapshot, plan, read_back = (lite.connect, lite.close, lite.apply_schema,
                                                                           lite.schema_snapshot, lite.plan, lite.read_back)

        def publish(self, session, plan):
            tag = os.path.basename(session["path"])[0]
            plan = dict(plan, nodes=[dict(n, id="%s-%s" % (tag, n["id"])) for n in plan["nodes"]],
                        edges=[dict(e, **{"from": "%s-%s" % (tag, e["from"]), "to": "%s-%s" % (tag, e["to"])}) for e in plan["edges"]])
            return lite.publish(session, plan, append=True)

        def snapshot(self, session, plan):
            return lite.snapshot(session, plan)

    paths = iter([str(tmp_path / "a.db"), str(tmp_path / "b.db")])
    report = conformance.run(Drifting(), project, lambda name: lite.connect({"path": next(paths)}))
    failed = {c["name"] for c in report["checks"] if not c["passed"]}
    assert report["passed"] is False and {"round trip", "iri stability"} <= failed, report["checks"]


def test_the_sqlite_stage_still_writes_the_store_through_the_connector(project):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        build(project, only={"sqlite"})
    assert "nodes" in out.getvalue() and os.path.exists(project.layout.database)
    con = sqlite3.connect(project.layout.database)
    try:
        assert con.execute("SELECT count(*) FROM nodes").fetchone()[0] > 0
        assert con.execute("SELECT count(*) FROM edges WHERE status = 'derived'").fetchone()[0] > 0
    finally:
        con.close()


def test_the_cli_lists_connectors_and_runs_the_kit(project):
    code, out = _cli("connectors")
    assert code == 0 and "sqlite" in out and "neo4j" in out and "materialize" in out and "kit@%d" % conformance.KIT_VERSION in out
    code, out = _cli("connectors", "check", "sqlite", "--project", project.data)
    assert code == 0 and "round trip" in out and "iri stability" in out and "passed" in out, out
    code, out = _cli("connectors", "check", "mongo", "--project", project.data)
    assert code == 1 and "no connector" in out


LIVE = os.environ.get("NEO4J_URI") and (os.environ.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_AUTH"))


@pytest.mark.skipif(not LIVE, reason="no Neo4j reachable: set NEO4J_URI and NEO4J_PASSWORD")
def test_the_kit_passes_for_neo4j_where_one_is_reachable(project):
    neo = connectors.get("neo4j")
    cfg = json.load(open(project.config_path, encoding="utf-8"))
    cfg["targets"] = ["sqlite", "neo4j"]
    cfg["neo4j"] = {"uri": os.environ["NEO4J_URI"], "database": os.environ.get("NEO4J_DATABASE") or "neo4j", "batch": 3}
    json.dump(cfg, open(project.config_path, "w", encoding="utf-8"))
    settings = neo.settings(project)

    def session(name):
        return neo.connect(dict(settings, project="%s-kit-%s" % (settings["project"], name)))
    report = conformance.run(neo, project, session)
    assert report["passed"] is True, [c for c in report["checks"] if not c["passed"]]
