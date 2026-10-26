# -*- coding: utf-8 -*-
"""The factory's inputs, read from the graph (roadmap Epic I). This release: the spec as a projection
(I3) and the plan from contract dependencies (I5).

    oto factory spec <component> [--out <file>]        # the component's spec, as the graph says it
    oto factory spec --check <file>                    # the shape holds and nobody edited it by hand
    oto factory plan [--all | --context <id>] [--json] [--out <file>]

A spec is a projection: the component (a CALM node), the bounded context it carries and the use
cases of that context, what it exposes and consumes with each contract's version and status, the
requirements it satisfies with their budgets and the latest measurement, the decisions that
govern it, the controls on it and its connections, its connections, the modules that implement it
with their last commit, and the open change proposals about it. It is schema-checked here (a
small, deterministic shape, no library) and carries a hash of its own content, so `--check`
refuses a spec edited by hand: nobody edits a spec, the graph does.

A plan is read from contract dependencies: a component that consumes an interface whose contract
is frozen builds in parallel with the provider; one that consumes a draft contract, or an
interface with none, or depends on a component with no interface between them, waits for it.
The groups are the levels of that order; a cycle of draft dependencies is named, never looped.
By default the plan is for the components a signed-off context (`readiness` ready or built)
runs as; `--context` for one context; `--all` for every CALM component.
"""
import datetime
import hashlib
import json

from .project import ProjectError

SCHEMA_VERSION = 1
LISTS = ("use_cases", "exposes", "consumes", "requirements", "decisions", "controls", "connections", "modules", "open_change_proposals")


class FactoryError(ProjectError):
    """A refusal, in words the person can act on."""


def _index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    out, inc = {}, {}
    for e in graph.get("edges") or []:
        out.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
        inc.setdefault((e.get("to"), e.get("rel")), []).append(e.get("from"))
    return nodes, out, inc


def _a(n):
    return (n or {}).get("attributes") or {}


def _contracts(nodes, inc, interface_id):
    found = []
    for cid in inc.get((interface_id, "contract_of"), []):
        c = nodes.get(cid)
        if c is None or c.get("type") != "Contract" or c.get("status") == "superseded":
            continue
        a = _a(c)
        found.append({"id": cid, "version": a.get("version"), "status": a.get("status") or "draft", "kind": a.get("kind"), "schema_url": a.get("schema_url")})
    return sorted(found, key=lambda c: (str(c["version"]), c["id"]))


def _frozen(contracts):
    return next((c for c in contracts if c["status"] == "frozen"), None)


# ---- the spec ----

def spec(graph, component_id, at=None):
    nodes, out, inc = _index(graph)
    n = nodes.get(component_id)
    if n is None:
        raise FactoryError("the graph holds no %s" % component_id)
    if n.get("type") != "Component":
        raise FactoryError("%s is a %s, not a Component: a spec is a component's" % (component_id, n.get("type")))
    a = _a(n)
    doc = {"schema_version": SCHEMA_VERSION,
           "component": {"id": component_id, "label": n.get("label") or component_id, "calm_id": a.get("calm_id"), "calm_type": a.get("calm_type"), "summary": n.get("summary") or ""}}
    contexts = [c for c in inc.get((component_id, "deployed_as"), []) if nodes.get(c, {}).get("type") == "BoundedContext"]
    if contexts:
        bc = nodes[contexts[0]]
        doc["context"] = {"id": contexts[0], "label": bc.get("label") or contexts[0], "readiness": _a(bc).get("readiness") or "draft"}
        doc["use_cases"] = [{"id": u, "label": nodes[u].get("label") or u} for u in inc.get((contexts[0], "part_of"), []) if nodes.get(u, {}).get("type") == "UseCase"]
    else:
        doc["context"] = None
        doc["use_cases"] = []

    def interfaces(rel):
        items = []
        for iid in sorted(set(out.get((component_id, rel), []))):
            i = nodes.get(iid)
            if i is None or i.get("type") != "Interface":
                continue
            items.append({"interface": iid, "label": i.get("label") or iid, "url": _a(i).get("url"), "contracts": _contracts(nodes, inc, iid)})
        return items
    doc["exposes"] = interfaces("exposes")
    doc["consumes"] = interfaces("consumes")
    requirements = []
    for rid in out.get((component_id, "satisfies"), []):
        r = nodes.get(rid)
        if r is None:
            continue
        measured = None
        evidence = sorted((nodes[e] for e in inc.get((rid, "measurement_of"), []) if e in nodes), key=lambda e: _a(e).get("observed_on") or "", reverse=True)
        if evidence:
            measured = {"value": _a(evidence[0]).get("value"), "observed_on": _a(evidence[0]).get("observed_on")}
        requirements.append({"id": rid, "label": r.get("label") or rid, "metric": _a(r).get("metric"), "budget": _a(r).get("budget"), "measured": measured})
    doc["requirements"] = requirements
    decisions = []
    for rel in ("governs", "about"):
        for did in inc.get((component_id, rel), []):
            d = nodes.get(did)
            if d is not None and d.get("type") == "Decision" and all(x["id"] != did for x in decisions):
                decisions.append({"id": did, "label": d.get("label") or did, "status": _a(d).get("status") or d.get("status")})
    doc["decisions"] = decisions
    relationships = [(rid, "out") for rid in inc.get((component_id, "connects_from"), [])] + [(rid, "in") for rid in inc.get((component_id, "connects_to"), [])]
    controls = []
    for cid in inc.get((component_id, "safeguards"), []):
        controls.append({"id": cid, "label": nodes.get(cid, {}).get("label") or cid, "requirement_url": _a(nodes.get(cid)).get("requirement_url"), "on": component_id})
    for rid, _d in relationships:
        for cid in inc.get((rid, "safeguards"), []):
            controls.append({"id": cid, "label": nodes.get(cid, {}).get("label") or cid, "requirement_url": _a(nodes.get(cid)).get("requirement_url"), "on": rid})
    doc["controls"] = controls
    connections = []
    for rid, direction in relationships:
        r = nodes.get(rid)
        if r is None:
            continue
        other_rel = "connects_to" if direction == "out" else "connects_from"
        for other in [x for x in out.get((rid, other_rel), []) if x != component_id] or [None]:
            item = {"relationship": rid, "label": r.get("label") or rid, "kind": _a(r).get("kind"), "protocol": _a(r).get("protocol"), "direction": direction}
            item["to" if direction == "out" else "from"] = other
            connections.append(item)
    doc["connections"] = connections
    modules = []
    for mid in out.get((component_id, "implemented_by"), []):
        m = nodes.get(mid)
        if m is None or m.get("type") != "CodeModule":
            continue
        commits = sorted((nodes[c] for c in inc.get((mid, "touches"), []) if c in nodes), key=lambda c: _a(c).get("committed_on") or "", reverse=True)
        last = {"sha": _a(commits[0]).get("sha"), "committed_on": _a(commits[0]).get("committed_on"), "author": _a(commits[0]).get("author")} if commits else None
        modules.append({"id": mid, "path": _a(m).get("path") or m.get("label"), "language": _a(m).get("language"), "last_commit": last})
    doc["modules"] = sorted(modules, key=lambda m: m["path"] or "")
    doc["open_change_proposals"] = [{"id": pid, "label": nodes[pid].get("label") or pid} for pid in inc.get((component_id, "proposes_change_to"), [])
                                    if pid in nodes and (_a(nodes[pid]).get("status") or "proposed") == "proposed"]
    doc["generated"] = {"by": "oto factory spec", "at": at or datetime.date.today().isoformat()}
    doc["generated"]["hash"] = spec_hash(doc)
    return doc


def spec_hash(doc):
    body = dict(doc)
    body["generated"] = {k: v for k, v in (doc.get("generated") or {}).items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def check_spec(doc):
    """What is wrong with a spec's shape, in words; [] when it is a spec."""
    problems = []
    if not isinstance(doc, dict):
        return ["a spec is a JSON object"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is %r; this engine writes %d" % (doc.get("schema_version"), SCHEMA_VERSION))
    component = doc.get("component")
    if not isinstance(component, dict) or not component.get("id") or not component.get("label"):
        problems.append("component is {id, label, calm_id, calm_type, summary}")
    if doc.get("context") is not None and not (isinstance(doc.get("context"), dict) and doc["context"].get("id")):
        problems.append("context is null or {id, label, readiness}")
    for key in LISTS:
        if not isinstance(doc.get(key), list):
            problems.append("%s is a list" % key)
    for item in doc.get("exposes") or [] + (doc.get("consumes") or []):
        if not isinstance(item, dict) or not item.get("interface") or not isinstance(item.get("contracts"), list):
            problems.append("an exposes or consumes item is {interface, label, url, contracts: [...]}")
            break
    generated = doc.get("generated")
    if not isinstance(generated, dict) or generated.get("by") != "oto factory spec" or not generated.get("hash"):
        problems.append("generated is {by: oto factory spec, at, hash}")
    return problems


def verify_spec(doc):
    """[] when the shape holds and the hash is the content's; the problems otherwise."""
    problems = check_spec(doc)
    if problems:
        return problems
    if doc["generated"]["hash"] != spec_hash(doc):
        return ["the spec was edited by hand since `oto factory spec` wrote it: its hash is not its content's. Regenerate it: oto factory spec %s --out <file>"
                % (doc.get("component") or {}).get("id", "<component>")]
    return []


# ---- the plan ----

def components_for(graph, mode="ready", context=None):
    """The component ids a plan is for, and the contexts they come from."""
    nodes, out, inc = _index(graph)
    if mode == "all":
        return sorted(n["id"] for n in nodes.values() if n.get("type") == "Component" and n.get("status") != "superseded" and _a(n).get("calm_id")), []
    contexts = []
    if context:
        if context not in nodes or nodes[context].get("type") != "BoundedContext":
            raise FactoryError("the graph holds no BoundedContext %s" % context)
        contexts = [context]
    else:
        contexts = sorted(n["id"] for n in nodes.values() if n.get("type") == "BoundedContext" and n.get("status") != "superseded"
                          and (_a(n).get("readiness") or "draft") in ("ready", "built"))
    found = []
    for bc in contexts:
        for cid in out.get((bc, "deployed_as"), []):
            if nodes.get(cid, {}).get("type") == "Component" and cid not in found:
                found.append(cid)
    return sorted(found), contexts


def plan(graph, component_ids):
    """{"components", "groups", "edges", "unplanned"}: the order from contract dependencies."""
    nodes, out, inc = _index(graph)
    ids = [c for c in component_ids if c in nodes]
    members = set(ids)
    edges = []
    for consumer in ids:
        for iid in out.get((consumer, "consumes"), []):
            for provider in inc.get((iid, "exposes"), []):
                if provider not in members or provider == consumer:
                    continue
                contracts = _contracts(nodes, inc, iid)
                frozen = _frozen(contracts)
                first = contracts[0] if contracts else None
                edges.append({"consumer": consumer, "provider": provider, "via": iid, "contract": (frozen or first or {}).get("id"),
                              "status": (frozen or first or {}).get("status"), "parallel": frozen is not None})
        for provider in out.get((consumer, "depends_on"), []):
            if provider in members and provider != consumer and not any(e["consumer"] == consumer and e["provider"] == provider for e in edges):
                edges.append({"consumer": consumer, "provider": provider, "via": None, "contract": None, "status": None, "parallel": False})
    waits = {c: set() for c in ids}
    for e in edges:
        if not e["parallel"]:
            waits[e["consumer"]].add(e["provider"])
    groups, placed = [], set()
    while len(placed) < len(ids):
        level = sorted(c for c in ids if c not in placed and waits[c] <= placed)
        if not level:
            break
        groups.append(level)
        placed |= set(level)
    unplanned = [{"id": c, "why": "in a cycle of draft dependencies with %s: freeze a contract between them, or build one first by hand"
                  % ", ".join(sorted(p for p in waits[c] if p not in placed))} for c in ids if c not in placed]
    return {"components": ids, "groups": groups, "edges": edges, "unplanned": unplanned}


def render_plan(result, nodes_by_id=None):
    label = lambda cid: (nodes_by_id or {}).get(cid, {}).get("label") or cid  # noqa: E731
    short = lambda cid: cid.split(".", 1)[1] if "." in cid else cid  # noqa: E731
    L = ["%d build(s) in %d group(s)" % (len(result["components"]) - len(result["unplanned"]), len(result["groups"]))]
    for n, group in enumerate(result["groups"], 1):
        L.append("%sgroup %d (%s): %s" % ("then " if n > 1 else "", n, "parallel" if len(group) > 1 else "one build", ", ".join(sorted(label(c) for c in group))))
    for e in result["edges"]:
        via = " via %s (%s)" % (e["via"], "%s %s" % (e["contract"], e["status"]) if e["contract"] else "no contract") if e["via"] else " (depends on it, no interface between)"
        L.append("  %s -> %s%s: %s" % (short(e["consumer"]), short(e["provider"]), via, "parallel" if e["parallel"] else "waits"))
    for u in result["unplanned"]:
        L.append("  unplanned: %s %s" % (label(u["id"]), u["why"]))
    return "\n".join(L) + "\n"
