# -*- coding: utf-8 -*-
"""The audit log: one append-only, hash-chained record per write (roadmap F2, F3).

The project already keeps records a person reads: `assertions.jsonl` (what was said),
`changelog.jsonl` (what was applied and why), `PROMOTIONS.jsonl` (what each environment holds).
This log is the one an auditor reads. Every path that changes what the project believes appends a
record keyed to the nodes it touched, and a refusal at the gates appends one too, because "who
tried what, and was it allowed" is the question accountability asks.

    audit.jsonl     one JSON object per line, never rewritten

    seq         1, 2, 3 ...
    at          when, ISO
    principal   who: the person named (--by), else the project's git identity
    agent       through what: the engine's version and the command
    action      what kind of write: "work set", "curate apply", "publish", "promote", ...
    nodes       the ids the write touched
    graph       a hash of the graph file after the write: the version of what the project believes
    decision    "applied", "refused", "promoted", ...
    detail      one line, in words
    trace_id    the operation's trace (F1); None until tracing is on
    prev        the previous record's hash ("" for the first)
    hash        sha256 of this record without `hash`, canonical JSON

`verify` walks the chain: a record whose hash is not what its fields give was edited; a record whose
`prev` is not the previous record's hash follows a removal or a reordering. It names the first such
record. A chain detects what was changed inside it; what was cut from its end only a copy elsewhere
can show, which is what the promotion record on the query repository's branches is for.
"""
import datetime
import hashlib
import json
import os

NAME = "audit.jsonl"
GRAPH_HASH_CHARS = 16


def path(project):
    return os.path.join(project.data, NAME)


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def digest(record):
    """The hash of a record: sha256 over its fields but `hash`, as canonical JSON."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def graph_version(project):
    """A short hash of the graph file as it stands: the version of what the project believes."""
    try:
        with open(project.graph_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:GRAPH_HASH_CHARS]
    except OSError:
        return None


def agent(action=None):
    from . import __version__
    return "oto %s%s" % (__version__, (" " + action) if action else "")


def read(project):
    """Every record, in order; a line that is not a record reads as {"seq": None, "raw": ...}."""
    p = path(project)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                record = None
            if not isinstance(record, dict) or "hash" not in record:
                out.append({"seq": None, "line": number, "raw": line[:120]})
            else:
                out.append(record)
    return out


def append(project, action, principal, nodes, decision, detail=None, trace_id=None):
    """Append one record and return it. The chain is read from the file, so two writers in turn
    produce one chain; the file is opened for append and written in one call."""
    if trace_id is None:
        from . import tracing
        trace_id = tracing.current_trace_id()
    records = read(project)
    last = records[-1] if records else None
    record = {"seq": (last.get("seq") or len(records)) + 1 if last else 1, "at": _now(),
              "principal": (principal or "").strip() or "(unnamed)", "agent": agent(action), "action": action,
              "nodes": sorted(set(n for n in (nodes or []) if n)), "graph": graph_version(project),
              "decision": decision, "detail": (detail or "").strip() or None, "trace_id": trace_id,
              "prev": (last or {}).get("hash") or ""}
    record["hash"] = digest(record)
    with open(path(project), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def verify(project):
    """{"ok", "records", "broken": the seq (or position) of the first record that does not chain, "why"}."""
    records = read(project)
    prev = ""
    for position, record in enumerate(records, 1):
        if record.get("seq") is None:
            return {"ok": False, "records": len(records), "broken": position, "why": "line %s is not a record" % record.get("line")}
        if record.get("hash") != digest(record):
            return {"ok": False, "records": len(records), "broken": record["seq"],
                    "why": "its hash is not what its fields give: the record was edited"}
        if record.get("prev", "") != prev:
            return {"ok": False, "records": len(records), "broken": record["seq"],
                    "why": "its prev is not the previous record's hash: a record before it was removed or the order changed"}
        if record.get("seq") != position:
            return {"ok": False, "records": len(records), "broken": record["seq"], "why": "its seq is %d at position %d" % (record["seq"], position)}
        prev = record["hash"]
    return {"ok": True, "records": len(records), "broken": None, "why": None}


def for_node(project, node_id):
    """The records that touched `node_id`, in order."""
    return [r for r in read(project) if node_id in (r.get("nodes") or [])]


def render(records, limit=50):
    """Records as text, one per line, newest last."""
    lines = []
    for r in records[-limit:]:
        if r.get("seq") is None:
            lines.append("  (line %s is not a record)" % r.get("line"))
            continue
        lines.append("  %4d  %s  %-14s %-8s %s%s" % (r["seq"], r["at"], r["action"], r["decision"],
                                                   ", ".join(r["nodes"][:4]) + (" +%d" % (len(r["nodes"]) - 4) if len(r["nodes"]) > 4 else ""),
                                                   ("  — " + r["detail"]) if r.get("detail") else ""))
        lines.append("        by %s, through %s, graph %s" % (r["principal"], r["agent"], r.get("graph") or "?"))
    return "\n".join(lines)
