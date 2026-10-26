# -*- coding: utf-8 -*-
"""The factory's inputs, read from the graph (roadmap Epic I). This release: the spec as a projection
(I3) and the plan from contract dependencies (I5).

    oto factory spec <component> [--out <file>]        # the component's spec, as the graph says it
    oto factory spec --check <file>                    # the shape holds and nobody edited it by hand
    oto factory plan [--all | --context <id>] [--json] [--out <file>]
    oto factory scope <component> [--cap N] [--allow <path>]... [--read-only <path>]... [--out .factory/run.json]
    oto factory run start --plan <plan.json> --at <date> [--id <run-id>] [--runs <dir>]
    oto factory run record --run <dir> --component <id> --iteration N --verdict pending|pass|fail|escalated [--gap ...] --at <when>
    oto factory run sync --run <dir> --events .factory/events.jsonl
    oto factory run status | replay --run <dir> [--component <id>]
    oto factory run promote --run <dir> --component <id> --commit <sha> --at <date> --into <main project>
    oto factory criteria --context <id> | --component <id> --out <dir>
    oto factory deviate --run <dir> --component <id> --about <node> --observed "..." --proposes "..." --at <date> --into <main project>

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

A scope is the run snapshot the factory plugin's hooks read (`factory/`, roadmap J2): the
component's write scope is the modules the code map says implement it (plus `--allow`), its
read-only paths are `contracts/` (plus `--read-only`), with the iteration cap and the hash of the
spec the run builds against. Epic E replaces the file with a signed policy snapshot.

A run is a graph of its own (I8, J4): one OTO project per run under `--runs`, on the `factory-run`
ontology, written by the engine and never by hand or by a model. `start` records the plan instance
and a Build per component; the loop hook appends its decisions to `.factory/events.jsonl` and
`sync` reads them in, each once; `record` writes an iteration by hand; `status` and `replay` read
the run back. Every write is in the run project's audit log. Only results are promoted: `promote`
writes, for a passed build, a proposal into the main graph (the run as a document, the evaluator's
verdict as evidence of the component, the commit that touches its modules) that goes through the
gates like any other change; run state stays in the run graph.

Criteria (I6) are drawn from the graph for a bounded context (or the context a component runs as):
each scenario of its use cases as given, when, then; each business rule constraining its elements;
each policy from outside that applies to it; each budget of the component it runs as; each control
on that component or its connections. `criteria.md`, `criteria.json` and a pytest skeleton, every
criterion tracing to the nodes it came from, reviewed by a person before anything builds on it.

A deviation (I7, H5) is what a runner or an evaluator found impossible as specified: `deviate`
records it in the main graph as a ChangeProposal prompted by the Evidence of what was observed,
about the node it would change, with the siblings reached through contract edges named before the
build continues, and fails the run's build until a person decides. A measurement (H6) is in
arch.py: `oto arch measure`.
"""
import datetime
import hashlib
import json
import os
import re

from .project import ProjectError

SCHEMA_VERSION = 1
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
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


# ---- the run snapshot ----

def scope(graph, component_id, cap=5, allow=(), read_only=(), at=None):
    nodes, out, inc = _index(graph)
    n = nodes.get(component_id)
    if n is None:
        raise FactoryError("the graph holds no %s" % component_id)
    if n.get("type") != "Component":
        raise FactoryError("%s is a %s, not a Component: a run builds a component" % (component_id, n.get("type")))
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        raise FactoryError("--cap is the iteration cap, a whole number from 1")
    if cap < 1:
        raise FactoryError("--cap is the iteration cap, a whole number from 1: a loop with no cap runs forever")
    modules = []
    for mid in out.get((component_id, "implemented_by"), []):
        m = nodes.get(mid)
        if m is not None and m.get("type") == "CodeModule" and _a(m).get("path"):
            modules.append(_a(m)["path"].strip("/"))
    write_scope = sorted(set(modules))
    for extra in allow or ():
        extra = str(extra).strip().strip("/")
        if extra and extra not in write_scope:
            write_scope.append(extra)
    if not write_scope:
        raise FactoryError("no module implements %s: the code map names none (oto arch map maps the repository), and --allow <path> names a scope by hand" % component_id)
    paths = ["contracts"]
    for extra in read_only or ():
        extra = str(extra).strip().strip("/")
        if extra and extra not in paths:
            paths.append(extra)
    return {"component": component_id, "label": n.get("label") or component_id, "write_scope": write_scope, "read_only": paths, "cap": cap, "iteration": 0,
            "spec_hash": spec(graph, component_id, at=at)["generated"]["hash"],
            "generated": {"by": "oto factory scope", "at": at or datetime.date.today().isoformat()}}


# ---- the run graph ----

RUN_PRINCIPAL = "oto factory"
VERDICTS = ("pending", "pass", "fail", "escalated")
TEST_RESULTS = ("pass", "fail", "unknown")
COST_NOTE = "not recorded by the hooks; the traces of Epic F hold it"


def _slug_of(component_id):
    from .data import _slug
    return _slug(component_id.split(".", 1)[1] if "." in component_id else component_id)


def _run_project(run_dir):
    from .project import Project, ProjectError
    if not run_dir or not os.path.isdir(run_dir):
        raise FactoryError("no such run: %s (oto factory run start makes one)" % run_dir)
    project = Project.standard(run_dir)
    try:
        config = project.config()
    except ProjectError as exc:
        raise FactoryError("%s is not a run project: %s" % (run_dir, exc))
    if (config.get("ontology") or {}).get("name") != "factory-run":
        raise FactoryError("%s is not a run project: its ontology is %r, not factory-run" % (run_dir, (config.get("ontology") or {}).get("name")))
    return project


def _run_node(graph):
    runs = [n for n in graph.get("nodes") or [] if n.get("type") == "Run"]
    if not runs:
        raise FactoryError("the run project holds no Run")
    return runs[0]


def _record(project, nodes, edges, action, detail, touched=None):
    """Merge nodes (by id: new ones appended, existing ones' attributes updated) and edges (each
    once) into the run graph, and append the audit record. The engine's own record, no gates."""
    from . import audit as _audit
    from .curate import session as _session
    graph = _session.live(project)
    by_id = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    for n in nodes:
        if n["id"] in by_id:
            by_id[n["id"]].setdefault("attributes", {}).update(n.get("attributes") or {})
            if n.get("summary"):
                by_id[n["id"]]["summary"] = n["summary"]
        else:
            graph.setdefault("nodes", []).append(n)
            by_id[n["id"]] = n
    seen = {(e.get("from"), e.get("rel"), e.get("to")) for e in graph.get("edges") or []}
    for e in edges:
        if (e["from"], e["rel"], e["to"]) not in seen:
            graph.setdefault("edges", []).append(e)
            seen.add((e["from"], e["rel"], e["to"]))
    _session._write(project.graph_path, graph)
    _audit.append(project, action, RUN_PRINCIPAL, touched if touched is not None else [n["id"] for n in nodes], "applied", detail=detail)
    return graph


def _node(nid, kind, label, summary, when, **attributes):
    """A node of the run graph, dated `when` (a date, or a date and time whose date is taken)."""
    return {"id": nid, "type": kind, "label": label, "summary": summary, "attributes": attributes, "aliases": [], "tags": [],
            "as_of": when[:10], "valid_from": when[:10], "source_doc": "run", "source_type": "observation", "status": "current", "sources": ["run"]}


def run_start(plan_doc, at, run_id=None, runs_dir=".factory/runs"):
    """Create the run project from a plan. Returns {"id", "dir", "builds", "groups"}."""
    from .scaffold import init as _init
    import contextlib
    import io
    if not at or not ISO_DATE.match(str(at)):
        raise FactoryError("--at YYYY-MM-DD is required: the date the run started is never defaulted")
    groups = plan_doc.get("groups") if isinstance(plan_doc, dict) else None
    if not isinstance(groups, list) or not any(groups):
        raise FactoryError("the plan holds no groups: `oto factory plan --json` writes one")
    labels = plan_doc.get("labels") or {}
    run_id = (run_id or "").strip() or "r-%s" % datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(runs_dir, run_id)
    if os.path.exists(run_dir):
        raise FactoryError("run %s exists at %s: a run is a partition of its own, never overwritten; pick another --id" % (run_id, run_dir))
    os.makedirs(runs_dir, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        _init(run_dir, slug="run-%s" % run_id, name="Factory run %s" % run_id, ontology="factory-run", empty=True)
    project = _run_project(run_dir)
    run_node_id = "run.%s" % run_id
    nodes = [_node(run_node_id, "Run", "Run %s" % run_id, "A factory run started on %s from a plan of %d group(s)." % (at, len(groups)), at,
                   started_on=at, state="running", plan=json.dumps({"groups": groups, "edges": plan_doc.get("edges") or []}, ensure_ascii=False))]
    edges = []
    for n, group in enumerate(groups, 1):
        for cid in group:
            bid = "build.%s-%s" % (run_id, _slug_of(cid))
            nodes.append(_node(bid, "Build", labels.get(cid) or _slug_of(cid), "The build of %s in group %d." % (cid, n), at, component=cid, group=n, state="planned", iterations=0))
            edges.append({"from": bid, "rel": "build_of", "to": run_node_id})
    _record(project, nodes, edges, "factory run start", "run %s from a plan of %d group(s), %d build(s)" % (run_id, len(groups), len(nodes) - 1))
    return {"id": run_id, "dir": run_dir, "builds": len(nodes) - 1, "groups": len(groups)}


def _build_for(graph, run_id, component):
    bid = "build.%s-%s" % (run_id, _slug_of(component))
    for n in graph.get("nodes") or []:
        if n.get("id") == bid and n.get("type") == "Build":
            return n
    raise FactoryError("run %s has no build of %s: it is not in the plan" % (run_id, component))


def run_record(run_dir, component, iteration, verdict, gaps=(), at=None, tests=None):
    """One iteration of a build: recorded once, the order a fact; `tests` is what the tests said beside
    the verdict (pass, fail, unknown), so a disagreement is a fact of the run (J6). Returns {"build", "iteration", "state"}."""
    from .curate import session as _session
    project = _run_project(run_dir)
    graph = _session.live(project)
    run = _run_node(graph)
    run_id = run["id"].split(".", 1)[1]
    try:
        number = int(iteration)
    except (TypeError, ValueError):
        raise FactoryError("--iteration is the iteration's number, from 1")
    if number < 1:
        raise FactoryError("--iteration is the iteration's number, from 1")
    verdict = (verdict or "").strip().lower()
    if verdict not in VERDICTS:
        raise FactoryError("--verdict is one of %s, not %r" % (", ".join(VERDICTS), verdict))
    tests = (tests or "unknown").strip().lower()
    if tests not in TEST_RESULTS:
        raise FactoryError("--tests is one of %s, not %r" % (", ".join(TEST_RESULTS), tests))
    at = (at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")).strip()
    build = _build_for(graph, run_id, component)
    iid = "iteration.%s-%s-%d" % (run_id, _slug_of(component), number)
    if any(n.get("id") == iid for n in graph.get("nodes") or []):
        raise FactoryError("iteration %d of %s is recorded in run %s already; a run is kept in full, never rewritten" % (number, component, run_id))
    previous = sorted((n for n in graph.get("nodes") or [] if n.get("type") == "Iteration" and n["id"].startswith("iteration.%s-%s-" % (run_id, _slug_of(component)))),
                      key=lambda n: (n.get("attributes") or {}).get("number") or 0)
    node = _node(iid, "Iteration", "%s, iteration %d" % (build.get("label") or component, number),
                 {"pending": "No verdict yet: sent to the evaluator.", "pass": "The evaluator passed it.", "fail": "The evaluator failed the previous attempt.",
                  "escalated": "The iteration cap was reached without a pass."}[verdict], at, number=number, verdict=verdict, gaps=[str(g) for g in gaps or []], at=at, tests=tests)
    edges = [{"from": iid, "rel": "iteration_of", "to": build["id"]}]
    if previous:
        edges.append({"from": iid, "rel": "follows", "to": previous[-1]["id"]})
    state = {"pending": "building", "fail": "building", "pass": "passed", "escalated": "escalated"}[verdict]
    build_update = _node(build["id"], "Build", build.get("label"), build.get("summary"), at, state=state, iterations=max(int((build.get("attributes") or {}).get("iterations") or 0), number))
    build_update["summary"] = None
    _record(project, [node, build_update], edges, "factory run record", "%s iteration %d: %s%s" % (component, number, verdict, " (%s)" % "; ".join(gaps) if gaps else ""),
            touched=[iid, build["id"]])
    _refresh_run_state(project)
    return {"build": build["id"], "iteration": iid, "state": state}


def _refresh_run_state(project):
    from .curate import session as _session
    graph = _session.live(project)
    run = _run_node(graph)
    builds = [n for n in graph.get("nodes") or [] if n.get("type") == "Build"]
    states = {(b.get("attributes") or {}).get("state") for b in builds}
    new = "escalated" if "escalated" in states or "failed" in states else ("done" if builds and states <= {"passed"} else "running")
    if (run.get("attributes") or {}).get("state") != new:
        run.setdefault("attributes", {})["state"] = new
        _session._write(project.graph_path, graph)


def run_set_build(run_dir, component, state, iterations=None, commit=None, at=None, detail=None):
    from .curate import session as _session
    project = _run_project(run_dir)
    graph = _session.live(project)
    run = _run_node(graph)
    run_id = run["id"].split(".", 1)[1]
    build = _build_for(graph, run_id, component)
    attributes = {"state": state}
    if iterations is not None:
        attributes["iterations"] = max(int((build.get("attributes") or {}).get("iterations") or 0), int(iterations))
    if commit:
        attributes["commit"] = commit
    update = _node(build["id"], "Build", build.get("label"), build.get("summary"), (at or datetime.date.today().isoformat()), **attributes)
    update["summary"] = None
    _record(project, [update], [], "factory run record", detail or "%s: %s" % (component, state), touched=[build["id"]])
    _refresh_run_state(project)
    return build["id"]


def run_sync(run_dir, events_path):
    """Read the loop hook's events into the run graph, each once. Returns {"events", "new", "iterations", "passed", "escalated", "skipped"}."""
    from .curate import session as _session
    if not os.path.isfile(events_path):
        raise FactoryError("no such events file: %s (the loop hook writes .factory/events.jsonl beside run.json)" % events_path)
    project = _run_project(run_dir)
    run_id = _run_node(_session.live(project))["id"].split(".", 1)[1]
    counts = {"events": 0, "new": 0, "iterations": 0, "passed": 0, "escalated": 0, "skipped": 0}
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                counts["skipped"] += 1
                continue
            counts["events"] += 1
            if e.get("run") and e["run"] != run_id:
                counts["skipped"] += 1
                continue
            component = e.get("component")
            kind = e.get("event")
            graph = _session.live(project)
            try:
                build = _build_for(graph, run_id, component or "")
            except FactoryError:
                counts["skipped"] += 1
                continue
            state = (build.get("attributes") or {}).get("state")
            if kind == "iteration":
                iid = "iteration.%s-%s-%s" % (run_id, _slug_of(component), e.get("iteration"))
                if any(n.get("id") == iid for n in graph.get("nodes") or []):
                    continue
                run_record(run_dir, component, e.get("iteration"), e.get("verdict") or "pending", e.get("gaps") or [], at=e.get("at"), tests=e.get("tests"))
                counts["new"] += 1
                counts["iterations"] += 1
            elif kind == "pass":
                if state == "passed":
                    continue
                run_set_build(run_dir, component, "passed", iterations=e.get("iteration") or 0, at=(e.get("at") or "")[:10] or None, detail="%s passed (event)" % component)
                counts["new"] += 1
                counts["passed"] += 1
            elif kind == "escalated":
                if state == "escalated":
                    continue
                run_set_build(run_dir, component, "escalated", iterations=e.get("iteration") or 0, at=(e.get("at") or "")[:10] or None, detail="%s escalated at the cap (event)" % component)
                counts["new"] += 1
                counts["escalated"] += 1
            else:
                counts["skipped"] += 1
    return counts


def run_status(run_dir):
    from .curate import session as _session
    project = _run_project(run_dir)
    graph = _session.live(project)
    run = _run_node(graph)
    builds = sorted((n for n in graph.get("nodes") or [] if n.get("type") == "Build"), key=lambda b: ((b.get("attributes") or {}).get("group") or 0, b.get("label") or ""))
    L = ["%s (%s): %d build(s), started %s" % (run["id"], (run.get("attributes") or {}).get("state"), len(builds), (run.get("attributes") or {}).get("started_on"))]
    for b in builds:
        a = b.get("attributes") or {}
        L.append("  group %s: %s (%s): %s, %d iteration(s)%s" % (a.get("group"), b.get("label"), a.get("component"), a.get("state"), int(a.get("iterations") or 0),
                                                              ", commit %s" % a["commit"] if a.get("commit") else ""))
    return "\n".join(L) + "\n"


def run_replay(run_dir, component):
    from .curate import session as _session
    project = _run_project(run_dir)
    graph = _session.live(project)
    run_id = _run_node(graph)["id"].split(".", 1)[1]
    build = _build_for(graph, run_id, component)
    iterations = sorted((n for n in graph.get("nodes") or [] if n.get("type") == "Iteration" and n["id"].startswith("iteration.%s-%s-" % (run_id, _slug_of(component)))),
                        key=lambda n: (n.get("attributes") or {}).get("number") or 0)
    L = ["%s (%s): %s after %d iteration(s)" % (build.get("label"), component, (build.get("attributes") or {}).get("state"), len(iterations))]
    for i in iterations:
        a = i.get("attributes") or {}
        L.append("  iteration %s: %s%s (%s)" % (a.get("number"), a.get("verdict"), " — " + "; ".join(a.get("gaps") or []) if a.get("gaps") else "", a.get("at")))
    return "\n".join(L) + "\n"


def _run_dirs(runs_dir):
    """The run projects under a directory, in name order."""
    if not os.path.isdir(runs_dir):
        raise FactoryError("no such runs directory: %s" % runs_dir)
    found = sorted(os.path.join(runs_dir, d) for d in os.listdir(runs_dir) if os.path.isfile(os.path.join(runs_dir, d, "project.config.json")))
    if not found:
        raise FactoryError("no run project under %s (oto factory run start makes one per run)" % runs_dir)
    return found


def run_metrics(run_dir=None, runs_dir=None):
    """The factory's metrics as queries over the run graph (roadmap J6), for one run or every run under
    a directory: iterations to pass (mean, min, max over the passed builds), the escalation rate over
    the builds that ended, and the iterations where the evaluator and the tests disagreed (FR4: tests
    passed, verdict fail; FR5: tests failed, verdict pass). Cost is not the hooks' to know and is said
    so, never guessed. Returns a dict."""
    from .curate import session as _session
    dirs = [run_dir] if run_dir else _run_dirs(runs_dir or os.path.join(".factory", "runs"))
    m = {"runs": 0, "run_ids": [], "builds": 0, "passed": 0, "escalated": 0, "failed": 0, "building": 0, "planned": 0, "iterations": 0,
         "iterations_to_pass": {"mean": None, "min": None, "max": None, "builds": 0}, "escalation_rate": None,
         "disagreements": 0, "disagreement_list": [], "cost": COST_NOTE}
    to_pass = []
    for d in dirs:
        project = _run_project(d)
        graph = _session.live(project)
        run = _run_node(graph)
        m["runs"] += 1
        m["run_ids"].append(run["id"])
        nodes = graph.get("nodes") or []
        builds = {b["id"]: b for b in nodes if b.get("type") == "Build"}
        build_of = {}
        for e in graph.get("edges") or []:
            if e.get("rel") == "iteration_of":
                build_of[e["from"]] = e["to"]
        for b in builds.values():
            a = b.get("attributes") or {}
            m["builds"] += 1
            state = a.get("state") or "planned"
            if state in ("passed", "escalated", "failed", "building", "planned"):
                m[state if state != "passed" else "passed"] += 1
            if state == "passed":
                to_pass.append(max(int(a.get("iterations") or 0), 1))
        for i in sorted((n for n in nodes if n.get("type") == "Iteration"), key=lambda n: ((n.get("attributes") or {}).get("at") or "", n["id"])):
            a = i.get("attributes") or {}
            m["iterations"] += 1
            tests, verdict = a.get("tests") or "unknown", a.get("verdict")
            if (tests, verdict) in (("pass", "fail"), ("fail", "pass")):
                b = builds.get(build_of.get(i["id"]), {})
                m["disagreements"] += 1
                m["disagreement_list"].append({"run": run["id"], "build": b.get("id"), "component": (b.get("attributes") or {}).get("component"), "iteration": a.get("number"),
                                               "tests": tests, "verdict": verdict, "gaps": list(a.get("gaps") or []), "question": "FR4" if tests == "pass" else "FR5"})
    if to_pass:
        m["iterations_to_pass"] = {"mean": sum(to_pass) / len(to_pass), "min": min(to_pass), "max": max(to_pass), "builds": len(to_pass)}
    ended = m["passed"] + m["escalated"] + m["failed"]
    if ended:
        m["escalation_rate"] = m["escalated"] / ended
    return m


def render_metrics(m):
    L = ["%d run(s) %s: %d build(s), %d passed, %d escalated, %d failed, %d building, %d planned; %d iteration(s)" % (
        m["runs"], ", ".join(m["run_ids"]), m["builds"], m["passed"], m["escalated"], m["failed"], m["building"], m["planned"], m["iterations"])]
    itp = m["iterations_to_pass"]
    L.append("  iterations to pass: %s" % ("mean %.2f, min %d, max %d over %d passed build(s)" % (itp["mean"], itp["min"], itp["max"], itp["builds"]) if itp["builds"] else "no build passed yet"))
    L.append("  escalation rate: %s" % ("%.0f%% of %d ended build(s)" % (m["escalation_rate"] * 100, m["passed"] + m["escalated"] + m["failed"]) if m["escalation_rate"] is not None else "no build ended yet"))
    L.append("  evaluator and tests disagree: %d iteration(s)%s" % (m["disagreements"], "" if m["disagreements"] else " (FR4, FR5)"))
    for d in m["disagreement_list"]:
        L.append("    %s iteration %s: tests %s, verdict %s (%s)%s" % (d["component"], d["iteration"], d["tests"], d["verdict"], d["question"], " — " + "; ".join(d["gaps"]) if d["gaps"] else ""))
    L.append("  cost: %s" % m["cost"])
    return "\n".join(L) + "\n"


def run_promote(run_dir, component, commit, at, into_project):
    """A passed build's verdict and commit as a proposal into the main graph. Returns {"doc", "document", "archive", "proposal", "run"}."""
    from .curate import session as _session
    if not (commit or "").strip():
        raise FactoryError("--commit is the commit the passed build is promoted with: its sha")
    if not at or not ISO_DATE.match(str(at)):
        raise FactoryError("--at YYYY-MM-DD is required: the date of the promotion is never defaulted")
    project = _run_project(run_dir)
    graph = _session.live(project)
    run = _run_node(graph)
    run_id = run["id"].split(".", 1)[1]
    build = _build_for(graph, run_id, component)
    a = build.get("attributes") or {}
    if a.get("state") != "passed":
        raise FactoryError("only a passed build is promoted: %s is %s in run %s" % (component, a.get("state"), run_id))
    main = _session.live(into_project)
    nodes_main, out, inc = _index(main)
    if component not in nodes_main:
        raise FactoryError("the main graph holds no %s" % component)
    iterations = int(a.get("iterations") or 0)
    sha = commit.strip()
    doc = "run-%s" % run_id
    slug = _slug_of(component)
    builds = sorted((n for n in graph.get("nodes") or [] if n.get("type") == "Build"), key=lambda b: ((b.get("attributes") or {}).get("group") or 0, b.get("id")))
    lines = ["# Factory run %s" % run_id, "", "Recorded by `oto factory run promote` on %s from the run graph at %s. One line per build: its state, its iterations and, "
             "for a promoted build, the commit; the run's iterations stay in the run graph." % (at, os.path.basename(os.path.abspath(run_dir))), "", "## Builds", ""]
    for b in builds:
        ba = b.get("attributes") or {}
        bslug = _slug_of(ba.get("component") or b["id"])
        line = "- %s: %s after %d iteration(s)" % (bslug, ba.get("state"), int(ba.get("iterations") or 0))
        if bslug == slug:
            line += ", commit %s" % sha
        elif ba.get("commit"):
            line += ", commit %s" % ba["commit"]
        lines.append(line)
    text = "\n".join(lines) + "\n"
    quote = "%s: passed after %d iteration(s), commit %s" % (slug, iterations, sha)
    corpus = os.path.join(into_project.layout.corpus, doc + ".md")
    archive = os.path.join(into_project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    evidence_id = "evidence.run-%s-%s" % (run_id, slug)
    commit_id = "commit.%s" % sha[:12]
    proposal = {"source_doc": doc, "as_of": at, "nodes": [
        {"id": "document.%s" % doc, "type": "Document", "label": "Factory run %s" % run_id, "summary": "The factory run %s as promoted; the date is the fact's own." % run_id,
         "attributes": {"kind": "run"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": "Factory run %s" % run_id}]},
        {"id": evidence_id, "type": "Evidence", "label": "Run %s: %s passed" % (run_id, build.get("label") or slug), "summary": "The evaluator passed the build of %s in run %s after %d iteration(s)." % (component, run_id, iterations),
         "attributes": {"kind": "review", "value": "pass after %d iteration(s)" % iterations, "observed_on": at, "source_url": "run %s" % run_id}, "valid_from": at,
         "evidence": [{"doc": doc, "where": "builds", "quote": quote}]},
        {"id": commit_id, "type": "Commit", "label": "%s factory run %s: %s" % (sha[:7], run_id, slug), "summary": "The commit the passed build of %s was promoted with." % component,
         "attributes": {"sha": sha, "committed_on": at, "author": RUN_PRINCIPAL, "message": "factory run %s: %s" % (run_id, slug)}, "valid_from": at,
         "evidence": [{"doc": doc, "where": "builds", "quote": quote}]}],
        "edges": [{"from": evidence_id, "rel": "evidence_of", "to": component}]}
    for mid in out.get((component, "implemented_by"), []):
        if nodes_main.get(mid, {}).get("type") == "CodeModule":
            proposal["edges"].append({"from": commit_id, "rel": "touches", "to": mid})
    out_dir = os.path.join(into_project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "%s-%s.json" % (doc, slug))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    run_set_build(run_dir, component, "passed", commit=sha, at=at, detail="%s promoted with commit %s" % (component, sha))
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out_path, "run": run_id, "iterations": iterations}


# ---- criteria (I6) ----

def _slug_text(text, words=5):
    from .data import _slug
    return _slug(" ".join(str(text).split()[:words]))


def criteria(graph, context_id=None, component_id=None):
    """{"context", "label", "component", "criteria": [{"id", "kind", "text", "sources", ...}]} for a bounded context."""
    nodes, out, inc = _index(graph)
    if component_id:
        c = nodes.get(component_id)
        if c is None:
            raise FactoryError("the graph holds no %s" % component_id)
        if c.get("type") != "Component":
            raise FactoryError("%s is a %s, not a Component" % (component_id, c.get("type")))
        contexts = [b for b in inc.get((component_id, "deployed_as"), []) if nodes.get(b, {}).get("type") == "BoundedContext"]
        if not contexts:
            raise FactoryError("no bounded context runs as %s (no BoundedContext deployed_as it): the criteria come from a context's use cases, rules and policies; "
                               "record the context first" % component_id)
        context_id = contexts[0]
    if not context_id:
        raise FactoryError("criteria takes --context <bounded context> or --component <component>")
    bc = nodes.get(context_id)
    if bc is None or bc.get("type") != "BoundedContext":
        raise FactoryError("the graph holds no BoundedContext %s" % context_id)
    components = [component_id] if component_id else [c for c in out.get((context_id, "deployed_as"), []) if nodes.get(c, {}).get("type") == "Component"]
    label = lambda nid: nodes.get(nid, {}).get("label") or nid  # noqa: E731
    found = []

    def add(kind, text, sources, **more):
        item = {"id": "c-%d" % (len(found) + 1), "kind": kind, "text": text, "sources": sources}
        item.update(more)
        found.append(item)
    elements = [e for e in inc.get((context_id, "part_of"), []) if e in nodes]
    for uc in [e for e in elements if nodes[e].get("type") == "UseCase"]:
        for sid in inc.get((uc, "exercises"), []):
            sc = nodes.get(sid)
            if sc is None or sc.get("type") != "Scenario":
                continue
            a = _a(sc)
            add("scenario", "Given %s, when %s, then %s." % (a.get("given") or "?", a.get("when") or "?", a.get("then") or "?"), [sid, uc],
                given=a.get("given"), when=a.get("when"), then=a.get("then"), scenario_kind=a.get("kind"))
    for comp in components:
        for rid in out.get((comp, "satisfies"), []):
            for sid in inc.get((rid, "exercises"), []):
                sc = nodes.get(sid)
                if sc is None or sc.get("type") != "Scenario" or any(sid in c["sources"] for c in found):
                    continue
                a = _a(sc)
                add("scenario", "Given %s, when %s, then %s." % (a.get("given") or "?", a.get("when") or "?", a.get("then") or "?"), [sid, rid],
                    given=a.get("given"), when=a.get("when"), then=a.get("then"), scenario_kind=a.get("kind"))
    rules = {}
    for e in elements:
        for rid in out.get((e, "constrained_by"), []):
            if nodes.get(rid, {}).get("type") == "BusinessRule":
                rules.setdefault(rid, []).append(e)
    for e in elements:
        if nodes[e].get("type") == "BusinessRule":
            rules.setdefault(e, [])
    for rid, constrained in rules.items():
        a = _a(nodes[rid])
        text = label(rid) + (": %s" % a["expression"] if a.get("expression") else "")
        add("rule", text, [rid] + constrained, rule_kind=a.get("kind"))
    policies = {}
    for pid in inc.get((context_id, "applies_to"), []):
        if nodes.get(pid, {}).get("type") == "Policy":
            policies.setdefault(pid, [])
    for rid in rules:
        for pid in inc.get((rid, "applies_to"), []):
            if nodes.get(pid, {}).get("type") == "Policy":
                policies.setdefault(pid, []).append(rid)
    for pid, through in policies.items():
        a = _a(nodes[pid])
        bits = [b for b in (a.get("kind"), a.get("authority")) if b]
        add("policy", label(pid) + (" (%s)" % ", ".join(bits) if bits else ""), [pid] + through)
    for comp in components:
        for rid in out.get((comp, "satisfies"), []):
            r = nodes.get(rid)
            if r is None or not _a(r).get("metric"):
                continue
            a = _a(r)
            add("budget", "%s within %s (%s)" % (a["metric"], a.get("budget") or "a budget nobody set", label(rid)), [rid, comp], metric=a["metric"], budget=a.get("budget"))
    for comp in components:
        for cid in inc.get((comp, "safeguards"), []):
            add("control", "%s%s" % (label(cid), " (%s)" % _a(nodes[cid])["requirement_url"] if _a(nodes.get(cid)).get("requirement_url") else ""), [cid, comp])
        for rid in inc.get((comp, "connects_from"), []) + inc.get((comp, "connects_to"), []):
            for cid in inc.get((rid, "safeguards"), []):
                add("control", "%s on %s%s" % (label(cid), label(rid), " (%s)" % _a(nodes[cid])["requirement_url"] if _a(nodes.get(cid)).get("requirement_url") else ""), [cid, rid, comp])
    return {"context": context_id, "label": bc.get("label") or context_id, "component": component_id, "components": components, "criteria": found}


def render_criteria(result, at):
    titles = {"scenario": "Scenarios", "rule": "Business rules", "policy": "Policies", "budget": "Budgets", "control": "Controls"}
    L = ["# Acceptance criteria of %s" % result["label"], "",
         "Drawn from the graph by `oto factory criteria` on %s for %s%s: each scenario of the context's use cases, each business rule "
         "constraining its elements, each policy from outside that applies to it, each budget of the component it runs as, each control on it. "
         "Every criterion names the nodes it came from. Review it before anything builds on it; what the graph does not say is not here."
         % (at, result["context"], " (component %s)" % result["component"] if result["component"] else ""), ""]
    for kind, title in titles.items():
        items = [c for c in result["criteria"] if c["kind"] == kind]
        if not items:
            continue
        L += ["## %s" % title, ""]
        for c in items:
            extra = ""
            if kind == "scenario" and c.get("scenario_kind"):
                extra = ", %s" % c["scenario_kind"]
            if kind == "rule" and c.get("rule_kind"):
                extra = ", %s" % c["rule_kind"]
            L.append("- %s (%s%s): %s [%s]" % (c["id"], kind, extra, c["text"], ", ".join(c["sources"])))
        L.append("")
    if not result["criteria"]:
        L += ["No criteria: the context has no scenario, rule, policy, budget or control the graph knows.", ""]
    return "\n".join(L).rstrip() + "\n"


def render_criteria_tests(result, at):
    L = ['"""Acceptance criteria of %s, drawn from the graph by `oto factory criteria` on %s; each test traces to the nodes its criterion came from. '
         'Review before building on it: a skipped test is a criterion nobody has implemented yet, not one that passes."""' % (result["label"], at),
         "import pytest", ""]
    for c in result["criteria"]:
        name = "test_%s_%s" % (c["id"].replace("-", "_"), _slug_text(c["text"]).replace("-", "_") or c["kind"])
        L += ["", '@pytest.mark.skip(reason="criterion %s not yet implemented: %s")' % (c["id"], c["text"].replace('"', "'")[:80]),
              "def %s():" % name, '    """%s (%s): %s"""' % (", ".join(c["sources"]), c["kind"], c["text"].replace('"', "'")), "    raise NotImplementedError", ""]
    if not result["criteria"]:
        L += ["", "def test_nothing_to_check_yet():", '    """The context has no criteria the graph knows."""', "    pytest.skip(\"no criteria\")", ""]
    return "\n".join(L).rstrip() + "\n"


def write_criteria(result, out_dir, at):
    from .data import _slug
    os.makedirs(out_dir, exist_ok=True)
    slug = _slug(result["label"])
    md = os.path.join(out_dir, "criteria.md")
    js = os.path.join(out_dir, "criteria.json")
    py = os.path.join(out_dir, "test_criteria_%s.py" % slug.replace("-", "_"))
    with open(md, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_criteria(result, at))
    with open(js, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(result, generated={"by": "oto factory criteria", "at": at}), f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(py, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_criteria_tests(result, at))
    return {"markdown": md, "json": js, "tests": py}


# ---- deviations (I7, H5) ----

def siblings_of(graph, about, component_id):
    """The components reached through the node a deviation is about: through a contract or an
    interface, those that consume or expose it; through a component, those at the other end of its
    relationships. Never the deviating component itself."""
    nodes, out, inc = _index(graph)
    kind = nodes.get(about, {}).get("type")
    found = []
    interfaces = []
    if kind == "Contract":
        interfaces = out.get((about, "contract_of"), [])
    elif kind == "Interface":
        interfaces = [about]
    for iid in interfaces:
        found += inc.get((iid, "consumes"), []) + inc.get((iid, "exposes"), [])
    if kind in ("Component", "System", "DataStore"):
        for rid in inc.get((about, "connects_from"), []) + inc.get((about, "connects_to"), []):
            found += [x for x in out.get((rid, "connects_to"), []) + out.get((rid, "connects_from"), []) if x != about]
    out_ids = []
    for cid in found:
        if cid != component_id and nodes.get(cid, {}).get("type") == "Component" and cid not in out_ids:
            out_ids.append(cid)
    return out_ids


def deviate(run_dir, component, about, observed, proposes, at, into_project):
    """Record a deviation: the evidence, the change proposal, the siblings; fail the run's build.
    Returns {"id", "doc", "document", "archive", "proposal", "siblings"}."""
    from .curate import session as _session
    if not (observed or "").strip():
        raise FactoryError("--observed says what was found impossible as specified, in a sentence")
    if not (proposes or "").strip():
        raise FactoryError("--proposes says the change proposed, in a sentence")
    if not at or not ISO_DATE.match(str(at)):
        raise FactoryError("--at YYYY-MM-DD is required: the date of the deviation is never defaulted")
    project = _run_project(run_dir)
    graph = _session.live(project)
    run_id = _run_node(graph)["id"].split(".", 1)[1]
    build = _build_for(graph, run_id, component)
    main = _session.live(into_project)
    nodes, out, inc = _index(main)
    if component not in nodes:
        raise FactoryError("the main graph holds no %s" % component)
    if about not in nodes:
        raise FactoryError("the main graph holds no %s: a deviation is about a node the architecture holds" % about)
    label = lambda nid: nodes.get(nid, {}).get("label") or nid  # noqa: E731
    corpus = into_project.layout.corpus
    n = 1
    while os.path.exists(os.path.join(corpus, "deviation-%s-%d.md" % (run_id, n))):
        n += 1
    dev_id = "%s-%d" % (run_id, n)
    doc = "deviation-%s" % dev_id
    siblings = siblings_of(main, about, component)
    observed, proposes = observed.strip(), proposes.strip()
    lines = ["# Deviation %s" % dev_id, "", "Recorded by `oto factory deviate` on %s from run %s, while building %s (%s). What the runner or the evaluator found "
             "impossible as specified, the change it proposes, the node it is about, and the siblings reached through it, so they are checked before the build continues."
             % (at, run_id, label(component), component), "", "## Observed", "", observed, "", "## Proposes", "", proposes, "", "## About", "",
             "- %s (%s)" % (label(about), about), "", "## Siblings reached through it", ""]
    lines += ["- %s (%s)" % (label(x), x) for x in siblings] or ["- none"]
    text = "\n".join(lines) + "\n"
    archive = os.path.join(into_project.layout.archive, doc + ".md")
    for target in (os.path.join(corpus, doc + ".md"), archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    evidence_id = "evidence.%s" % doc
    cp_id = "changeproposal.%s" % dev_id
    summary = "Raised while building %s in run %s: %s. Affected through %s: %s." % (label(component), run_id, observed, label(about),
                                                                                 ", ".join(label(x) for x in siblings) if siblings else "no sibling")
    proposal = {"source_doc": doc, "as_of": at, "nodes": [
        {"id": "document.%s" % doc, "type": "Document", "label": "Deviation %s" % dev_id, "summary": "A deviation recorded from run %s; the date is the fact's own." % run_id,
         "attributes": {"kind": "run"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": "Deviation %s" % dev_id}]},
        {"id": evidence_id, "type": "Evidence", "label": observed, "summary": "Observed while building %s in run %s (deviation %s)." % (label(component), run_id, dev_id),
         "attributes": {"kind": "review", "value": observed, "observed_on": at, "source_url": "run %s" % run_id}, "valid_from": at,
         "evidence": [{"doc": doc, "where": "observed", "quote": observed}]},
        {"id": cp_id, "type": "ChangeProposal", "label": "CP %s: %s" % (dev_id, proposes), "summary": summary, "attributes": {"status": "proposed"}, "valid_from": at,
         "evidence": [{"doc": doc, "where": "proposes", "quote": proposes}]}],
        "edges": [{"from": cp_id, "rel": "prompted_by", "to": evidence_id}, {"from": cp_id, "rel": "proposes_change_to", "to": about},
                  {"from": evidence_id, "rel": "evidence_of", "to": component}] + ([{"from": evidence_id, "rel": "evidence_of", "to": about}] if about != component else [])}
    out_dir = os.path.join(into_project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, doc + ".json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    run_set_build(run_dir, component, "failed", at=at, detail="%s: deviation %s about %s; a person decides" % (component, dev_id, about))
    return {"id": dev_id, "doc": doc, "document": os.path.join(corpus, doc + ".md"), "archive": archive, "proposal": out_path, "siblings": siblings,
            "build": build["id"], "cp": cp_id}


# ---- measurements (H6) ----

def measure_from(path):
    """(format, value) read from a JUnit XML report, a coverage.py XML report or a k6 summary JSON."""
    import xml.etree.ElementTree as ET
    if not os.path.isfile(path):
        raise FactoryError("no such report: %s" % path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise FactoryError("%s is not XML: %s" % (path, exc))
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if suites:
            def num(el, key):
                try:
                    return int(el.get(key) or 0)
                except ValueError:
                    return 0
            tests = sum(num(s, "tests") for s in suites)
            failures = sum(num(s, "failures") for s in suites)
            errors = sum(num(s, "errors") for s in suites)
            skipped = sum(num(s, "skipped") for s in suites)
            passed = max(tests - failures - errors - skipped, 0)
            detail = ", ".join(x for x in ("%d failed" % failures if failures else "", "%d error(s)" % errors if errors else "", "%d skipped" % skipped if skipped else "") if x)
            return "junit", "%d of %d tests passed%s" % (passed, tests, " (%s)" % detail if detail else "")
        if root.tag == "coverage" and root.get("line-rate") is not None:
            try:
                rate = float(root.get("line-rate"))
            except ValueError:
                raise FactoryError("%s: line-rate is not a number" % path)
            covered, valid = root.get("lines-covered"), root.get("lines-valid")
            detail = " (%s of %s)" % (covered, valid) if covered and valid else ""
            return "coverage", "%d %% of lines covered%s" % (round(rate * 100), detail)
        raise FactoryError("%s is XML, but neither a JUnit report (testsuite) nor a coverage.py report (coverage line-rate); the formats read are junit, coverage and k6" % path)
    try:
        data = json.loads(text)
    except ValueError:
        raise FactoryError("%s is neither XML nor JSON; the formats read are junit (XML), coverage (XML) and k6 (JSON summary)" % path)
    metrics = (data or {}).get("metrics") if isinstance(data, dict) else None
    duration = (metrics or {}).get("http_req_duration") if isinstance(metrics, dict) else None
    values = (duration or {}).get("values") if isinstance(duration, dict) else None
    if isinstance(values, dict) and values.get("p(95)") is not None:
        count = ((metrics.get("http_reqs") or {}).get("values") or {}).get("count")
        return "k6", "p95 %d ms%s" % (round(float(values["p(95)"])), " over %d requests" % int(count) if count else "")
    raise FactoryError("%s is JSON, but not a k6 summary (metrics.http_req_duration.values.p(95)); the formats read are junit, coverage and k6" % path)


def measure(project, nfr_id, at, value=None, path=None, source=None):
    """A measurement as Evidence of the requirement, cited to a document. Returns {"doc", "document", "archive", "proposal", "value", "format"}."""
    from .curate import session as _session
    from .data import _slug
    if not at or not ISO_DATE.match(str(at)):
        raise FactoryError("--at YYYY-MM-DD is required: the date of the measurement is never defaulted")
    if not (value or "").strip() and not path:
        raise FactoryError("a measurement comes from a report (--from <junit.xml|coverage.xml|k6-summary.json>) or is stated (--value \"...\")")
    graph = _session.live(project)
    nodes, out, inc = _index(graph)
    nfr = nodes.get(nfr_id)
    if nfr is None:
        raise FactoryError("the graph holds no %s" % nfr_id)
    if nfr.get("type") != "NFR":
        raise FactoryError("%s is a %s, not an NFR (a Requirement with a metric and a budget): only a requirement with a budget is measured" % (nfr_id, nfr.get("type")))
    fmt = "stated"
    if path:
        fmt, value = measure_from(path)
    value = value.strip()
    slug = _slug(nfr_id.split(".", 1)[1] if "." in nfr_id else nfr_id)
    doc = "measure-%s-%s" % (slug, at)
    a = _a(nfr)
    lines = ["# Measurement of %s" % (nfr.get("label") or nfr_id), "",
             "Recorded by `oto arch measure` on %s, %s. The measured value next to the budget, so what the requirement asks and what was observed are one line."
             % (at, "from a %s report, %s" % (fmt, os.path.basename(path)) if path else "a value stated at the prompt"), "", "## Measured", "",
             "- %s: %s, budget %s (%s)" % (nfr.get("label") or nfr_id, value, a.get("budget") or "none set", a.get("metric") or "no metric")]
    text = "\n".join(lines) + "\n"
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    evidence_id = "evidence.%s" % doc
    attributes = {"kind": "measurement", "value": value, "observed_on": at}
    if source or path:
        attributes["source_url"] = source or os.path.basename(path)
    proposal = {"source_doc": doc, "as_of": at, "nodes": [
        {"id": "document.%s" % doc, "type": "Document", "label": "Measurement of %s" % (nfr.get("label") or nfr_id), "summary": "A measurement of %s as recorded; the date is the fact's own." % nfr_id,
         "attributes": {"kind": "run"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": "Measurement of %s" % (nfr.get("label") or nfr_id)}]},
        {"id": evidence_id, "type": "Evidence", "label": "%s measured on %s" % (nfr.get("label") or nfr_id, at), "summary": "%s: %s on %s." % (a.get("metric") or nfr_id, value, at),
         "attributes": attributes, "valid_from": at, "evidence": [{"doc": doc, "where": "measured", "quote": value}]}],
        "edges": [{"from": evidence_id, "rel": "measurement_of", "to": nfr_id}]}
    for comp in inc.get((nfr_id, "satisfies"), []):
        if nodes.get(comp, {}).get("type") in ("Component", "System", "Interface"):
            proposal["edges"].append({"from": evidence_id, "rel": "evidence_of", "to": comp})
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, doc + ".json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out_path, "value": value, "format": fmt}
