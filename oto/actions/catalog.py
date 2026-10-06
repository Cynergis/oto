# -*- coding: utf-8 -*-
"""The catalog: which actions are ready, on which entities, with their inputs bound.

Works over any graph given as node and edge dicts, so the CLI reads the authored files and the
engine reads a store, and both answer the same. An action's `when` is matched with the rules'
matcher over current and intended facts; the first pattern binds the subject. Inputs are filled
from the subject's own fields only. The answer is the action as an MCP tool definition plus an
`oto` block: subject, readiness, bindings, the declared invocation, the variables the caller
must hold, and what a recorded result would assert. Nothing here invokes anything.
"""
import datetime
import json
import os

from ..reason.match import BELIEVED_OR_INTENDED, Graph, matches, today
from . import model as _model

#: A schedule as hours between runs.
INTERVALS = {"hourly": 1, "daily": 24, "weekly": 168}


def now():
    """The moment schedules are judged against: OTO_TODAY at midnight when set, else the clock."""
    pinned = (os.environ.get("OTO_TODAY") or "").strip()
    if pinned:
        return datetime.datetime.fromisoformat(pinned + "T00:00:00+00:00")
    return datetime.datetime.now(datetime.timezone.utc)


def due(action, at=None):
    """(due, reason): a read-only action with a schedule is due when it never ran, or when its
    last run is older than the schedule's interval. Anything else is never due."""
    schedule = action.get("schedule")
    if not schedule:
        return False, "no schedule"
    if not _model.read_only(action):
        return False, "not read-only: never runs unattended"
    hours = INTERVALS.get(schedule)
    if not hours:
        return False, "unknown schedule %r" % schedule
    last = action.get("_last_run") or {}
    stamp = last.get("recorded_at") or (last.get("at") + "T00:00:00+00:00" if last.get("at") else None)
    if not stamp:
        return True, "never run"
    try:
        then = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return True, "last run has no readable time"
    moment = at or now()
    age = moment - then
    if age >= datetime.timedelta(hours=hours):
        return True, "last run %s, %s ago" % (last.get("at"), "%dh" % int(age.total_seconds() // 3600))
    return False, "ran %s; next after %s" % (last.get("at"), (then + datetime.timedelta(hours=hours)).isoformat())


def definitions_from_nodes(nodes):
    """The action definitions a built graph carries: each Action node stores its file under
    `attributes.definition`, so a store served without its project still knows them."""
    out = []
    for n in nodes:
        if n.get("type") != _model.CLASS:
            continue
        attrs = n.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except ValueError:
                attrs = {}
        definition = attrs.get("definition")
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except ValueError:
                definition = None
        if isinstance(definition, dict) and definition.get("id"):
            definition = dict(definition)
            if attrs.get("last_run"):
                definition["_last_run"] = dict(attrs["last_run"], runs=attrs.get("runs"))
            out.append(definition)
    return sorted(out, key=lambda a: a["id"])


def with_last_runs(actions, last_runs):
    """The definitions with `_last_run` attached from run records (the CLI's side of what the
    store carries in the node)."""
    out = []
    for action in actions:
        action = dict(action)
        last = (last_runs or {}).get(action.get("id"))
        if last:
            action["_last_run"] = {k: last.get(k) for k in ("at", "on", "by", "stamp", "ready", "runs", "recorded_at")}
        out.append(action)
    return out


def describe_when(when):
    """The preconditions as one readable phrase."""
    parts = []
    for clause in when or []:
        if "node" in clause:
            text = "%s is a %s" % (clause["node"], clause.get("type") or "node")
            where = clause.get("where") or {}
            if where:
                text += " with " + ", ".join("%s %s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in where.items())
            parts.append(text)
        elif "edge" in clause:
            parts.append("%s -%s-> %s" % tuple(clause["edge"]))
        elif "not_edge" in clause:
            parts.append("no %s -%s-> %s" % tuple(clause["not_edge"]))
        elif "not_node" in clause:
            parts.append("no %s" % (clause.get("type") or "node"))
        else:
            parts.append(json.dumps(clause, ensure_ascii=False))
    return "  and  ".join(parts)


def readiness(action, nodes, edges, covers=None):
    """(ready ids, reason). The ids of the subject entities the action is ready on, sorted; when
    none, one sentence saying why. `covers` is what each class covers (model/vocabulary.covers)."""
    graph = Graph(nodes, edges, statuses=BELIEVED_OR_INTENDED, covers=covers)
    var = _model.subject_variable(action)
    subject = action.get("subject")
    if not var:
        return [], "the action binds no subject"
    ready = sorted({b[var] for b, _used in matches(graph, action.get("when") or []) if var in b})
    if ready:
        return ready, ""
    candidates = [n for n in graph.nodes.values() if n.get("type") == subject]
    if not candidates:
        return [], "no %s in the graph" % subject
    return [], "%d %s, none meet: %s" % (len(candidates), subject, describe_when(action.get("when")))


def bind(action, node):
    """(inputs, missing): the inputs filled from the subject's own fields, and the inputs the
    schema requires that nothing binds, which the caller must supply."""
    inputs = {}
    for name, source in (action.get("bind") or {}).items():
        if source == "$id":
            value = node.get("id")
        elif source == "$label":
            value = node.get("label")
        elif source.startswith("$attr."):
            attrs = node.get("attributes") or {}
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except ValueError:
                    attrs = {}
            value = attrs.get(source[len("$attr."):])
        else:
            value = None
        if value is not None:
            inputs[name] = value
    required = ((action.get("inputSchema") or {}).get("required")) or []
    missing = [name for name in required if name not in inputs]
    return inputs, missing


def tool_definition(action, nodes, edges, on=None, covers=None):
    """The action as an MCP tool definition, plus an `oto` block. With `on`, a subject node, the
    inputs come back bound."""
    ready, reason = readiness(action, nodes, edges, covers)
    out = {"name": action["id"], "title": action.get("label"), "description": action.get("description"),
           "inputSchema": action.get("inputSchema"), "annotations": dict(action.get("annotations") or {}),
           "oto": {"subject": action.get("subject"), "executed_by": action.get("executed_by"),
                   "ready_on": ready, "not_ready_because": reason or None,
                   "when": describe_when(action.get("when")), "invoke": action.get("invoke"),
                   "needs": list(action.get("needs") or []), "result": action.get("result"),
                   "schedule": action.get("schedule"), "last_run": action.get("_last_run"),
                   "timeout": action.get("timeout")}}
    if action.get("schedule"):
        is_due, why = due(action)
        out["oto"]["due"] = is_due
        out["oto"]["due_because"] = why
    if on is not None:
        inputs, missing = bind(action, on)
        out["oto"]["on"] = on.get("id")
        out["oto"]["ready"] = on.get("id") in ready
        out["oto"]["inputs"] = inputs
        out["oto"]["inputs_missing"] = missing
    return out


def catalog(actions, nodes, edges, ready_only=False, due_only=False, covers=None):
    """Every action as a tool definition, readiness computed, sorted by id. `due_only` keeps the
    scheduled read-only actions whose run is due and that are ready on at least one entity."""
    out = []
    for action in sorted(actions, key=lambda a: a.get("id") or ""):
        definition = tool_definition(action, nodes, edges, covers=covers)
        if (ready_only or due_only) and not definition["oto"]["ready_on"]:
            continue
        if due_only and not definition["oto"].get("due"):
            continue
        out.append(definition)
    return out


def for_entity(actions, nodes, edges, node, covers=None):
    """The actions whose subject class is the node's, each bound to it, ready ones first."""
    out = []
    for action in sorted(actions, key=lambda a: a.get("id") or ""):
        if action.get("subject") != node.get("type"):
            continue
        out.append(tool_definition(action, nodes, edges, on=node, covers=covers))
    out.sort(key=lambda d: (not d["oto"]["ready"], d["name"]))
    return out


# ---- text, the same for the CLI and the tool ----

def _kind(definition):
    ann = definition.get("annotations") or {}
    return "read-only" if ann.get("readOnlyHint") else ("destructive" if ann.get("destructiveHint") else "changes")


def text(definitions, heading=None):
    """The catalog as text: one block per action."""
    if not definitions:
        return (heading + "\n" if heading else "") + "No actions." + ("" if heading else " An action is a file actions/<id>.json.")
    lines = [heading] if heading else ["%d action(s); OTO lists them, the caller invokes:" % len(definitions)]
    for d in definitions:
        m = d["oto"]
        head = "• %s  [%s, on %s%s]  %s" % (d["name"], _kind(d), m["subject"],
                                            (", by " + m["executed_by"]) if m.get("executed_by") else "", d.get("title") or "")
        lines.append(head.rstrip())
        if m.get("on"):
            lines.append("    on %s: %s" % (m["on"], "READY" if m.get("ready") else "not ready (%s)" % (m.get("not_ready_because") or "preconditions not met on this entity")))
            if m.get("inputs"):
                lines.append("    inputs: " + json.dumps(m["inputs"], ensure_ascii=False, sort_keys=True))
            if m.get("inputs_missing"):
                lines.append("    the caller must supply: " + ", ".join(m["inputs_missing"]))
        elif m["ready_on"]:
            shown = m["ready_on"][:8]
            lines.append("    ready on %d: %s%s" % (len(m["ready_on"]), ", ".join(shown), " …" if len(m["ready_on"]) > 8 else ""))
        else:
            lines.append("    not ready: %s" % m["not_ready_because"])
        invoke = m.get("invoke") or {}
        detail = {k: v for k, v in invoke.items() if k != "transport"}
        lines.append("    invoke: %s %s" % (invoke.get("transport", "?"), json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail else ""))
        if m.get("needs"):
            lines.append("    needs (names only): " + ", ".join(m["needs"]))
        result = m.get("result") or {}
        if result:
            lines.append("    result: %s%s" % (result.get("kind"), (" -> " + json.dumps(result.get("then"), ensure_ascii=False, sort_keys=True)) if result.get("then") else ""))
        if m.get("schedule"):
            lines.append("    schedule: %s%s" % (m["schedule"], (" · DUE (%s)" % m.get("due_because")) if m.get("due") else
                                                 (" · not due (%s)" % m.get("due_because")) if m.get("due_because") else ""))
        if m.get("timeout"):
            lines.append("    timeout: %ss" % m["timeout"])
        last = m.get("last_run")
        if last:
            lines.append("    last run: %s on %s by %s%s%s" % (last.get("at"), last.get("on"), last.get("by"),
                                                             "" if last.get("ready", True) else " (preconditions did not hold)",
                                                             (" · %d run(s)" % last["runs"]) if last.get("runs") else ""))
    return "\n".join(lines)
