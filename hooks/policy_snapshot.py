#!/usr/bin/env python3
"""The policy snapshot as a guard reads it (roadmap E3): plain Python over the standard library, the
same file in the engine plugin (hooks/) and in any plugin whose guard reads the snapshot (the
factory's, in Cynergis/oto-factory), byte for byte.

`oto policy snapshot --agent <id> --principal <id>` writes `.factory/policy.json`: the intersection of
what an agent and the principal it runs for may do, the write paths it reaches and the paths it is
denied, a hash over the content and, when the project signs, an HMAC-SHA256 signature naming the
environment variable that holds the key. A guard loads it, checks the hash, that it has not
expired (`expires_at`) and the signature when that variable is set here, and decides one tool call: a write under a denied path is refused naming
the rule, a write under no permitted path is refused naming what is permitted, a shell command that
writes under a denied path is refused; everything else passes. A refusal is appended to
`events.jsonl` beside the snapshot, for `oto policy denials` (or a run's own sync) to turn into
audit records.
"""
import datetime
import fnmatch
import hashlib
import hmac
import json
import os
import re

NAME = "policy.json"
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITE_MARKERS = re.compile(r"(^|[\s;|&(])(rm|mv|cp|tee|touch|truncate|chmod|chown|sed\s+-i|perl\s+-i|dd|install)\b|>>?|git\s+(checkout|restore|rm|mv)\b")


def where(cwd):
    """The snapshot's path: $OTO_POLICY_SNAPSHOT, else <cwd>/.factory/policy.json."""
    return os.environ.get("OTO_POLICY_SNAPSHOT") or os.path.join(cwd, ".factory", NAME)


def load(path):
    """(snapshot, None), or (None, why) when the file cannot be read or is not a snapshot."""
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError) as exc:
        return None, "%s cannot be read (%s): what is permitted is unknown, so nothing is. Write it again with `oto policy snapshot`" % (path, exc)
    if not isinstance(snap, dict) or not isinstance(snap.get("scopes"), dict) or "hash" not in snap:
        return None, "%s is not a policy snapshot: it names no scopes or no hash. Write it with `oto policy snapshot --agent <id> --principal <id>`" % path
    return snap, None


def content_hash(snap):
    body = {k: v for k, v in snap.items() if k not in ("hash", "signature")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def check(snap):
    """None when the snapshot is the one the engine wrote; why not otherwise. The signature is
    checked when the variable it names is set here; without it, the hash alone."""
    if content_hash(snap) != snap.get("hash"):
        return "the snapshot's hash is not its content's: it was edited since `oto policy snapshot` wrote it, so nothing in it is trusted"
    stamp = snap.get("expires_at")
    if stamp:
        try:
            when = datetime.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            when = None
        if when is None or datetime.datetime.now(datetime.timezone.utc) >= when:
            return "the snapshot expired at %s: nothing in it is trusted any more; write it again with `oto policy snapshot`" % stamp
    signature = snap.get("signature")
    if isinstance(signature, dict) and signature.get("key"):
        key = os.environ.get(signature["key"] or "")
        if key:
            expected = hmac.new(key.encode("utf-8"), str(snap.get("hash")).encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, str(signature.get("value") or "")):
                return "the snapshot's signature does not verify with the key in %s: it is not the one the project signed" % signature["key"]
    return None


def relative(path, cwd):
    path = str(path).replace("\\", "/")
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, cwd)
        except ValueError:
            return path
    path = os.path.normpath(path).replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def within(path, patterns):
    for p in patterns or []:
        p = str(p).strip().strip("/")
        if not p:
            continue
        if path == p or path.startswith(p + "/") or fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p + "/*"):
            return True
    return False


def _rule_for(snap, path):
    """The forbid whose component reaches `path`, by id, when one does."""
    for f in snap.get("forbids") or []:
        for p in f.get("paths") or []:
            if within(path, [p]):
                return (f.get("via") or {}).get("principal") or (f.get("via") or {}).get("agent")
    return None


def decide(snap, tool, tool_input, cwd):
    """(allowed, reason, rule, action, path) for one tool call."""
    scopes = snap.get("scopes") or {}
    write, denied = scopes.get("write") or [], scopes.get("denied") or []
    agent, principal = (snap.get("agent") or {}).get("id"), (snap.get("principal") or {}).get("id")
    tool_input = tool_input or {}
    if tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not path:
            return True, None, None, "write", None
        rel = relative(path, cwd)
        if within(rel, denied):
            rule = _rule_for(snap, rel)
            return False, "%s is denied to %s running for %s: forbidden by %s" % (rel, agent, principal, rule or "the policy"), rule, "write", rel
        if rel.startswith("../") or not within(rel, write):
            return False, ("%s is outside every path the policy permits %s to write for %s: %s. No rule permits it; ask for a rule, never for the guard to look away"
                           % (rel, agent, principal, ", ".join(write) or "nothing")), None, "write", rel
        return True, None, None, "write", rel
    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if WRITE_MARKERS.search(command):
            for p in denied:
                p = str(p).strip().strip("/")
                if p and re.search(r"(^|[\s'\"=/])%s(/|\b)" % re.escape(p), command):
                    rule = _rule_for(snap, p)
                    return False, "the command touches %s, denied to %s running for %s, with a verb that writes: forbidden by %s" % (p, agent, principal, rule or "the policy"), rule, "write", p
        return True, None, None, "run", None
    return True, None, None, "read", None


def record(snapshot_path, snap, tool, action, path, rule):
    """One line appended to events.jsonl beside the snapshot: a refusal, for the audit log."""
    line = {"event": "denied", "tool": tool, "action": action, "path": path, "rule": rule,
            "agent": (snap.get("agent") or {}).get("id"), "principal": (snap.get("principal") or {}).get("id"),
            "snapshot": snap.get("hash"), "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        with open(os.path.join(os.path.dirname(snapshot_path), "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass
    return line


def guard(payload, refuse):
    """The whole decision for a hook: returns None to allow, or calls `refuse(reason)`. With no
    snapshot in the directory, the session is not guarded by the policy."""
    cwd = payload.get("cwd") or os.getcwd()
    path = where(cwd)
    if not os.path.isfile(path):
        return None
    snap, problem = load(path)
    if problem:
        refuse(problem)
        return None
    problem = check(snap)
    if problem:
        refuse(problem)
        return None
    allowed, reason, rule, action, target = decide(snap, payload.get("tool_name") or "", payload.get("tool_input") or {}, cwd)
    if not allowed:
        record(path, snap, payload.get("tool_name") or "", action, target, rule)
        refuse(reason)
    return None
