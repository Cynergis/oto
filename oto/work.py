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
reason, so the person asked has the context without anyone retyping it. `inbox` (N3) lists what
is pending for a person, the way a session opens; `reply` (N4) answers a message, and a resolving
reply also lifts the block it was about, in one gated change; `event merged-pr` records what a
merged pull request deployed, once however often the event is delivered. Identity is the git
`user.name <user.email>` in the project, mapped to a Person by email, else by name.
"""
import os

from . import audit as _audit
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
MESSAGE, SENT_TO, SENT_BY, REGARDING, IN_REPLY_TO = "Message", "sent_to", "sent_by", "regarding", "in_reply_to"
PERSON = "Person"


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


def person_for(graph, identity):
    """The Person `identity` ("Name <email>", or either alone) names: by email when one is recorded
    on a Person, else by label or alias. None when the project knows no such person."""
    text = (identity or "").strip()
    if not text:
        return None
    email = text[text.rfind("<") + 1:text.rfind(">")].strip().lower() if "<" in text and text.endswith(">") else \
        (text.lower() if "@" in text and " " not in text else "")
    name = text[:text.rfind("<")].strip() if "<" in text else ("" if email else text)
    people = [n for n in graph.get("nodes") or [] if n.get("type") == PERSON and n.get("status", "current") == "current"]
    if email:
        for n in people:
            if str((n.get("attributes") or {}).get("email") or "").strip().lower() == email:
                return n
    if name:
        names = [n for n in people if name.lower() in
                 [str(n.get("label") or "").lower()] + [str(a).lower() for a in (n.get("aliases") or [])]]
        if len(names) == 1:
            return names[0]
    return None


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


def _commit(project, text, by, at, about, edit, action="work"):
    """Record `text` as an assertion by `by`, let `edit(candidate, source)` append what cites it,
    hold the candidate to the gates and apply it. Returns what `edit` returned. Nothing refused is
    written: a refusal aborts the candidate, and the assertion stands as what was said. Both
    outcomes go to the audit log (audit.py), keyed to the nodes touched."""
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
            refusal = WorkError("refused by the gates:\n  - " + "\n  - ".join("%s: %s" % (f.subject, f.detail) for f in problems[:10]))
            _audit.append(project, action, by, about, "refused", detail=str(refusal).splitlines()[1].strip(" -") if "\n" in str(refusal) else str(refusal))
            raise refusal
        _session._write(candidate_path, candidate)
    except Exception:
        _session.abort(project)
        raise
    summary = _diff.summarize(live, candidate)
    record = _ledger.entry(summary, _ledger.retirements(live, candidate), by=by.strip(), note="oto %s: %s" % (action, text),
                           sources=_ledger.new_sources(live, candidate))
    _session.apply(project)
    _ledger.append(project, record)
    done["assertion"] = entry["id"]
    touched = list(about) + list(summary.get("nodes_added") or []) + [nid for nid, _f in summary.get("nodes_changed") or []]
    _audit.append(project, action, by, touched, "applied", detail=text)
    return done


def refused(project, action, by, term, error):
    """Record a refusal that happened before anything was written: what was asked, of which node,
    and why not. The node is the term as given when it names nothing resolvable."""
    node = term
    try:
        live = _session.live(project)
        vocabulary = _load_vocabulary(project)
        for kinds in (_kinds(vocabulary, ITEM), _kinds(vocabulary, MESSAGE) if MESSAGE in (vocabulary.get("classes") or {}) else set(), None):
            try:
                found = resolve(live, term or "", kinds) if kinds else None
            except WorkError:
                found = None
            if found:
                node = found["id"]
                break
        else:
            found = [n for n in _session.find(live, term or "") if n.get("status", "current") == "current"]
            if len(found) == 1:
                node = found[0]["id"]
    except (OSError, ValueError):
        pass
    return _audit.append(project, action, by, [node] if node else [], "refused", detail=str(error).splitlines()[0])


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
        return dict(_append_transition(candidate, source, item, state, at, by, text, reason=reason, target=target, environment=environment),
                    **{"from": was})
    return _commit(project, text, by, at, [item["id"]] + ([target["id"]] if target else []), edit, action="work set")


def _append_transition(candidate, source, item, state, at, by, text, reason=None, target=None, environment=None, event=None):
    """Append the transition of `item` to `state` to the candidate, superseding its current one.
    Returns {"item", "label", "from", "to", "transition", "superseded", "waiting_on"}."""
    previous = [t for t in transitions_of(candidate, item["id"]) if t.get("status", "current") == "current"]
    new_id = _next_id(candidate, "transition", item["id"])
    attributes = {"to": state, "at": at, "by": by.strip()}
    if reason:
        attributes["reason"] = reason.strip()
    if environment:
        attributes["environment"] = environment
    if event:
        attributes["event"] = event
    label = item.get("label") or item["id"]
    node = dict(source, id=new_id, type=BLOCK if state == "blocked" else TRANSITION,
                label="%s %s" % (label, "blocked" if state == "blocked" else state),
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
    return {"item": item["id"], "label": label, "to": state, "transition": new_id,
            "superseded": [t["id"] for t in previous], "waiting_on": target["id"] if target else None}


def _seen(project, vocabulary, graph):
    """The graph as a build sees it: the rules run over the current facts, each node's attributes
    read with what is derived and the defaults."""
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
    declared = declared_names(vocabulary)
    cover = _covers(vocabulary.get("classes") or {})
    derived = {}
    rules = _rules.load(project)
    if rules and not _rules.problems(rules, vocabulary):
        try:
            for a in _engine.run(rules, nodes, edges, covers=cover, declared=declared)["attributes"]:
                derived.setdefault(a["node"], {})[a["name"]] = a["value"]
        except _engine.DoesNotConverge:
            pass
    from .reason.match import Graph
    return Graph(nodes, edges, derived, covers=cover, declared=declared)


def _states(project, vocabulary, graph):
    """{item id: (state, deployed_to)} as a build derives them."""
    seen = _seen(project, vocabulary, graph)
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
        attributes = {"from": by.strip(), "body": text, "sent": at.strip()}
        if due:
            attributes["due"] = due.strip()
        candidate["nodes"].append(dict(source, id=new_id, type=MESSAGE, label="To %s about %s" % (to_label, label),
                                       summary=text[:160], attributes=attributes))
        candidate["edges"].append({"from": new_id, "rel": SENT_TO, "to": target["id"]})
        sender = person_for(candidate, by)
        if sender:
            candidate["edges"].append({"from": new_id, "rel": SENT_BY, "to": sender["id"]})
        candidate["edges"].append({"from": new_id, "rel": REGARDING, "to": item["id"]})
        if block:
            candidate["edges"].append({"from": new_id, "rel": REGARDING, "to": block["id"]})
        return {"message": new_id, "item": item["id"], "label": label, "to": target["id"], "to_label": to_label}
    return _commit(project, "message to %s: %s" % (to_label, text), by, at.strip(), [item["id"], target["id"]], edit, action="work notify")


def _message_rows(project, vocabulary, graph):
    """Every current message with what it regards: [{id, from, sent, due, status, body, to: [ids],
    item: {id, label} or None, block: {since, reason} or None, in_reply_to}]."""
    seen = _seen(project, vocabulary, graph)
    by_id = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    edges = graph.get("edges") or []
    out = []
    for nid, n in sorted(seen.nodes.items()):
        if n.get("type") not in _kinds(vocabulary, MESSAGE):
            continue
        regards = [by_id[e["to"]] for e in edges if e.get("from") == nid and e.get("rel") == REGARDING and e.get("to") in by_id]
        item = next((r for r in regards if r.get("type") in _kinds(vocabulary, ITEM)), None)
        block = next((r for r in regards if r.get("type") in _kinds(vocabulary, TRANSITION)), None)
        held = (block or {}).get("attributes") or {}
        a = n.get("attributes") or {}
        out.append({"id": nid, "from": a.get("from"), "sent": a.get("sent"), "due": a.get("due"), "status": seen.attribute(nid, "status"),
                    "body": a.get("body"), "to": [e["to"] for e in edges if e.get("from") == nid and e.get("rel") == SENT_TO],
                    "item": {"id": item["id"], "label": item.get("label") or item["id"]} if item else None,
                    "block": {"since": held.get("at"), "reason": held.get("reason"),
                              "lifted": block.get("status", "current") != "current"} if block else None,
                    "in_reply_to": next((e["to"] for e in edges if e.get("from") == nid and e.get("rel") == IN_REPLY_TO), None)})
    return out


def inbox(project, as_=None):
    """What waits for a person: {"person": {id, label}, "pending": [message rows]}, pending messages
    sent to them, oldest first. `as_` names them (id, label, alias, or "Name <email>"); without it,
    the git identity. None when the vocabulary has no Message; raises when nobody matches."""
    vocabulary = _load_vocabulary(project)
    if MESSAGE not in (vocabulary.get("classes") or {}):
        return None
    live = _session.live(project)
    if as_:
        recipients = set()
        for kind in _union((vocabulary.get("properties") or {}).get(SENT_TO, {}).get("range")):
            recipients |= _kinds(vocabulary, kind)
        who = person_for(live, as_) or resolve(live, as_, recipients)
    else:
        me = identity(project)
        who = person_for(live, me) if me else None
        if who is None:
            raise WorkError("no Person matches %s: name yourself with --as, or record your email on your Person"
                            % (("the git identity %r" % me) if me else "a git identity (none in this project)"))
    rows = [m for m in _message_rows(project, vocabulary, live) if who["id"] in m["to"] and m["status"] == "pending"]
    rows.sort(key=lambda m: (m["sent"] or "", m["id"]))
    return {"person": {"id": who["id"], "label": who.get("label") or who["id"]}, "pending": rows}


def inbox_text(found, name=None):
    """The inbox as a session opens with it."""
    person, rows = found["person"], found["pending"]
    head = "%s%s pending for %s" % ((name + " · ") if name else "", len(rows) if rows else "nothing", person["label"])
    if not rows:
        return head
    lines = [head]
    for m in rows:
        where = (" · re %s" % m["item"]["label"]) if m["item"] else ""
        if m["block"] and not m["block"]["lifted"]:
            where += " (blocked since %s)" % (m["block"]["since"] or "?")
        lines.append("  ● %s · from %s%s%s" % (m["id"], m["from"] or "?", where, (" · due %s" % m["due"]) if m["due"] else ""))
        for line in (m["body"] or "").splitlines() or [""]:
            lines.append("    %s" % line)
        lines.append("    reply:  oto work reply %s --body \"...\"%s" % (m["id"], "   # --resolve lifts the block" if m["block"] and not m["block"]["lifted"] else ""))
    return "\n".join(lines)


def reply(project, term, body, by, at, resolve_it=False, to=None):
    """Answer a message: a Message in reply to it, from `by`, regarding what it regarded, with the
    outcome replied or, with `resolve_it`, resolved, which also lifts the block the message was
    about if the item is still blocked. Returns {"message", "reply", "outcome", "item", "label",
    "transition", "from", "to", "assertion"}."""
    if not (at or "").strip() or not ISO_DATE.match(at.strip()):
        raise WorkError("--at is the date of the reply, as YYYY-MM-DD; never defaulted")
    if not (body or "").strip():
        raise WorkError("a reply says something: --body")
    if not (by or "").strip():
        raise WorkError("say who replies: --by, or a git identity (user.name and user.email) in the project")
    _no_candidate(project)
    vocabulary = _load_vocabulary(project)
    if MESSAGE not in (vocabulary.get("classes") or {}):
        raise WorkError("the vocabulary declares no Message: a reply needs the communication ontology (oto init --ontology communication)")
    live = _session.live(project)
    original = resolve(live, term, _kinds(vocabulary, MESSAGE))
    row = next(m for m in _message_rows(project, vocabulary, live) if m["id"] == original["id"])
    if row["status"] == "resolved":
        raise WorkError("%s is already resolved; nothing to answer" % original["id"])
    outcome = "resolved" if resolve_it else "replied"
    recipients = set()
    for kind in _union((vocabulary.get("properties") or {}).get(SENT_TO, {}).get("range")):
        recipients |= _kinds(vocabulary, kind)
    target = None
    if to:
        target = resolve(live, to, recipients)
    else:
        sent_by = [e["to"] for e in live.get("edges") or [] if e.get("from") == original["id"] and e.get("rel") == SENT_BY]
        target = next((n for n in live.get("nodes") or [] if n.get("id") in sent_by), None)
        if target is None and row["from"]:
            try:
                target = resolve(live, row["from"], recipients)
            except WorkError:
                target = None                                      # an agent or a tool asked: the reply answers the thread
    item = next((n for n in live.get("nodes") or [] if row["item"] and n.get("id") == row["item"]["id"]), None)
    lift = bool(resolve_it and item and current_state(live, item, vocabulary) == "blocked")
    text = "reply to %s%s: %s" % (original["id"], " (resolved)" if resolve_it else "", body.strip())

    def edit(candidate, source):
        new_id = _next_id(candidate, "message", (item or original)["id"])
        attributes = {"from": by.strip(), "body": body.strip(), "sent": at.strip(), "outcome": outcome}
        candidate["nodes"].append(dict(source, id=new_id, type=MESSAGE, label="Reply to %s" % (original.get("label") or original["id"]),
                                       summary=body.strip()[:160], attributes=attributes))
        candidate["edges"].append({"from": new_id, "rel": IN_REPLY_TO, "to": original["id"]})
        for e in list(live.get("edges") or []):
            if e.get("from") == original["id"] and e.get("rel") == REGARDING:
                candidate["edges"].append({"from": new_id, "rel": REGARDING, "to": e["to"]})
        if target:
            candidate["edges"].append({"from": new_id, "rel": SENT_TO, "to": target["id"]})
        sender = person_for(candidate, by)
        if sender:
            candidate["edges"].append({"from": new_id, "rel": SENT_BY, "to": sender["id"]})
        done = {"message": original["id"], "reply": new_id, "outcome": outcome, "item": item["id"] if item else None,
                "label": (item.get("label") or item["id"]) if item else None, "transition": None, "from": None,
                "to": target["id"] if target else None}
        if lift:
            moved = _append_transition(candidate, source, item, "open", at.strip(), by,
                                       "%s: blocked -> open. %s" % (item.get("label") or item["id"], body.strip()))
            done["transition"], done["from"] = moved["transition"], "blocked"
        return done
    about = [original["id"]] + ([item["id"]] if item else [])
    return _commit(project, text, by, at.strip(), about, edit, action="work reply")


def event_merged_pr(project, repo, number, term, environment, at, by=None):
    """A merged pull request deployed `term` to `environment`: append the transition once. The
    event is `github:<repo>#<number>`; delivered again, nothing is appended. Returns the transition
    record, or {"already": True, "event": id} when it was recorded before."""
    event = "github:%s#%s" % (repo.strip(), str(number).strip())
    if not (at or "").strip() or not ISO_DATE.match(at.strip()):
        raise WorkError("--at is the date it merged, as YYYY-MM-DD")
    if environment not in ("qa", "preprod", "prod"):
        raise WorkError("--environment is qa, preprod or prod: where the merge deployed it")
    _no_candidate(project)
    vocabulary = _load_vocabulary(project)
    live = _session.live(project)
    item = resolve(live, term, _kinds(vocabulary, ITEM))
    who = (by or "").strip() or "pull request %s#%s merged" % (repo.strip(), str(number).strip())
    for t in transitions_of(live, item["id"]):
        if (t.get("attributes") or {}).get("event") == event:
            _audit.append(project, "work event", who, [item["id"], t["id"]], "unchanged", detail="%s already recorded" % event)
            return {"already": True, "event": event, "transition": t["id"], "item": item["id"], "label": item.get("label") or item["id"]}
    was = current_state(live, item, vocabulary)
    if was == "deployed":
        seen = _seen(project, vocabulary, live)
        if seen.attribute(item["id"], "deployed_to") == environment:
            current = [t for t in transitions_of(live, item["id"]) if t.get("status", "current") == "current"]
            _audit.append(project, "work event", who, [item["id"]], "unchanged", detail="%s: already deployed to %s" % (event, environment))
            return {"already": True, "event": event, "transition": current[0]["id"] if current else None,
                    "item": item["id"], "label": item.get("label") or item["id"],
                    "reason": "already deployed to %s" % environment}      # an epic's later pull requests change no state
    text = "%s: %s -> deployed to %s by %s" % (item.get("label") or item["id"], was, environment, event)

    def edit(candidate, source):
        return dict(_append_transition(candidate, source, item, "deployed", at.strip(), who, text, environment=environment, event=event),
                    **{"from": was, "event": event})
    return _commit(project, "%s: %s" % (event, text), who, at.strip(), [item["id"]], edit, action="work event")


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


def event_verdict(project, term, run_id, component, verdict, at, by=None, gaps=(), waiting_on=None):
    """A factory verdict on the work item (roadmap M4): a failed or escalated build blocks the item
    on a named person, with the run, the component and the gaps as the reason; a pass changes no
    state (deployed is set by a merge or a promotion) and is noted in the audit log."""
    verdict = (verdict or "").strip().lower()
    if verdict not in ("pass", "fail", "escalated"):
        raise WorkError("--verdict is pass, fail or escalated, not %r" % verdict)
    if not (run_id or "").strip() or not (component or "").strip():
        raise WorkError("a factory verdict names its run (--run) and its component (--component)")
    who = (by or "").strip() or "oto factory run %s" % run_id.strip()
    if verdict == "pass":
        from . import audit as _audit
        vocabulary = _load_vocabulary(project)
        item = resolve(_session.live(project), term, _kinds(vocabulary, ITEM))
        _audit.append(project, "work event", who, [item["id"]], "unchanged", detail="run %s: %s passed; no state changes on a pass" % (run_id.strip(), component.strip()))
        return {"noted": True, "item": item["id"], "label": item.get("label") or item["id"]}
    if not (waiting_on or "").strip():
        raise WorkError("a failed or escalated build blocks the item on a person: --waiting-on names whom")
    reason = "the factory could not build %s in run %s (%s): %s" % (component.strip(), run_id.strip(), verdict, "; ".join(str(g) for g in gaps) if gaps else "no gaps named")
    done = set_state(project, term, "blocked", who, at, reason=reason, waiting_on=waiting_on)
    done["noted"] = False
    return done
