# -*- coding: utf-8 -*-
"""The SQLite connector: the indexed store every machine has, in one file beside the build.

The store's schema is fixed (`targets/sqlite.py`): entities, aliases, edges, derived facts, findings,
the corpus passages, the lexicon, the vocabulary's terms, the questions and the recent ledger, each a
table, with the node's id as primary key. A publish writes a fresh file next to the old one and
replaces it in one step, so a server holding the old file never reads a half-written store.
"""
import json
import os
import sqlite3

from . import Connector
from ..targets import sqlite as _target

MANIFEST = {
    "name": "sqlite", "version": "1.0.0", "modes": ["materialize"], "query_language": "sql",
    "capabilities": {"named_graphs": False, "schema_constraints": True, "transactions": True, "vector_index": False,
                     "full_text": True},
    "auth": ["file"], "conformance": "kit@1",
}


def connector():
    return SqliteConnector()


class SqliteConnector(Connector):
    name = "sqlite"
    MANIFEST = MANIFEST

    # ---- sessions ----
    def settings(self, project):
        return {"path": project.layout.database, "project": project.identity()["slug"]}

    def connect(self, settings):
        return {"path": settings["path"]}

    def close(self, session):
        pass

    # ---- schema ----
    def apply_schema(self, session, vocabulary):
        """The store's tables and indexes, created where they are not; the vocabulary declares no
        store-level constraint beyond the unique id, so the schema is the same for every project."""
        statements = [s.strip() for s in _target.SCHEMA_SQL.split(";") if s.strip()]
        if os.path.exists(session["path"]):
            con = sqlite3.connect(session["path"])
            try:
                if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nodes'").fetchone():
                    return 0
            finally:
                con.close()
        os.makedirs(os.path.dirname(os.path.abspath(session["path"])) or ".", exist_ok=True)
        con = sqlite3.connect(session["path"])
        try:
            con.execute("PRAGMA journal_mode=DELETE")
            con.executescript(_target.SCHEMA_SQL)
            con.commit()
        finally:
            con.close()
        return len(statements)

    def schema_snapshot(self, session):
        if not os.path.exists(session["path"]):
            return []
        con = sqlite3.connect(session["path"])
        try:
            return sorted(" ".join((r[0] or "").split()) for r in con.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        finally:
            con.close()

    # ---- the plan ----
    def plan(self, project):
        return _target.plan(project)

    def drop(self, plan, node_id):
        out = dict(plan)
        out["nodes"] = [n for n in plan["nodes"] if n["id"] != node_id]
        out["edges"] = [e for e in plan["edges"] if node_id not in (e["from"], e["to"])]
        derived = dict(plan.get("derived") or {})
        derived["derived_edges"] = [e for e in derived.get("derived_edges") or [] if node_id not in (e["from"], e["to"])]
        derived["derived_attributes"] = [a for a in derived.get("derived_attributes") or [] if a["node"] != node_id]
        derived["findings"] = [f for f in derived.get("findings") or [] if f.get("node") != node_id]
        out["derived"] = derived
        return out

    # ---- publish and read back ----
    def publish(self, session, plan, append=False):
        """Write the plan to the session's file: a fresh store replacing the old one, or, with
        `append`, rows added to the store as it stands (what the conformance kit uses to show a
        duplicate publish is caught)."""
        path = session["path"]
        if append and os.path.exists(path):
            con = sqlite3.connect(path)
            try:
                counts = _target.write(con, plan)
                con.commit()
            finally:
                con.close()
            return counts
        tmp = path + ".new"
        if os.path.exists(tmp):
            os.remove(tmp)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        con = sqlite3.connect(tmp)
        try:
            con.execute("PRAGMA journal_mode=DELETE")
            con.executescript(_target.SCHEMA_SQL)
            counts = _target.write(con, plan)
            con.commit()
            con.execute("PRAGMA optimize")
        finally:
            con.close()
        os.replace(tmp, path)
        return counts

    def snapshot(self, session, plan=None):
        con = sqlite3.connect(session["path"])
        try:
            entities = {r[0]: {"type": r[1], "label": r[2], "status": r[3]}
                        for r in con.execute("SELECT id, type, label, status FROM nodes ORDER BY id")}
            relationships = sorted([r[0], r[1], r[2], "derived" if r[3] == "derived" else "asserted"]
                                   for r in con.execute("SELECT src, rel, dst, status FROM edges"))
            rows = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
        finally:
            con.close()
        return {"ids": sorted(entities), "entities": entities, "relationships": relationships, "rows": rows}

    def read_back(self, session, plan):
        got = self.snapshot(session, plan)
        want_entities = {n["id"]: {"type": n.get("type"), "label": n.get("label"), "status": n.get("status", "current")}
                         for n in plan["nodes"]}
        differences = []
        for nid in sorted(set(want_entities) - set(got["entities"])):
            differences.append("missing entity %s" % nid)
        for nid in sorted(set(got["entities"]) - set(want_entities)):
            differences.append("unexpected entity %s" % nid)
        for nid in sorted(set(want_entities) & set(got["entities"])):
            if want_entities[nid] != got["entities"][nid]:
                differences.append("entity %s differs: planned %s, found %s" % (nid, want_entities[nid], got["entities"][nid]))
        if got["rows"] != len(want_entities):
            differences.append("entities: planned %d rows, found %d" % (len(want_entities), got["rows"]))
        want_rels = sorted([e["from"], e["rel"], e["to"], "asserted"] for e in plan["edges"])
        want_rels += sorted([e["from"], e["rel"], e["to"], "derived"] for e in (plan.get("derived") or {}).get("derived_edges") or [])
        if sorted(want_rels) != got["relationships"]:
            differences.append("relationships: planned %d, found %d" % (len(want_rels), len(got["relationships"])))
        return differences

    # ---- the build stage ----
    def stage(self, project):
        """What `oto build` runs: the plan into the project's store, and one line about it."""
        plan = self.plan(project)
        session = self.connect(self.settings(project))
        identity = project.identity()
        path = session["path"]
        try:
            counts = self.publish(session, plan)
        except PermissionError:
            tmp = path + ".new"
            print(f"WARNING: '{os.path.relpath(path, project.src)}' is locked - is the {identity['server_name']} "
                  f"server running? Fresh build left at '{os.path.relpath(tmp, project.src)}'. Stop the server "
                  f"and rename it over {identity['db_name']}, or rerun without the server. "
                  f"(CI is unaffected.)")
            raise SystemExit(0)
        print(f"{os.path.basename(path)}: {counts['nodes']} nodes, {counts['edges']} edges ({counts['derived']} derived), "
              f"{counts['passages']} passages, {counts['lexicon']} lexicon rows, {counts['terms']} terms, "
              f"{counts['questions']} questions -> {os.path.relpath(path, project.src)}")
