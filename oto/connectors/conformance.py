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
    finally:
        connector.close(a)

    return {"connector": getattr(connector, "name", None), "kit": KIT_VERSION,
            "passed": all(c["passed"] for c in checks), "checks": checks}


def report(result):
    """The kit's result as text."""
    lines = ["connector %s against kit@%d: %s" % (result["connector"], result["kit"], "passed" if result["passed"] else "FAILED")]
    for check in result["checks"]:
        lines.append("  %-14s %s%s" % (check["name"], "ok" if check["passed"] else "FAILED",
                                       "" if check["passed"] else ": " + check["detail"]))
    return "\n".join(lines)
