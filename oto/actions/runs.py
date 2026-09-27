# -*- coding: utf-8 -*-
"""Run records: the caller invoked an action and hands OTO the response. OTO writes the record,
a source document for the inbox, and, for a `proposal` result, the proposal that realises what
the action's `then` clause says. Nothing here writes `graph.json`; the proposal goes through the
curate gates like any other.

    runs/actions/<action-id>/<stamp>/run.json       what was invoked, on what, by whom, when, the
                                                    bound inputs, the response's hash and size
    runs/actions/<action-id>/<stamp>/response.json  the response as handed over (or .txt)
    inbox/<at>-run-<action>-<subject>.md            the run as a source document: ingest it, and
                                                    the facts the run asserted cite it
    proposals/<action-id>.<stamp>.json              for a `proposal` result: the subject as the
                                                    `then` clause says, evidence pointing at the
                                                    run document

At build time the records give each Action node its `acts_on` edges and its `last_run`.
Environment variable values are never seen here; the record holds the names the action needs.
"""
import datetime
import hashlib
import json
import os
import re

from ..intake.document import slugify

DIR = os.path.join("runs", "actions")
RESPONSE_REF = re.compile(r"^\$response(?:\.(.+))?$")
QUOTE_LIMIT = 200
RESPONSE_LIMIT = 2_000_000
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def directory(project, action_id=None):
    base = os.path.join(project.data, DIR)
    return os.path.join(base, action_id) if action_id else base


def response_path(response, path):
    """`$response.a.b.0` over a parsed response; None when the path does not resolve."""
    m = RESPONSE_REF.match(path or "")
    if not m:
        return None
    value = response
    for part in (m.group(1) or "").split("."):
        if part == "":
            continue
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
        if value is None:
            return None
    return value


def _stamp(base_dir, at):
    """<at>-<n>, unique within the action's run directory."""
    n, stamp = 1, at
    while os.path.exists(os.path.join(base_dir, stamp)):
        n += 1
        stamp = "%s-%d" % (at, n)
    return stamp


def document_name(action, subject, at):
    return "%s-run-%s-%s.md" % (at, slugify(action["id"].split(".", 1)[-1])[:40], slugify(subject.get("label") or subject["id"])[:40])


def document_text(action, subject, at, by, inputs, response, ready, note=None):
    """The run as a source document, in the shape a captured note has: dated, attributed, quotable."""
    invoke = action.get("invoke") or {}
    lines = ["# Run of %s on %s" % (action.get("label") or action["id"], subject.get("label") or subject["id"]), "",
             "> **Run:** %s · **By:** %s · **Action:** `%s` · **On:** `%s`" % (at, by, action["id"], subject["id"]),
             ">", "> This document records one invocation of an action the graph declares, performed by the "
             "person named above, and the response it returned. It is a source document: a fact the run "
             "asserted cites it, and the person named is who to ask.", ""]
    if not ready:
        lines += ["> **Note:** the action's preconditions did not hold on this entity when the run was recorded.", ""]
    lines += ["## Action", "",
              "- id: `%s`" % action["id"],
              "- invoke: %s %s" % (invoke.get("transport", "?"), ", ".join("%s=%s" % (k, v) for k, v in sorted(invoke.items()) if k != "transport")),
              "- needs (names only): %s" % (", ".join(action.get("needs") or []) or "nothing"),
              "- read-only: %s" % ("yes" if (action.get("annotations") or {}).get("readOnlyHint") else "no"), "",
              "## Inputs", "", "```json", json.dumps(inputs, indent=2, ensure_ascii=False, sort_keys=True), "```", "",
              "## Response", ""]
    if isinstance(response, (dict, list)):
        lines += ["```json", json.dumps(response, indent=2, ensure_ascii=False, sort_keys=True), "```"]
    else:
        lines += ["```", str(response).rstrip(), "```"]
    if note:
        lines += ["", "## Note", "", note.strip()]
    return "\n".join(lines) + "\n"


def render_then(action, subject, response, at, doc_slug):
    """The proposal a `proposal` result asserts about the subject: (proposal dict, unresolved paths)."""
    then = ((action.get("result") or {}).get("then")) or {}
    node = {"id": subject["id"], "type": subject.get("type")}
    unresolved = []
    if then.get("status"):
        node["status"] = then["status"]
        if then["status"] == "current" and subject.get("status") == "intended":
            node["valid_from"] = at                       # the plan became real on the day it was observed
    attributes = {}
    for name, source in (then.get("attributes") or {}).items():
        if isinstance(source, str) and source.startswith("$response"):
            value = response_path(response, source)
            if value is None:
                unresolved.append(source)
                continue
            attributes[name] = value
        else:
            attributes[name] = source
    if attributes:
        node["attributes"] = attributes
    node["as_of"] = at
    node["source_doc"] = doc_slug
    node["sources"] = [doc_slug]
    quote = json.dumps(attributes if attributes else response, ensure_ascii=False, sort_keys=True)
    node["evidence"] = [{"doc": doc_slug, "where": "response", "quote": quote[:QUOTE_LIMIT]}]
    proposal = {"source_doc": doc_slug, "as_of": at,
                "note": "recorded run of %s on %s" % (action["id"], subject["id"]),
                "nodes": [node], "edges": []}
    return proposal, unresolved


def record(project, action, subject, response, by, at, ready, inputs, inputs_missing, note=None):
    """Write the run record, the inbox document and, for a proposal result, the proposal.
    Returns the record dict, whose paths are relative to the project."""
    if not ISO_DATE.match(at or ""):
        raise ValueError("--at must be a YYYY-MM-DD date")
    if not (by or "").strip():
        raise ValueError("--by is required: an unattributed run cannot be followed up")
    raw_size = len(json.dumps(response, ensure_ascii=False) if isinstance(response, (dict, list)) else str(response))
    if raw_size > RESPONSE_LIMIT:
        raise ValueError("the response is %d characters; a run record keeps at most %d. Keep the raw file where it is "
                         "and hand over the part the action's result needs" % (raw_size, RESPONSE_LIMIT))
    base = directory(project, action["id"])
    os.makedirs(base, exist_ok=True)
    stamp = _stamp(base, at)
    run_dir = os.path.join(base, stamp)
    os.makedirs(run_dir)
    raw = json.dumps(response, ensure_ascii=False, sort_keys=True) if isinstance(response, (dict, list)) else str(response)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    response_file = "response.json" if isinstance(response, (dict, list)) else "response.txt"
    with open(os.path.join(run_dir, response_file), "w", encoding="utf-8", newline="\n") as f:
        f.write(raw if response_file == "response.txt" else json.dumps(response, indent=2, ensure_ascii=False, sort_keys=True))
        f.write("\n")

    os.makedirs(project.layout.inbox, exist_ok=True)
    doc_name = document_name(action, subject, at)
    doc_path = os.path.join(project.layout.inbox, doc_name)
    n = 1
    while os.path.exists(doc_path):
        n += 1
        doc_path = os.path.join(project.layout.inbox, doc_name[:-3] + "-%d.md" % n)
    doc_slug = slugify(os.path.basename(doc_path))
    with open(doc_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(document_text(action, subject, at, by, inputs, response, ready, note))

    kind = (action.get("result") or {}).get("kind")
    proposal_rel, unresolved, withheld = None, [], None
    if kind == "proposal":
        if not isinstance(response, dict):
            unresolved = ["the response is not a JSON object; nothing to render from it"]
        parsed = response if isinstance(response, dict) else {}
        missing = [path for path in ((action.get("result") or {}).get("require") or []) if response_path(parsed, path) is None]
        if missing or not isinstance(response, dict):
            withheld = ("the response does not confirm the fact: %s not present; the run is recorded, no proposal is written"
                        % ", ".join(missing or ["a JSON object"]))
        else:
            proposal, unresolved_paths = render_then(action, subject, parsed, at, doc_slug)
            unresolved += unresolved_paths
            os.makedirs(os.path.join(project.data, "proposals"), exist_ok=True)
            proposal_rel = os.path.join("proposals", "%s.%s.json" % (action["id"], stamp))
            with open(os.path.join(project.data, proposal_rel), "w", encoding="utf-8", newline="\n") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)
                f.write("\n")

    record_ = {"action": action["id"], "on": subject["id"], "subject_type": subject.get("type"), "by": by.strip(),
               "at": at, "stamp": stamp, "recorded_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
               "ready": bool(ready), "inputs": inputs, "inputs_missing": list(inputs_missing or []),
               "invoke": action.get("invoke"), "needs": list(action.get("needs") or []),
               "response_file": response_file, "response_sha256": digest, "response_bytes": len(raw.encode("utf-8")),
               "result_kind": kind, "document": os.path.relpath(doc_path, project.data), "document_slug": doc_slug,
               "proposal": proposal_rel, "unresolved": unresolved, "withheld": withheld, "note": note or None}
    with open(os.path.join(run_dir, "run.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(record_, f, indent=2, ensure_ascii=False)
        f.write("\n")
    record_["directory"] = os.path.relpath(run_dir, project.data)
    return record_


def all_runs(project):
    """Every run record, oldest first: [(relative directory, record)]. Unreadable ones are skipped."""
    base = directory(project)
    out = []
    if not os.path.isdir(base):
        return out
    for action_id in sorted(os.listdir(base)):
        action_dir = os.path.join(base, action_id)
        if not os.path.isdir(action_dir):
            continue
        for stamp in sorted(os.listdir(action_dir)):
            path = os.path.join(action_dir, stamp, "run.json")
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("action") and rec.get("on"):
                out.append((os.path.relpath(os.path.dirname(path), project.data), rec))
    return out


def last_runs(project):
    """{action id: {at, on, by, stamp, ready, result_kind, runs}}: the latest run per action."""
    out = {}
    for rel, rec in all_runs(project):
        current = out.get(rec["action"])
        summary = {"at": rec.get("at"), "on": rec["on"], "by": rec.get("by"), "stamp": rec.get("stamp"),
                   "ready": rec.get("ready"), "result_kind": rec.get("result_kind"), "directory": rel,
                   "recorded_at": rec.get("recorded_at"),
                   "runs": (current["runs"] + 1) if current else 1}
        out[rec["action"]] = summary
    return out


def acts_on_edges(project):
    """One `acts_on` edge per (action, subject) pair a run recorded."""
    seen, out = set(), []
    for _rel, rec in all_runs(project):
        key = (rec["action"], rec["on"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": rec["action"], "rel": "acts_on", "to": rec["on"]})
    return out
