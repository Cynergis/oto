# -*- coding: utf-8 -*-
"""The product's domain graph (roadmap Epic I). This release: an event-storming board in (I2).

    oto ddd storm --from board.json --at YYYY-MM-DD [--name <slug>] [--context <node id>]

A board is what a storming session leaves: stickies by kind, in the order they were put up. The
file is plain JSON, one object per sticky, a kind and a text and what the sticky points at by the
text of another sticky:

    {"session": "Invoice approval, big picture", "held_on": "2026-10-20", "facilitator": "Ana Lyst",
     "context": "Invoice approval",
     "stickies": [
       {"kind": "actor", "text": "Approver"},
       {"kind": "aggregate", "text": "Invoice"},
       {"kind": "external system", "text": "Supplier portal", "sends": ["Submit invoice"]},
       {"kind": "command", "text": "Submit invoice", "handled_by": "Invoice", "raises": "Invoice submitted"},
       {"kind": "event", "text": "Invoice submitted", "by": "Invoice"},
       {"kind": "policy", "text": "Whenever an invoice is submitted, check the rules", "when": "Invoice submitted", "then": "Check approval rules"},
       {"kind": "read model", "text": "Pending invoices", "from": ["Invoice submitted"], "consulted_by": "Approver", "fields": ["supplier", "amount"]},
       {"kind": "hot spot", "text": "Who approves above 10k?", "about": "Approve invoice"}]}

`storm` writes the board as a document in the corpus (one line per sticky, the evidence each fact
quotes) and a capture against the pack's capture schema (compile/capture.py): an event is a
`DomainEvent` emitted by its aggregate and preceding the next event on the board; a command is a
`Command` handled by its aggregate, raising its event, triggered by its actor (a `Role`), by the
policy that issues it, or by the external system that sends it; a policy is a `Reaction`; a read
model, an external system and a hot spot (an `OpenQuestion`, open) are theirs; an aggregate gets
the root `Entity` the vocabulary requires, named after it; every element is part of the context
(the board's, as a new `BoundedContext`, or `--context` an existing one). `oto curate propose
--from captures/storm-<slug>.json` makes the proposal and the gates take it like any other change.
What the board does not say is said first (a command with no aggregate, a sticky that points at
nothing), never invented. Readiness is not the board's to say: every element reads as a draft until
a named person decides it is ready (`oto decide <node> readiness=ready --by <who> --at <date>`),
which is the analyst's sign-off on the graph itself.
"""
import json
import os
import re

from ...naming import slug as _slug
from ...project import ProjectError

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KINDS = {"event": "event", "domain event": "event", "command": "command", "actor": "actor", "role": "actor", "aggregate": "aggregate",
         "policy": "policy", "reaction": "policy", "read model": "read model", "readmodel": "read model", "read-model": "read model",
         "external system": "external system", "external-system": "external system", "externalsystem": "external system", "system": "external system",
         "hot spot": "hot spot", "hotspot": "hot spot", "hot-spot": "hot spot", "question": "hot spot"}
TYPES = {"event": "DomainEvent", "command": "Command", "actor": "Role", "aggregate": "Aggregate", "policy": "Reaction", "read model": "ReadModel",
         "external system": "ExternalSystem", "hot spot": "OpenQuestion"}
IN_CONTEXT = ("DomainEvent", "Command", "Reaction", "ReadModel", "Aggregate")


class DddError(ProjectError):
    """A refusal, in words the person can act on."""


def _list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(v) for v in value]


def read_board(board):
    """The board checked: {"session", "held_on", "facilitator", "context", "stickies": [{"kind", "text", ...}]}."""
    if not isinstance(board, dict) or not isinstance(board.get("stickies"), list) or not board["stickies"]:
        raise DddError("a board is {\"session\": ..., \"context\": ..., \"stickies\": [{\"kind\": ..., \"text\": ...}, ...]} with at least one sticky")
    out = []
    for raw in board["stickies"]:
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            raise DddError("every sticky carries a kind and a text: %s" % json.dumps(raw)[:80])
        kind = KINDS.get(str(raw.get("kind") or "").strip().lower())
        if not kind:
            raise DddError("sticky %r has kind %r; a sticky is one of: event, command, actor, aggregate, policy, read model, external system, hot spot"
                           % (raw.get("text"), raw.get("kind")))
        out.append(dict(raw, kind=kind, text=str(raw["text"]).strip()))
    return {"session": str(board.get("session") or "Event storming").strip(), "held_on": board.get("held_on"), "facilitator": board.get("facilitator"),
            "context": (str(board.get("context")).strip() if board.get("context") else None), "stickies": out}


def document(board, doc, at, source):
    title = "Event storming: %s" % board["session"]
    held = []
    if board.get("held_on"):
        held.append("held on %s" % board["held_on"])
    if board.get("facilitator"):
        held.append("facilitated by %s" % board["facilitator"])
    lines = ["# %s" % title, "", "The board of the session%s, read from %s on %s by `oto ddd storm`: one line per sticky, in the order they were put up; "
             "each fact in the graph quotes its sticky here.%s" % (", " + ", ".join(held) if held else "", source, at,
                                                                  " Context: %s." % board["context"] if board.get("context") else ""), "", "## Stickies", ""]
    for s in board["stickies"]:
        extra = []
        for key, word in (("by", "by"), ("actor", "actor"), ("handled_by", "handled by"), ("raises", "raises"), ("when", "when"), ("then", "then"),
                          ("from", "from"), ("consulted_by", "consulted by"), ("sends", "sends"), ("receives", "receives"), ("about", "about")):
            if s.get(key):
                extra.append("%s %s" % (word, ", ".join(_list(s[key]))))
        lines.append("- [%s] %s%s" % (s["kind"], s["text"], " (%s)" % "; ".join(extra) if extra else ""))
    return title, "\n".join(lines).rstrip() + "\n"


def capture(board, doc, at, context_id=None):
    """(capture, gaps): the board as items against the ddd vocabulary."""
    stickies = board["stickies"]
    by_text = {}
    for s in stickies:
        by_text.setdefault(s["text"].lower(), s)
    ids = {s["text"].lower(): _slug(s["text"]) for s in stickies}
    items, gaps = [], []
    context = context_id
    if not context:
        if not board.get("context"):
            raise DddError("the board names no context and --context names none: a storming session is about one bounded context")
        context = _slug(board["context"])
        items.append({"type": "BoundedContext", "id": context, "label": board["context"], "summary": "The bounded context the session %s stormed." % board["session"],
                      "fields": {}, "links": {}, "where": "context", "quote": board["context"]})

    def ref(text, what, kinds=None):
        key = str(text).strip().lower()
        if key in ids and (kinds is None or by_text[key]["kind"] in kinds):
            return ids[key]
        gaps.append("%s points at %r, which is no %s on the board; the link is left out" % (what, text, " or ".join(kinds) if kinds else "sticky"))
        return None

    policies_then = {str(s.get("then") or "").strip().lower(): s for s in stickies if s["kind"] == "policy" and s.get("then")}
    sent_by = {}
    for s in stickies:
        if s["kind"] == "external system":
            for t in _list(s.get("sends")):
                sent_by.setdefault(t.strip().lower(), s)
    events = [s for s in stickies if s["kind"] == "event"]
    for s in stickies:
        kind, text, sid = s["kind"], s["text"], ids[s["text"].lower()]
        item = {"type": TYPES[kind], "id": sid, "label": text, "summary": (s.get("note") or text).strip(), "fields": {}, "links": {}, "where": kind, "quote": text}
        if kind == "event":
            if s.get("by"):
                target = ref(s["by"], "event %r" % text, ("aggregate",))
                if target:
                    item["links"]["emitted_by"] = [target]
            if s.get("payload"):
                item["fields"]["payload"] = _list(s["payload"])
            index = events.index(s)
            if index + 1 < len(events):
                item["links"]["precedes"] = [ids[events[index + 1]["text"].lower()]]
        elif kind == "command":
            if s.get("handled_by"):
                target = ref(s["handled_by"], "command %r" % text, ("aggregate",))
                if target:
                    item["links"]["handled_by"] = [target]
            else:
                gaps.append("command %r names no aggregate (handled_by): the vocabulary requires one, and the gate will say so" % text)
            raised = [ref(e, "command %r" % text, ("event",)) for e in _list(s.get("raises"))]
            if any(raised):
                item["links"]["raises"] = [r for r in raised if r]
            if s.get("actor"):
                target = ref(s["actor"], "command %r" % text, ("actor",))
                if target:
                    item["fields"]["trigger_kind"] = "actor"
                    item["links"]["triggered_by"] = [target]
            elif text.lower() in policies_then:
                item["fields"]["trigger_kind"] = "policy"
                item["links"]["triggered_by"] = [ids[policies_then[text.lower()]["text"].lower()]]
            elif text.lower() in sent_by:
                item["fields"]["trigger_kind"] = "external_system"
                item["links"]["triggered_by"] = [ids[sent_by[text.lower()]["text"].lower()]]
            if s.get("schedule"):
                item["fields"]["trigger_kind"] = "timer"
                item["fields"]["schedule"] = str(s["schedule"])
            if s.get("payload"):
                item["fields"]["payload"] = _list(s["payload"])
        elif kind == "aggregate":
            root = {"type": "Entity", "id": sid + "-root", "label": "%s (root)" % text, "summary": "The root entity of the %s aggregate." % text,
                    "fields": {}, "links": {}, "where": kind, "quote": text}
            items.append(root)
            item["links"]["root"] = [root["id"]]
        elif kind == "policy":
            if s.get("when"):
                target = ref(s["when"], "policy %r" % text, ("event",))
                if target:
                    item["links"]["reacts_to"] = [target]
            if s.get("then"):
                target = ref(s["then"], "policy %r" % text, ("command",))
                if target:
                    item["links"]["issues"] = [target]
            if s.get("condition"):
                item["fields"]["condition"] = str(s["condition"])
        elif kind == "read model":
            if s.get("fields"):
                item["fields"]["fields"] = _list(s["fields"])
            projected = [ref(e, "read model %r" % text, ("event",)) for e in _list(s.get("from"))]
            if any(projected):
                item["links"]["projected_from"] = [p for p in projected if p]
            if s.get("consulted_by"):
                target = ref(s["consulted_by"], "read model %r" % text, ("actor",))
                if target:
                    item["links"]["consulted_by"] = [target]
            informs = [ref(c, "read model %r" % text, ("command",)) for c in _list(s.get("informs"))]
            if any(informs):
                item["links"]["informs"] = [i for i in informs if i]
        elif kind == "external system":
            sends = [ref(t, "external system %r" % text, ("command", "event")) for t in _list(s.get("sends"))]
            if any(sends):
                item["links"]["sends"] = [x for x in sends if x]
            receives = [ref(t, "external system %r" % text, ("event",)) for t in _list(s.get("receives"))]
            if any(receives):
                item["links"]["receives"] = [x for x in receives if x]
            item["links"]["integrated_by"] = [context]
        elif kind == "hot spot":
            item["fields"]["state"] = "open"
            if board.get("held_on") and ISO_DATE.match(str(board["held_on"])):
                item["fields"]["raised_on"] = board["held_on"]
            if s.get("about"):
                target = ref(s["about"], "hot spot %r" % text)
                if target:
                    item["links"]["about"] = [target]
        if item["type"] in IN_CONTEXT:
            item["links"]["part_of"] = [context]
        items.append(item)
    return {"doc": doc, "as_of": at, "items": items}, gaps


def storm(project, path, at, name=None, context_id=None):
    """Read the board, write the document and the capture. Returns {"doc", "document", "archive",
    "capture", "stickies", "items", "gaps"}."""
    if not at or not ISO_DATE.match(str(at)):
        raise DddError("--at YYYY-MM-DD is required: the date the board was read is never defaulted")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if "DomainEvent" not in classes or "BoundedContext" not in classes:
        raise DddError("the vocabulary declares no DomainEvent and BoundedContext: the ddd ontology does (oto init --ontology ddd, or compose it)")
    if not os.path.isfile(path):
        raise DddError("no such board: %s" % path)
    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except ValueError as exc:
            raise DddError("%s is not JSON: %s" % (path, exc))
    board = read_board(raw)
    if context_id:
        from ...naming import graph_ids as _graph_ids
        if context_id not in _graph_ids(project):
            raise DddError("the graph holds no %s: --context names a BoundedContext the graph holds" % context_id)
    doc = "storm-%s" % (_slug(name) if name else _slug(board.get("context") or board["session"]))
    source = os.path.basename(path)
    title, text = document(board, doc, at, source)
    cap, gaps = capture(board, doc, at, context_id=context_id)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    out_dir = os.path.join(project.data, "captures")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cap, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "capture": out, "stickies": len(board["stickies"]), "items": len(cap["items"]), "gaps": gaps,
            "context": context_id or next(i["id"] for i in cap["items"] if i["type"] == "BoundedContext")}
