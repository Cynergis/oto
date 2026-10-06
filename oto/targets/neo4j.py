# -*- coding: utf-8 -*-
"""Stage 6, optional. Load the built graph into a self-hosted Neo4j.

Runs only when the project config names the target:

    "targets": ["sqlite", "neo4j"],
    "neo4j": {"uri": "bolt://localhost:7687", "database": "neo4j", "batch": 500}

with `NEO4J_USER` (default neo4j) and `NEO4J_PASSWORD` in the environment, never in a file. The
driver lives in the `neo4j` extra, so the base install stays dependency-free.

The load carries everything the query engine reads: entities, relations, evidence, derived facts,
findings, and also the corpus passages, the lexicon and the recent ledger, so `oto serve` can
answer from Neo4j alone (`"serve": {"backend": "neo4j"}`) exactly as it answers from SQLite.

The load is a content copy, not a byte copy. Every node and relationship carries the load's
`build_seq`; after the new facts are written, anything of this project with an older sequence is
deleted, so a fact retired in the graph is retired in Neo4j on the next load. A failure mid-load
leaves the previous build's facts in place and the local build untouched; the error names the
stage. `--verify` reads the graph back and compares it to what was planned.
"""
import json
import os

from ..project import ProjectError
from . import neo4j_map as _map

DEFAULT_BATCH = 500


def available():
    try:
        import neo4j  # noqa: F401
        return True
    except ImportError:
        return False


def configured(project):
    cfg = project.config()
    targets = cfg.get("targets") or ["sqlite"]
    forced = "neo4j" in (getattr(project, "options", {}) or {}).get("targets", set())
    return ("neo4j" in targets or forced) and bool((cfg.get("neo4j") or {}).get("uri"))


def credentials():
    """(user, password) from the environment, or None. `NEO4J_PASSWORD` with `NEO4J_USER` (default
    neo4j), or the Docker-style `NEO4J_AUTH=user/password`. Never from a file."""
    user = os.environ.get("NEO4J_USER") or "neo4j"
    password = os.environ.get("NEO4J_PASSWORD")
    if not password and os.environ.get("NEO4J_AUTH", "").count("/") == 1:
        user, password = os.environ["NEO4J_AUTH"].split("/", 1)
    return (user, password) if password else None


def connection(cfg):
    """uri, database and batch from a project config's `neo4j` section; `NEO4J_URI` overrides the uri."""
    cfg = cfg or {}
    return {"uri": os.environ.get("NEO4J_URI") or cfg.get("uri"), "database": cfg.get("database") or "neo4j",
            "batch": int(cfg.get("batch") or DEFAULT_BATCH)}


def settings(project):
    conf = connection(project.config().get("neo4j"))
    auth = credentials()
    if not auth:
        raise ProjectError("neo4j target: set NEO4J_PASSWORD (and NEO4J_USER, default neo4j) in the environment")
    conf["auth"] = auth
    return conf


def build_plan(project):
    layout = project.layout
    with open(os.path.join(layout.graph, "knowledge-graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    derived_path = os.path.join(layout.graph, "derived.json")
    derived = json.load(open(derived_path, encoding="utf-8")) if os.path.exists(derived_path) else {}
    from . import rows as _rows
    from .sqlite import SCHEMA_VERSION
    return _map.plan(graph, config, project.identity()["slug"], int(project.build_seq()), derived,
                     passages=_rows.passages(layout), lexicon=_rows.lexicon_rows(project), terms=_rows.term_rows(project),
                     changelog=_rows.changelog_rows(project), schema_version=SCHEMA_VERSION)


# ---- the queries, one place, so a fake driver can check them ----

def _batches(rows, size):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def load(driver, database, planned, batch=DEFAULT_BATCH):
    """Write the plan. Returns the number of statements run. Idempotent for the same plan."""
    project, seq = planned["project"], planned["build_seq"]
    statements = 0

    def run(query, **params):
        nonlocal statements
        driver.execute_query(query, params, database_=database)
        statements += 1

    # One load number per project, so a rebuild of the same commit still retires what it removed.
    run("MERGE (p:OtoProject {key: $key}) SET p.slug = $slug, p.loads = coalesce(p.loads, 0) + 1, "
        "p.build_seq = $seq, p.schema_version = $schema RETURN p.loads",
        key="%s:project" % project, slug=project, seq=seq, schema=planned.get("schema_version"))
    run("CREATE CONSTRAINT oto_entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE n.key IS UNIQUE")
    run("CREATE CONSTRAINT oto_evidence_key IF NOT EXISTS FOR (n:Evidence) REQUIRE n.key IS UNIQUE")
    run("CREATE CONSTRAINT oto_source_key IF NOT EXISTS FOR (n:Source) REQUIRE n.key IS UNIQUE")
    run("CREATE CONSTRAINT oto_passage_key IF NOT EXISTS FOR (n:Passage) REQUIRE n.key IS UNIQUE")
    run("CREATE FULLTEXT INDEX oto_entity_text IF NOT EXISTS FOR (n:Entity) ON EACH [n.label, n.summary, n.aliases_text]")
    run("CREATE FULLTEXT INDEX oto_passage_text IF NOT EXISTS FOR (n:Passage) ON EACH [n.title, n.body]")

    load_id = "%s:%s" % (seq, _load_number(driver, database, project))
    statements += 1                                   # the read above is a statement too
    for label in planned["labels"]:
        rows = [{"key": n["props"]["key"], "props": dict(n["props"], load=load_id), "dates": n["dates"]}
                for n in planned["nodes"] if n["label"] == label]
        for chunk in _batches(rows, batch):
            run("UNWIND $rows AS row MERGE (n:Entity {key: row.key}) SET n = row.props, n:`%s` "
                "WITH n, row UNWIND row.dates AS d SET n[d] = date(n[d])" % label, rows=chunk)
    for chunk in _batches([dict(e, load=load_id) for e in planned["evidence"]], batch):
        run("UNWIND $rows AS row MERGE (e:Evidence {key: row.key}) SET e = row "
            "WITH e, row MATCH (n:Entity {key: row.entity}) MERGE (n)-[r:EVIDENCED_BY]->(e) SET r.load = row.load", rows=chunk)
    for chunk in _batches([dict(d, load=load_id) for d in planned["documents"]], batch):
        run("UNWIND $rows AS row MERGE (d:Source {key: row.key}) SET d = row", rows=chunk)
    for chunk in _batches([dict(p, load=load_id) for p in planned.get("passages") or []], batch):
        run("UNWIND $rows AS row MERGE (p:Passage {key: row.key}) SET p = row", rows=chunk)
    for chunk in _batches([dict(r, load=load_id) for r in planned.get("lexicon") or []], batch):
        run("UNWIND $rows AS row MERGE (l:Lexicon {key: row.key}) SET l = row", rows=chunk)
    for chunk in _batches([dict(r, load=load_id) for r in planned.get("changelog") or []], batch):
        run("UNWIND $rows AS row MERGE (c:Changelog {key: row.key}) SET c = row", rows=chunk)
    for chunk in _batches([dict(r, load=load_id) for r in planned.get("terms") or []], batch):
        run("UNWIND $rows AS row MERGE (t:Term {key: row.key}) SET t = row", rows=chunk)
    for chunk in _batches([dict(a, load=load_id) for a in planned["derived_attributes"]], batch):
        run("UNWIND $rows AS row MERGE (a:DerivedAttribute {key: row.key}) SET a = row "
            "WITH a, row MATCH (n:Entity {key: row.entity}) MERGE (a)-[r:DERIVED_ON]->(n) SET r.load = row.load", rows=chunk)
    for chunk in _batches([dict(f, load=load_id) for f in planned["findings"]], batch):
        run("UNWIND $rows AS row MERGE (f:PolicyFinding {key: row.key}) SET f = row "
            "WITH f, row WHERE row.entity IS NOT NULL MATCH (n:Entity {key: row.entity}) MERGE (f)-[r:FLAGS]->(n) SET r.load = row.load",
            rows=chunk)
    for rel_type in planned["rel_types"]:
        rows = [{"a": r["a"], "b": r["b"], "kind": r["props"].get("kind", "asserted"), "props": dict(r["props"], load=load_id)}
                for r in planned["rels"] if r["type"] == rel_type]
        for chunk in _batches(rows, batch):
            run("UNWIND $rows AS row MATCH (a {key: row.a}), (b {key: row.b}) "
                "MERGE (a)-[r:`%s` {kind: row.kind}]->(b) SET r = row.props" % rel_type, rows=chunk)

    # Retire what the previous load wrote and this one did not.
    run("MATCH (n {project: $project}) WHERE n.load <> $load DETACH DELETE n", project=project, load=load_id)
    run("MATCH ({project: $project})-[r]-() WHERE r.load <> $load DELETE r", project=project, load=load_id)
    return statements


def _load_number(driver, database, project):
    records, _summary, _keys = driver.execute_query(
        "MATCH (p:OtoProject {key: $key}) RETURN p.loads AS loads", {"key": "%s:project" % project}, database_=database)
    return int(records[0]["loads"]) if records else 1


def verify(driver, database, planned):
    """Read the project back and compare it to the plan. Returns the differences, empty when none."""
    project = planned["project"]
    differences = []
    records, _s, _k = driver.execute_query(
        "MATCH (n:Entity {project: $project}) RETURN n.key AS key, n.label AS label, labels(n) AS labels, n.status AS status",
        {"project": project}, database_=database)
    got = {r["key"]: (r["label"], sorted(set(r["labels"]) - {"Entity"}), r["status"]) for r in records}
    want = {n["props"]["key"]: (n["props"].get("label"), [n["label"]], n["props"].get("status")) for n in planned["nodes"]}
    for k in sorted(set(want) - set(got)):
        differences.append("missing entity %s" % k)
    for k in sorted(set(got) - set(want)):
        differences.append("unexpected entity %s" % k)
    for k in sorted(set(want) & set(got)):
        if want[k] != got[k]:
            differences.append("entity %s differs: planned %s, found %s" % (k, want[k], got[k]))
    records, _s, _k = driver.execute_query(
        "MATCH ({project: $project})-[r]->() RETURN type(r) AS type, count(r) AS n",
        {"project": project}, database_=database)
    got_rels = {r["type"]: int(r["n"]) for r in records}
    want_rels = {}
    for r in planned["rels"]:
        want_rels[r["type"]] = want_rels.get(r["type"], 0) + 1
    want_rels["EVIDENCED_BY"] = len(planned["evidence"])
    want_rels["DERIVED_ON"] = len(planned["derived_attributes"])
    want_rels["FLAGS"] = len([f for f in planned["findings"] if f.get("entity")])
    for t in sorted(set(want_rels) | set(got_rels)):
        if want_rels.get(t, 0) != got_rels.get(t, 0):
            differences.append("relationship %s: planned %d, found %d" % (t, want_rels.get(t, 0), got_rels.get(t, 0)))
    records, _s, _k = driver.execute_query(
        "MATCH (p:Passage {project: $project}) RETURN count(p) AS n", {"project": project}, database_=database)
    got_passages = int(records[0]["n"]) if records else 0
    if got_passages != len(planned.get("passages") or []):
        differences.append("passages: planned %d, found %d" % (len(planned.get("passages") or []), got_passages))
    return differences


def run(project):
    if not configured(project):
        print("neo4j: not configured (no `neo4j.uri` in project.config.json, or `neo4j` not in targets); skipped")
        return
    if not available():
        raise ProjectError("neo4j target is configured but the driver is not installed: "
                           "pip install \"oto-kg[neo4j] @ git+<the engine repository>\"")
    from neo4j import GraphDatabase

    conf = settings(project)
    planned = build_plan(project)
    counts = _map.summary(planned)
    driver = GraphDatabase.driver(conf["uri"], auth=conf["auth"])
    try:
        driver.verify_connectivity()
        statements = load(driver, conf["database"], planned, batch=conf["batch"])
        print("neo4j: loaded %d entities, %d relationships, %d evidence, %d sources, %d passages into %s (%s) in %d statements"
              % (counts["nodes"], counts["relationships"], counts["evidence"], counts["documents"], counts["passages"],
                 conf["uri"], conf["database"], statements))
        if (getattr(project, "options", {}) or {}).get("verify"):
            differences = verify(driver, conf["database"], planned)
            if differences:
                raise ProjectError("neo4j: the loaded graph differs from the build:\n  - " + "\n  - ".join(differences[:20]))
            print("neo4j: verified: the loaded graph matches the build")
    finally:
        driver.close()
