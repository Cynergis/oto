# -*- coding: utf-8 -*-
"""The work pack's one write: a transition of a work item, appended as a fact (roadmap M2, M3).

An item's state is never written on the item. `set` records what a person says about it as an
assertion (curate/assertions.py), appends a `Transition` citing it, supersedes the item's current
transition so the chain is the history, holds the candidate to the same gates as any change (the
diff's checks, the vocabulary's shapes, the ontology's blocking policies) and applies it. The
rule `state-follows-the-current-transition` then derives the state at the next build.

What the command refuses, the model refuses: `blocked` without a reason and a waiting-on (a
`Block` requires both), `deployed` by hand (a merged pull request or a promotion sets it), a date
that is not a date, a name that is several items or none. Nothing refused is written.

`board` (M5) reads the same graph the way a build does, the rules run, and groups the items: open,
blocked by whom or what each waits on, deployed by environment. The snapshot carries it as `work`,
so the workbench's Work page and `oto work board` show one thing. `notify` (M6) writes the first
message of the communication pack: from a block, to whom it waits on, carrying the item and the
reason, so the person asked has the context without anyone retyping it.
"""
import os

from .curate import assertions as _assertions, diff as _diff, ledger as _ledger, session as _session
from .model.vocabulary import ISO_DATE, _union, covers as _covers
from .project import ProjectError
from .reason import engine as _engine, rules as _rules, shapes as _shapes
from .reason.questions import declared_names

ITEM = "WorkItem"
TRANSITION, BLOCK = "Transition", "Block"
STATES = ("open", "blocked", "deployed")
BY_EVENT = ("deployed",)
TRANSITION_OF, WAITING_ON = "transition_of", "waiting_on"
MESSAGE, SENT_TO, REGARDING = "Message", "sent_to", "regarding"


class WorkError(ProjectError):
    """A refusal, in words the person can act on."""


def _load_vocabulary(project):
    import json
    with open(project.ontology_config_path, encoding="utf-8") as f:
        return json.load(f)


def _kinds(vocabulary, kind):
    """`kind` and every class that is a kind of it."""
    return _covers(vocabulary.get("classes") or {}).get(kind, {kind})


def resolve(graph, term, kinds):
    """The one current node `term` names among `kinds`, by id, label or alias (session.find).
    Raises with the candidates when it names several, or none."""
    found = [n for n in _session.find(graph, term)
             if n.get("type") in kinds and n.get("status", "current") == "current"]
    exact = [n for n in found if n.get("id") == term or term.lower() in
             [str(n.get("label") or "").lower()] + [str(a).lower() for a in (n.get("aliases") or [])]]
    if len(exact) == 1:
        return exact[0]
    if len(found) == 1:
        return found[0]
    if not found:
        raise WorkError("%r names no current %s" % (term, " or ".join(sorted(kinds))))
    raise WorkError("%r names %d things: %s. Say which, by id."
                    % (term, len(found), ", ".join("%s (%s)" % (n["id"], n.get("label") or "") for n in found[:6])))


def transitions_of(graph, item_id):
    """The item's transitions, current first, then the superseded ones, each with its node."""
    of = {e["from"] for e in graph.get("edges") or [] if e.get("rel") == TRANSITION_OF and e.get("to") == item_id}
    nodes = [n for n in graph.get("nodes") or [] if n.get("id") in of]
    return sorted(nodes, key=lambda n: (n.get("status", "current") != "current", n.get("valid_from") or "", n["id"]))


def current_state(graph, item, vocabulary):
    """The item's state as the build would derive it: the current transition's `to`, else what the
    item asserts (read through `was`), else the default."""
    current = [t for t in transitions_of(graph, item["id"]) if t.get("status", "current") == "current"]
    if current:
        return (current[0].get("attributes") or {}).get("to")
    reading = declared_names(vocabulary).get(item.get("type"), set())
    reading = getattr(reading, "reading", {}).get("state") or {}
    asserted = (item.get("attributes") or {}).get("state")
    if asserted is not None:
        return reading.get("was", {}).get(asserted, asserted)
    return reading.get("default")


def identity(project):
    """Who is speaking, from git when the person does not say: `user.name <user.email>`."""
    from . import gitx
    root = os.path.dirname(project.src)
    try:
        name = gitx.run(["config", "user.name"], cwd=root).strip()
        email = gitx.run(["config", "user.email"], cwd=root).strip()
    except ProjectError:
        return None
    if not (name or email):
        return None
    return ("%s <%s>" % (name, email)) if name and email else (name or email)


def _next_id(graph, prefix, item_id):
    stem = prefix + "." + item_id.split(".", 1)[-1]
    taken = {n.get("id") for n in graph.get("nodes") or []}
    n = 1
    while "%s-%d" % (stem, n) in taken:
        n += 1
    return "%s-%d" % (stem, n)


def _no_candidate(project):
    if _session.exists(project):
        raise WorkError("a curate candidate is open (%s): apply or abort it first, so this change is not mixed into it"
                        % os.path.basename(_session.candidate_path(project)))


def _commit(project, text, by, at, about, edit):
    """Record `text` as an assertion by `by`, let `edit(candidate, source)` append what cites it,
    hold the candidate to the gates and apply it. Returns what `edit` returned. Nothing refused is
    written: a refusal aborts the candidate, and the assertion stands as what was said."""
    _no_candidate(project)
    vocabulary = _load_vocabulary(project)
    live = _session.live(project)
    entry = _assertions.record(project, text=text, by=by.strip(), at=at, about=about)
    candidate_path = _session.start(project)
    try:
        candidate = _session.candidate(project)
        done = edit(candidate, {"source_type": _assertions.HUMAN_ASSERTION, "sources": [_assertions.reference(entry["id"])],
                                "source_doc": _assertions.reference(entry["id"]), "as_of": at, "valid_from": at,
                                "status": "current", "aliases": [], "tags": []})
        problems = gates(project, live, candidate, vocabulary)
        if problems:
            raise WorkError("refused by the gates:\n  - " + "\n  - ".join("%s: %s" % (f.subject, f.detail) for f in problems[:10]))
        _session._write(candidate_path, candidate)
    except Exception:
        _session.abort(project)
        raise
    summary = _diff.summarize(live, candidate)
    record = _ledger.entry(summary, _ledger.retirements(live, candidate), by=by.strip(), note="oto work: " + text,
                           sources=_ledger.new_sources(live, candidate))
    _session.apply(project)
    _ledger.append(project, record)
    done["assertion"] = entry["id"]
    return done


def set_state(project, term, state, by, at, reason=None, waiting_on=None, environment=None, note=None):
    """Append a transition of the item `term` names. Returns what was written:
    {"item", "label", "from", "to", "transition", "superseded", "waiting_on", "assertion"}."""
    if state not in STATES:
        raise WorkError("the state is one of %s, not %r" % (", ".join(STATES), state))
    if state in BY_EVENT:
        raise WorkError("deployed is set by what deploys: a merged pull request or a promotion to an environment, never by hand")
    if not (at or "").strip() or not ISO_DATE.match(at.strip()):
        raise WorkError("--at is the date it happened, as YYYY-MM-DD; never defaulted, never a word like 'yesterday'")
    at = at.strip()
    if not (by or "").strip():
        raise WorkError("say who records this: --by, or a git identity (user.name and user.email) in the project")
    if state == "blocked":
        missing = [flag for flag, value in (("--reason", reason), ("--waiting-on", waiting_on)) if not (value or "").strip()]
        if missing:
            raise WorkError("a block carries its context: %s %s required, so whoever reads it knows why and whom to ask"
                            % (" and ".join(missing), "are" if len(missing) > 1 else "is"))
    elif reason or waiting_on:
        raise WorkError("--reason and --waiting-on describe a block; a transition to %s carries neither" % state)
    _no_candidate(project)
    vocabulary = _load_vocabulary(project)
    live = _session.live(project)
    item = resolve(live, term, _kinds(vocabulary, ITEM))
    was = current_state(live, item, vocabulary)
    if was == state:
        raise WorkError("%s is already %s; nothing recorded" % (item.get("label") or item["id"], state))
    target = None
    if waiting_on:
        allowed = set()
        for kind in _union((vocabulary.get("properties") or {}).get(WAITING_ON, {}).get("range")):
            allowed |= _kinds(vocabulary, kind)
        target = resolve(live, waiting_on, allowed)

    text = "%s: %s -> %s" % (item.get("label") or item["id"], was, state)
    if reason:
        text += ". Reason: %s. Waiting on %s." % (reason.strip(), target.get("label") or target["id"])
    if note:
        text += " " + note.strip()

    def edit(candidate, source):
        previous = [t for t in transitions_of(candidate, item["id"]) if t.get("status", "current") == "current"]
        new_id = _next_id(candidate, "transition", item["id"])
        attributes = {"to": state, "at": at, "by": by.strip()}
        if reason:
            attributes["reason"] = reason.strip()
        if environment:
            attributes["environment"] = environment
        node = dict(source, id=new_id, type=BLOCK if state == "blocked" else TRANSITION,
                    label="%s %s" % (item.get("label") or item["id"], "blocked" if state == "blocked" else state),
                    summary=(reason.strip() if reason else "%s on %s, recorded by %s." % (state, at, by.strip())),
                    attributes=attributes)
        if previous:
            node["supersedes"] = previous[0]["id"]
            node["change_note"] = text
            for old in previous:
                old["status"] = "superseded"
                old["valid_to"] = at
                old["superseded_by"] = new_id
                old.setdefault("change_note", text)
        candidate["nodes"].append(node)
        candidate["edges"].append({"from": new_id, "rel": TRANSITION_OF, "to": item["id"]})
        if target:
            candidate["edges"].append({"from": new_id, "rel": WAITING_ON, "to": target["id"]})
        return {"item": item["id"], "label": item.get("label") or item["id"], "from": was, "to": state,
                "transition": new_id, "superseded": [t["id"] for t in previous],
                "waiting_on": target["id"] if target else None}
    return _commit(project, text, by, at, [item["id"]] + ([target["id"]] if target else []), edit)


def _states(project, vocabulary, graph):
    """{item id: (state, deployed_to)} as a build derives them: the rules run over the current
    facts, then each item's attributes read with the default."""
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
    declared = declared_names(vocabulary)
    derived = {}
    rules = _rules.load(project)
    if rules and not _rules.problems(rules, vocabulary):
        try:
            for a in _engine.run(rules, nodes, edges, covers=_covers(vocabulary.get("classes") or {}), declared=declared)["attributes"]:
                derived.setdefault(a["node"], {})[a["name"]] = a["value"]
        except _engine.DoesNotConverge:
            pass
    from .reason.match import Graph
    seen = Graph(nodes, edges, derived, covers=_covers(vocabulary.get("classes") or {}), declared=declared)
    return {nid: (seen.attribute(nid, "state"), seen.attribute(nid, "deployed_to"))
            for nid, n in seen.nodes.items() if n.get("type") in _kinds(vocabulary, ITEM)}


def board(project):
    """The plan's three columns, from the live graph as a build would derive it: {"counts", "open":
    [{id, label, kind, due}] soonest due first, "blocked": [{id, label, since, reason, by, transition,
    waiting_on: {id, label, type}}] grouped by whom or what each waits on, "deployed": [{id, label,
    environment, at}] by environment, qa to prod}. None when the vocabulary declares no work item."""
    vocabulary = _load_vocabulary(project)
    if ITEM not in (vocabulary.get("classes") or {}):
        return None
    graph = _session.live(project)
    by_id = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    states = _states(project, vocabulary, graph)
    out = {"counts": {s: 0 for s in STATES}, "open": [], "blocked": [], "deployed": []}
    for nid, (state, environment) in states.items():
        item = by_id[nid]
        label = item.get("label") or nid
        attributes = item.get("attributes") or {}
        out["counts"][state] = out["counts"].get(state, 0) + 1
        if state == "blocked":
            current = [t for t in transitions_of(graph, nid) if t.get("status", "current") == "current"]
            block = current[0] if current else None
            waits = [e["to"] for e in graph.get("edges") or [] if block and e.get("from") == block["id"] and e.get("rel") == WAITING_ON]
            target = by_id.get(waits[0]) if waits else None
            held = (block or {}).get("attributes") or {}
            out["blocked"].append({"id": nid, "label": label, "since": held.get("at"), "reason": held.get("reason"),
                                   "by": held.get("by"), "transition": block["id"] if block else None,
                                   "waiting_on": {"id": target["id"], "label": target.get("label") or target["id"],
                                                  "type": target.get("type")} if target else None})
        elif state == "deployed":
            current = [t for t in transitions_of(graph, nid) if t.get("status", "current") == "current"]
            out["deployed"].append({"id": nid, "label": label, "environment": environment,
                                    "at": ((current[0].get("attributes") or {}).get("at") if current else None)})
        else:
            out["open"].append({"id": nid, "label": label, "kind": attributes.get("kind"), "due": attributes.get("due")})
    out["open"].sort(key=lambda i: (i["due"] or "9999", i["label"]))
    out["blocked"].sort(key=lambda b: ((b["waiting_on"] or {}).get("label") or "", b["since"] or "", b["label"]))
    order = {"qa": 0, "preprod": 1, "prod": 2}
    out["deployed"].sort(key=lambda d: (order.get(d["environment"], 9), d["label"]))
    return out


def board_text(board, name=None):
    """The board as text: blocked first, by whom it waits on; then deployed by environment; then open."""
    c = board["counts"]
    lines = ["%s%d item(s): %d open, %d blocked, %d deployed" % ((name + ": ") if name else "", sum(c.values()), c["open"], c["blocked"], c["deployed"])]
    lines.append("blocked (%d)%s" % (c["blocked"], ", by whom or what it waits on:" if board["blocked"] else ""))
    waiting = None
    for b in board["blocked"]:
        who = ("%s (%s)" % (b["waiting_on"]["label"], b["waiting_on"]["type"])) if b["waiting_on"] else "(nothing named)"
        if who != waiting:
            lines.append("  %s" % who)
            waiting = who
        lines.append("    %-40s since %s, raised by %s" % (b["label"], b["since"] or "?", b["by"] or "?"))
        if b["reason"]:
            lines.append("      %s" % b["reason"])
    lines.append("deployed (%d)%s" % (c["deployed"], ":" if board["deployed"] else ""))
    for d in board["deployed"]:
        lines.append("  %-8s %-40s %s" % (d["environment"] or "?", d["label"], d["at"] or ""))
    lines.append("open (%d)%s" % (c["open"], ":" if board["open"] else ""))
    for i in board["open"]:
        lines.append("  %-40s %s%s" % (i["label"], i["kind"] or "", (", due " + i["due"]) if i["due"] else ""))
    return "\n".join(lines)


def notify(project, term, by, at, body=None, to=None, due=None):
    """Write a message from the block on `term` to whom it waits on: pending, carrying the item, the
    block's date, reason and author, and what the sender adds. `to` names someone else to tell.
    Returns {"message", "item", "label", "to", "to_label", "assertion"}."""
    if not (at or "").strip() or not ISO_DATE.match(at.strip()):
        raise WorkError("--at is the date it is sent, as YYYY-MM-DD; never defaulted")
    if due and not ISO_DATE.match(due.strip()):
        raise WorkError("--due is a date, YYYY-MM-DD")
    if not (by or "").strip():
        raise WorkError("say who sends this: --by, or a git identity (user.name and user.email) in the project")
    _no_candidate(project)
    vocabulary = _load_vocabulary(project)
    if MESSAGE not in (vocabulary.get("classes") or {}):
        raise WorkError("the vocabulary declares no Message, so there is nowhere to put one: a message needs the "
                        "communication ontology, which extends work (oto init --ontology communication)")
    live = _session.live(project)
    item = resolve(live, term, _kinds(vocabulary, ITEM))
    label = item.get("label") or item["id"]
    if current_state(live, item, vocabulary) != "blocked":
        raise WorkError("%s is not blocked; a notification goes from a block to whom it waits on" % label)
    current = [t for t in transitions_of(live, item["id"]) if t.get("status", "current") == "current"]
    block = current[0] if current else None
    held = (block or {}).get("attributes") or {}
    recipients = set()
    for kind in _union((vocabulary.get("properties") or {}).get(SENT_TO, {}).get("range")):
        recipients |= _kinds(vocabulary, kind)
    if to:
        target = resolve(live, to, recipients)
    else:
        waits = [e["to"] for e in live.get("edges") or [] if block and e.get("from") == block["id"] and e.get("rel") == WAITING_ON]
        target = next((n for n in live.get("nodes") or [] if n.get("id") in waits), None)
        if target is None or target.get("type") not in recipients:
            raise WorkError("%s waits on %s, not on someone who can be told: say whom with --to"
                            % (label, ("%s (%s)" % (target["id"], target.get("type"))) if target else "nothing named"))
    text = "%s is blocked since %s: %s (raised by %s)." % (label, held.get("at") or "?", held.get("reason") or "no reason recorded",
                                                           held.get("by") or "nobody named")
    if body and body.strip():
        text += " " + body.strip()
    to_label = target.get("label") or target["id"]

    def edit(candidate, source):
        new_id = _next_id(candidate, "message", item["id"])
        attributes = {"from": by.strip(), "body": text, "sent": at.strip(), "status": "pending"}
        if due:
            attributes["due"] = due.strip()
        candidate["nodes"].append(dict(source, id=new_id, type=MESSAGE, label="To %s about %s" % (to_label, label),
                                       summary=text[:160], attributes=attributes))
        candidate["edges"].append({"from": new_id, "rel": SENT_TO, "to": target["id"]})
        candidate["edges"].append({"from": new_id, "rel": REGARDING, "to": item["id"]})
        if block:
            candidate["edges"].append({"from": new_id, "rel": REGARDING, "to": block["id"]})
        return {"message": new_id, "item": item["id"], "label": label, "to": target["id"], "to_label": to_label}
    return _commit(project, "message to %s: %s" % (to_label, text), by, at.strip(), [item["id"], target["id"]], edit)


def gates(project, live, candidate, vocabulary):
    """The blocking findings the candidate would meet at `oto curate check`: the diff's checks, the
    declared shapes, the ontology's blocking policies."""
    findings = [f for f in _diff.check(live, candidate, vocabulary, known_assertions=_assertions.known_ids(project))
                if f.severity == _diff.Finding.BLOCKING]
    nodes, edges = candidate.get("nodes") or [], candidate.get("edges") or []
    for item in _shapes.findings(vocabulary, nodes, edges):
        findings.append(_diff.Finding(_diff.Finding.BLOCKING, item["node"], "shape %s: %s" % (item["kind"], item["message"])))
    rules = _rules.load(project)
    if rules and not _rules.problems(rules, vocabulary):
        try:
            outcome = _engine.run(rules, nodes, edges, covers=_covers(vocabulary.get("classes") or {}), declared=declared_names(vocabulary))
        except _engine.DoesNotConverge as exc:
            findings.append(_diff.Finding(_diff.Finding.BLOCKING, "rules", str(exc)))
        else:
            findings += [_diff.Finding(_diff.Finding.BLOCKING, f.get("node") or "(graph)", "policy %s: %s" % (f["rule"], f["message"]))
                         for f in outcome["findings"] if f["severity"] == "blocking"]
    return findings
