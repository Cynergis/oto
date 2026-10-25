# -*- coding: utf-8 -*-
"""The Neo4j connector: the built graph into a self-hosted Neo4j, loaded and read back.

The Cypher lives in `targets/neo4j.py` and the row shapes in `targets/neo4j_map.py`; this is the
interface over them. The schema compiler turns the vocabulary into constraints: a unique key on
every entity, one per declared class, and the full-text indexes the query engine needs, all
`IF NOT EXISTS`, so applying the same vocabulary again changes nothing. Every key is
`<project>:<id>`; a session may carry its own project tag, so two stores of one build in one
database never collide, which is how the conformance kit checks that ids stay the same between them.
"""
from . import Connector
from ..targets import neo4j as _target, neo4j_map as _map

MANIFEST = {
    "name": "neo4j", "version": "1.0.0", "modes": ["materialize"], "query_language": "cypher",
    "capabilities": {"named_graphs": True, "schema_constraints": True, "transactions": True, "vector_index": True,
                     "full_text": True},
    "auth": ["basic", "oidc"], "conformance": "kit@1",
}
BASE_SCHEMA = (
    "CREATE CONSTRAINT oto_entity_key IF NOT EXISTS FOR (n:Entity) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT oto_evidence_key IF NOT EXISTS FOR (n:Evidence) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT oto_source_key IF NOT EXISTS FOR (n:Source) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT oto_passage_key IF NOT EXISTS FOR (n:Passage) REQUIRE n.key IS UNIQUE",
    "CREATE FULLTEXT INDEX oto_entity_text IF NOT EXISTS FOR (n:Entity) ON EACH [n.label, n.summary, n.aliases_text]",
    "CREATE FULLTEXT INDEX oto_passage_text IF NOT EXISTS FOR (n:Passage) ON EACH [n.title, n.body]",
)


def connector():
    return Neo4jConnector()


class Neo4jConnector(Connector):
    name = "neo4j"
    MANIFEST = MANIFEST

    # ---- sessions ----
    def settings(self, project):
        return dict(_target.settings(project), project=project.identity()["slug"])

    def connect(self, settings):
        if not _target.available():
            from ..project import ProjectError
            raise ProjectError("the neo4j connector needs the driver: pip install \"oto-kg[neo4j] @ git+<the engine repository>\"")
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(settings["uri"], auth=settings["auth"])
        driver.verify_connectivity()
        return {"driver": driver, "database": settings.get("database") or "neo4j",
                "batch": int(settings.get("batch") or _target.DEFAULT_BATCH), "project": settings.get("project")}

    def close(self, session):
        session["driver"].close()

    # ---- schema (K3: the vocabulary compiled to constraints) ----
    def schema_statements(self, vocabulary):
        """The base constraints and indexes, then one unique key per class the vocabulary declares."""
        statements = list(BASE_SCHEMA)
        for name in sorted((vocabulary or {}).get("classes") or {}):
            try:
                label = _map.safe_name(name)
            except ValueError:
                continue
            statements.append("CREATE CONSTRAINT oto_%s_key IF NOT EXISTS FOR (n:%s) REQUIRE n.key IS UNIQUE" % (label.lower(), label))
        return statements

    def apply_schema(self, session, vocabulary):
        statements = self.schema_statements(vocabulary)
        for statement in statements:
            session["driver"].execute_query(statement, {}, database_=session["database"])
        return len(statements)

    def schema_snapshot(self, session):
        names = []
        for query in ("SHOW CONSTRAINTS YIELD name RETURN name", "SHOW INDEXES YIELD name RETURN name"):
            records, _s, _k = session["driver"].execute_query(query, {}, database_=session["database"])
            names += [str(r["name"]) for r in records]
        return sorted(n for n in names if n.startswith("oto_"))

    # ---- the plan ----
    def plan(self, project):
        return _target.build_plan(project)

    def _for(self, session, plan):
        """The plan keyed for the session's project tag, when it differs from the plan's."""
        tag = session.get("project")
        return _map.rekey(plan, tag) if tag and tag != plan["project"] else plan

    def drop(self, plan, node_id):
        return _map.without(plan, node_id)

    # ---- publish and read back ----
    def publish(self, session, plan):
        planned = self._for(session, plan)
        statements = _target.load(session["driver"], session["database"], planned, batch=session["batch"])
        return dict(_map.summary(planned), statements=statements)

    def read_back(self, session, plan):
        return _target.verify(session["driver"], session["database"], self._for(session, plan))

    def snapshot(self, session, plan):
        planned = self._for(session, plan)
        project = planned["project"]
        prefix = project + ":"

        def local(key):
            return key[len(prefix):] if isinstance(key, str) and key.startswith(prefix) else key
        records, _s, _k = session["driver"].execute_query(
            "MATCH (n:Entity {project: $project}) RETURN n.key AS key, n.label AS label, labels(n) AS labels, n.status AS status",
            {"project": project}, database_=session["database"])
        entities = {local(r["key"]): {"type": next(iter(sorted(set(r["labels"]) - {"Entity"})), None),
                                      "label": r["label"], "status": r["status"]} for r in records}
        records, _s, _k = session["driver"].execute_query(
            "MATCH (a:Entity {project: $project})-[r]->(b:Entity) RETURN a.key AS a, type(r) AS rel, b.key AS b, r.kind AS kind",
            {"project": project}, database_=session["database"])
        relationships = sorted([local(r["a"]), r["rel"], local(r["b"]), r["kind"] or "asserted"] for r in records)
        records, _s, _k = session["driver"].execute_query(
            "MATCH (n:Entity {project: $project}) RETURN count(n) AS n", {"project": project}, database_=session["database"])
        rows = int(records[0]["n"]) if records else 0
        return {"ids": sorted(entities), "entities": entities, "relationships": relationships, "rows": rows}

    # ---- the build stage ----
    def stage(self, project):
        """What `oto build` runs when the project targets Neo4j."""
        from ..project import ProjectError
        if not _target.configured(project):
            print("neo4j: not configured (no `neo4j.uri` in project.config.json, or `neo4j` not in targets); skipped")
            return
        if not _target.available():
            raise ProjectError("neo4j target is configured but the driver is not installed: "
                               "pip install \"oto-kg[neo4j] @ git+<the engine repository>\"")
        settings = self.settings(project)
        plan = self.plan(project)
        counts = _map.summary(plan)
        session = self.connect(settings)
        try:
            result = self.publish(session, plan)
            print("neo4j: loaded %d entities, %d relationships, %d evidence, %d sources, %d passages into %s (%s) in %d statements"
                  % (counts["nodes"], counts["relationships"], counts["evidence"], counts["documents"], counts["passages"],
                     settings["uri"], session["database"], result["statements"]))
            if (getattr(project, "options", {}) or {}).get("verify"):
                differences = self.read_back(session, plan)
                if differences:
                    raise ProjectError("neo4j: the loaded graph differs from the build:\n  - " + "\n  - ".join(differences[:20]))
                print("neo4j: verified: the loaded graph matches the build")
        finally:
            self.close(session)
