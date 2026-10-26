# -*- coding: utf-8 -*-
"""The conformance kit: what a connector must prove before it is listed.

Run against a built project and a way to open fresh sessions (`sessions(name)`, called for "a" and
"b"), it checks, in order:

    manifest        the manifest validates (`manifest_problems`)
    interface       every method of the interface is implemented
    schema          the vocabulary's schema applied twice leaves the store's schema unchanged
    round trip      a publish, then read_back, differs in nothing
    idempotency     the same plan published again leaves the store exactly as it was, no duplicates
    iri stability   the same plan published to a second store gives the same ids, so the IRI of
                    every node, which derives from its id, is the same in dev and in prod
    retirement      a plan without one node, published, retires that node and its edges

and, for a connector whose manifest declares `overlay`, against a populated store (the one the kit
just published when the connector materializes too, else the session `sessions("overlay")` opens):

    overlay introspect  the catalog read twice is the same catalog; every table has a name and a kind,
                        every column a name and a type
    overlay read-only   a SELECT answers; a statement that would write is refused in words and
                        changes nothing
    overlay log         the query log is a list (empty where the store keeps none)

A failed check carries what differed. The suite runs this for SQLite everywhere and for Neo4j where
one is reachable; `oto connectors check <name>` runs it by hand.
"""
from . import KIT_VERSION, interface_problems, manifest_problems  # noqa: F401  (KIT_VERSION is the kit's)


def run(connector, project, sessions):
    """{"connector", "kit", "passed", "checks": [{"name", "passed", "detail"}]}."""
    import json
    checks = []

    def check(name, fn):
        try:
            detail = fn()
            checks.append({"name": name, "passed": not detail, "detail": detail or "ok"})
        except Exception as exc:                                       # noqa: BLE001 - the kit reports, never raises
            checks.append({"name": name, "passed": False, "detail": "%s: %s" % (type(exc).__name__, exc)})

    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)

    check("manifest", lambda: "; ".join(manifest_problems(getattr(connector, "MANIFEST", None))))
    check("interface", lambda: "; ".join(interface_problems(connector)))
    modes = (getattr(connector, "MANIFEST", None) or {}).get("modes") or []

    if "materialize" not in modes:
        if "overlay" in modes:
            own = sessions("overlay")
            try:
                _overlay_checks(connector, own, check)
            finally:
                connector.close(own)
        return {"connector": getattr(connector, "name", None), "kit": KIT_VERSION,
                "passed": all(c["passed"] for c in checks), "checks": checks}

    a = sessions("a")
    try:
        def schema():
            connector.apply_schema(a, vocabulary)
            first = connector.schema_snapshot(a)
            connector.apply_schema(a, vocabulary)
            second = connector.schema_snapshot(a)
            return "" if first == second else "applying the schema again changed it: %s -> %s" % (first, second)
        check("schema", schema)

        plan = connector.plan(project)
        state = {}

        def round_trip():
            connector.publish(a, plan)
            differences = connector.read_back(a, plan)
            state["after_first"] = connector.snapshot(a, plan)
            return "; ".join(differences[:5])
        check("round trip", round_trip)

        def idempotency():
            connector.publish(a, plan)
            again = connector.snapshot(a, plan)
            if again != state.get("after_first"):
                return "a second publish changed the store: %d rows, then %d" % (
                    (state.get("after_first") or {}).get("rows", -1), again.get("rows", -1))
            return "; ".join(connector.read_back(a, plan)[:5])
        check("idempotency", idempotency)

        b = sessions("b")
        try:
            def stability():
                connector.apply_schema(b, vocabulary)
                connector.publish(b, plan)
                there = connector.snapshot(b, plan)
                here = state.get("after_first") or connector.snapshot(a, plan)
                if there.get("ids") != here.get("ids"):
                    only_here = sorted(set(here.get("ids", [])) - set(there.get("ids", [])))[:3]
                    only_there = sorted(set(there.get("ids", [])) - set(here.get("ids", [])))[:3]
                    return "ids differ between the two stores: only in the first %s, only in the second %s" % (only_here, only_there)
                return ""
            check("iri stability", stability)
        finally:
            connector.close(b)

        def retirement():
            ids = [n["id"] for n in plan["nodes"]] if isinstance(plan.get("nodes"), list) and plan["nodes"] and "id" in plan["nodes"][0] \
                else [n["props"]["id"] for n in plan["nodes"]]
            if not ids:
                return "the plan has no node to retire"
            gone = ids[-1]
            smaller = connector.drop(plan, gone)
            connector.publish(a, smaller)
            after = connector.snapshot(a, smaller)
            if gone in after.get("ids", []):
                return "node %s was published, then left out of the next publish, and is still in the store" % gone
            if any(gone in (r[0], r[2]) for r in after.get("relationships", [])):
                return "node %s is gone but its edges are still in the store" % gone
            return "; ".join(connector.read_back(a, smaller)[:5])
        check("retirement", retirement)

        if "overlay" in modes:
            _overlay_checks(connector, a, check)
    finally:
        connector.close(a)

    return {"connector": getattr(connector, "name", None), "kit": KIT_VERSION,
            "passed": all(c["passed"] for c in checks), "checks": checks}


def _overlay_checks(connector, own, check):
    """The overlay half, against a populated store `own`: the catalog read in place, a read-only
    query answered, a write refused, the log a list."""
    def introspect():
        first = connector.introspect(own)
        second = connector.introspect(own)
        if first != second:
            return "the catalog read twice differs"
        if not isinstance(first.get("tables"), list) or not first.get("store"):
            return "introspect returns {store, tables}"
        for t in first["tables"]:
            if not t.get("name") or t.get("kind") not in ("table", "view"):
                return "table %r has no name or no kind (table or view)" % (t.get("name"),)
            for c in t.get("columns") or []:
                if not c.get("name") or not c.get("type"):
                    return "column %r of %s has no name or no type" % (c.get("name"), t["name"])
        return "" if first["tables"] else "the store has no table to describe"
    check("overlay introspect", introspect)

    def read_only():
        answered = connector.native_read(own, "SELECT 1 AS one")
        if answered.get("rows") != [[1]] or answered.get("columns") != ["one"]:
            return "SELECT 1 did not answer [[1]]: %s" % (answered,)
        before = connector.introspect(own)
        for sql in ("DELETE FROM %s" % before["tables"][0]["name"], "CREATE TABLE oto_kit_probe (a)"):
            try:
                connector.native_read(own, sql)
            except ValueError:
                continue
            return "%r was not refused" % sql
        if connector.introspect(own) != before:
            return "a refused statement changed the catalog"
        return ""
    check("overlay read-only", read_only)

    def log():
        entries = connector.query_log(own)
        return "" if isinstance(entries, list) else "query_log returns a list"
    check("overlay log", log)


def report(result):
    """The kit's result as text."""
    lines = ["connector %s against kit@%d: %s" % (result["connector"], result["kit"], "passed" if result["passed"] else "FAILED")]
    for check in result["checks"]:
        lines.append("  %-14s %s%s" % (check["name"], "ok" if check["passed"] else "FAILED",
                                       "" if check["passed"] else ": " + check["detail"]))
    return "\n".join(lines)
