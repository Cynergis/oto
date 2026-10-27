# -*- coding: utf-8 -*-
"""`oto policy`: the access policy the graph holds, compiled into a bundle (roadmap E2).

The policy pack (ontologies/policy) says a `PolicyRule` permits or forbids one `Permission` (an
action on a kind of resource, narrowed by a selector over the resource's attributes) for the roles
and teams it names, on every resource the selector admits or only on those it singles out. Only an
active rule compiles; a draft nobody activated and a retired rule are left out, and a rule that
cannot compile (a permission on a class the vocabulary does not declare, a selector that is not
`key=value`) is named and left out, never guessed at.

The bundle, `build/policy/` by default, is three files:

    policies.cedar   the rules in Cedar (ADR-0004), one policy per rule and principal, annotated with
                     the rule's id, its rationale as a comment
    policies.json    the same rules as plain data, for the engine's evaluator and the hooks, which
                     stay plain Python and need no Cedar engine
    manifest.json    bundle_version, generated_at, version (build_seq, graph hash, ontology version),
                     the rule count, what could not compile, the sha256 of each file, a hash of the
                     content, and a signature when the project names a key

The signature is HMAC-SHA256 over the content hash with the key the named environment variable
holds; the manifest names the variable, never the key. `verify` checks the files against the
manifest and, given the variable, the signature against the key; without the variable it reports
the signature and checks the hashes alone.
"""
import datetime
import hashlib
import hmac
import json
import os
import re

from .project import ProjectError

BUNDLE_VERSION = 1
CLASS = "PolicyRule"
ACTIVE = "active"
DEFAULT_STATUS = "draft"
FILES = ("policies.cedar", "policies.json", "manifest.json")
PRINCIPAL_TYPES = ("Role", "Team")


class PolicyError(ProjectError):
    pass


def _attrs(node):
    a = node.get("attributes")
    return a if isinstance(a, dict) else {}


def _typed(value):
    """A selector value as data: true, false, a number, else the text."""
    text = str(value).strip()
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_selector(items):
    """[{key, op, value}] from `key=value` and `key!=value`; raises ValueError naming the bad one."""
    out = []
    for item in items or []:
        text = str(item)
        if "!=" in text:
            key, _sep, value = text.partition("!=")
            op = "!="
        elif "=" in text:
            key, _sep, value = text.partition("=")
            op = "=="
        else:
            raise ValueError("selector %r is not key=value or key!=value" % text)
        if not key.strip():
            raise ValueError("selector %r names no attribute" % text)
        out.append({"key": key.strip(), "op": op, "value": _typed(value)})
    return out


def _ref(node):
    return {"id": node["id"], "type": node.get("type"), "label": node.get("label") or node["id"]}


def compile(graph, classes=None):
    """The active rules as data: {bundle_version, rules, problems, roles, permissions}. `classes` is
    the vocabulary's classes; without it, the classes the graph uses."""
    nodes = [n for n in (graph.get("nodes") or []) if (n.get("status") or "current") == "current"]
    by_id = {n["id"]: n for n in nodes}
    known = set(classes) if classes else {n.get("type") for n in nodes}
    out_edges = {}
    for e in graph.get("edges") or []:
        if (e.get("status") or "current") == "current":
            out_edges.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
    rules, problems, roles, permissions = [], [], {}, {}
    for n in sorted(nodes, key=lambda n: n["id"]):
        if n.get("type") != CLASS:
            continue
        a = _attrs(n)
        if (a.get("status") or DEFAULT_STATUS) != ACTIVE:
            continue
        rule_problems = []
        if a.get("effect") not in ("permit", "forbid"):
            rule_problems.append("%s: effect is %r, not permit or forbid" % (n["id"], a.get("effect")))
        principals = [by_id[t] for t in out_edges.get((n["id"], "for_role"), []) if t in by_id]
        if not principals:
            rule_problems.append("%s: names no role or team (for_role)" % n["id"])
        targets = [by_id[t] for t in out_edges.get((n["id"], "of_permission"), []) if t in by_id]
        if len(targets) != 1:
            rule_problems.append("%s: names %d permissions; a rule has exactly one (of_permission)" % (n["id"], len(targets)))
        permission = None
        if len(targets) == 1:
            p = targets[0]
            pa = _attrs(p)
            try:
                selector = parse_selector(pa.get("selector"))
            except ValueError as exc:
                selector = None
                rule_problems.append("%s: permission %s: %s" % (n["id"], p["id"], exc))
            if not pa.get("action"):
                rule_problems.append("%s: permission %s has no action" % (n["id"], p["id"]))
            if not pa.get("resource_class"):
                rule_problems.append("%s: permission %s has no resource_class" % (n["id"], p["id"]))
            elif pa["resource_class"] not in known:
                rule_problems.append("%s: permission %s is on %r, which the vocabulary does not declare" % (n["id"], p["id"], pa["resource_class"]))
            if selector is not None:
                permission = {"id": p["id"], "label": p.get("label") or p["id"], "action": pa.get("action"),
                              "resource_class": pa.get("resource_class"), "selector": selector}
        resources = [_ref(by_id[t]) for t in out_edges.get((n["id"], "singles_out"), []) if t in by_id]
        if rule_problems:
            problems.extend(rule_problems)
            continue
        rule = {"id": n["id"], "label": n.get("label") or n["id"], "effect": a["effect"], "priority": int(a.get("priority") or 0),
                "rationale": a.get("rationale") or "", "roles": [_ref(p) for p in principals], "permission": permission,
                "resources": sorted(resources, key=lambda r: r["id"])}
        rules.append(rule)
        for p in principals:
            roles[p["id"]] = _ref(p)
        permissions[permission["id"]] = permission
    rules.sort(key=lambda r: (-r["priority"], r["id"]))
    return {"bundle_version": BUNDLE_VERSION, "rules": rules, "problems": problems,
            "roles": [roles[k] for k in sorted(roles)], "permissions": [permissions[k] for k in sorted(permissions)]}


# ---- Cedar ----

def _literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def cedar(doc):
    """The compiled rules as Cedar text: one policy per rule and principal."""
    lines = ["// %d active rule(s) of the access policy, compiled by oto policy compile (ADR-0004). Edit the graph, not this file."
             % len(doc.get("rules") or []), ""]
    for rule in doc.get("rules") or []:
        p = rule["permission"]
        conditions = " && ".join("resource.%s %s %s" % (c["key"], c["op"], _literal(c["value"])) for c in p["selector"])
        if rule["resources"]:
            resource = "resource in [%s]" % ", ".join('%s::"%s"' % (r["type"], r["id"]) for r in rule["resources"])
        else:
            resource = "resource is %s" % p["resource_class"]
        for who in rule["roles"]:
            lines.append("// %s: %s%s" % (rule["id"], rule["label"], (" — " + rule["rationale"]) if rule["rationale"] else ""))
            lines.append('@id("%s")' % rule["id"])
            lines.append("%s (" % rule["effect"])
            lines.append('  principal in %s::"%s",' % (who["type"], who["id"]))
            lines.append('  action == Action::"%s",' % p["action"])
            lines.append("  %s" % resource)
            lines.append(")" + (" when { %s };" % conditions if conditions else ";"))
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# ---- the bundle ----

def content_hash(doc):
    """sha256 over the canonical JSON of the policies file's content."""
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _sign(content, key_env):
    key = os.environ.get(key_env or "")
    if not key:
        raise PolicyError("the bundle is to be signed with the key in %s, which is not set: export it, or drop `policy.sign_with` from project.config.json" % key_env)
    return {"algorithm": "HMAC-SHA256", "key": key_env,
            "value": hmac.new(key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256).hexdigest()}


def bundle(graph, out_dir, version=None, at=None, key_env=None, classes=None):
    """Write policies.cedar, policies.json and manifest.json into `out_dir`; return the manifest."""
    doc = compile(graph, classes)
    at = at or datetime.date.today().isoformat()
    policies = {"bundle_version": BUNDLE_VERSION, "generated_at": at, "version": dict(version or {}),
                "rules": doc["rules"], "roles": doc["roles"], "permissions": doc["permissions"], "problems": doc["problems"]}
    signature = _sign(content_hash(policies), key_env) if key_env else None
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "policies.cedar"), "w", encoding="utf-8", newline="\n") as f:
        f.write(cedar(doc))
    with open(os.path.join(out_dir, "policies.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(policies, f, indent=2, ensure_ascii=False)
        f.write("\n")
    manifest = {"bundle_version": BUNDLE_VERSION, "generated_at": at, "version": dict(version or {}), "rules": len(doc["rules"]),
                "problems": doc["problems"], "files": {name: _file_hash(os.path.join(out_dir, name)) for name in ("policies.cedar", "policies.json")},
                "hash": content_hash(policies), "signature": signature}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return manifest


def read_manifest(out_dir):
    path = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(path):
        raise PolicyError("no bundle at %s: `oto policy compile` writes one, as does `oto build` when the vocabulary declares %s" % (out_dir, CLASS))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify(out_dir, key_env=None):
    """[] when every file is the one the manifest names, the content hash holds and, with a key, the
    signature verifies; the problems otherwise."""
    try:
        manifest = read_manifest(out_dir)
    except (PolicyError, ValueError) as exc:
        return [str(exc)]
    problems = []
    for name, expected in (manifest.get("files") or {}).items():
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            problems.append("%s is missing" % name)
        elif _file_hash(path) != expected:
            problems.append("%s is not the file the manifest names: it was edited since the bundle was written" % name)
    content = manifest.get("content") or "policies.json"        # the bindings bundle (oto/iam.py) hashes bindings.json
    path = os.path.join(out_dir, content)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                policies = json.load(f)
        except ValueError:
            policies = None
        if policies is not None and content_hash(policies) != manifest.get("hash"):
            problems.append("%s: the content hash is not the manifest's" % content)
    signature = manifest.get("signature")
    if signature and key_env:
        if signature.get("key") != key_env:
            problems.append("the signature was made with the key in %s, not %s" % (signature.get("key"), key_env))
        else:
            key = os.environ.get(key_env or "")
            if not key:
                problems.append("the signature names the key in %s, which is not set" % key_env)
            elif hmac.new(key.encode("utf-8"), str(manifest.get("hash")).encode("utf-8"), hashlib.sha256).hexdigest() != signature.get("value"):
                problems.append("the signature does not verify with the key in %s" % key_env)
    return problems


def describe(manifest):
    """One line about a bundle."""
    signature = manifest.get("signature")
    return "%d rule(s), hash %s, %s" % (manifest.get("rules", 0), str(manifest.get("hash"))[:12],
                                        ("signed with %s" % signature["key"]) if signature else "unsigned")


def describe_snapshot(snap):
    signature = snap.get("signature")
    return "a snapshot for %s running for %s, %d permit(s), %d forbid(s), hash %s, expires %s, %s" % (
        (snap.get("agent") or {}).get("id"), (snap.get("principal") or {}).get("id"), len(snap.get("permits") or []), len(snap.get("forbids") or []),
        str(snap.get("hash"))[:12], snap.get("expires_at") or "never", ("signed with %s" % signature["key"]) if signature else "unsigned")


# ---- the snapshot (E3) ----

SNAPSHOT_VERSION = 1
SNAPSHOT_NAME = os.path.join(".factory", "policy.json")
DEFAULT_TTL_HOURS = 24
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def expired(snap, now=None):
    """True when the snapshot's `expires_at` has passed (an unreadable stamp counts as expired)."""
    stamp = snap.get("expires_at")
    if not stamp:
        return False
    try:
        when = datetime.datetime.strptime(str(stamp), STAMP).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return True
    return (now or _utcnow()) >= when


def _holds(value, condition):
    """One selector condition against one attribute value. An absent boolean reads as false (`pii=false`
    admits a table nobody marked); an absent value of any other kind is equal to nothing."""
    wanted = condition["value"]
    if value is None and isinstance(wanted, bool):
        value = False
    if condition["op"] == "==":
        return value is not None and value == wanted
    return value is None or value != wanted


def _admits(selector, node):
    a = _attrs(node)
    return all(_holds(a.get(c["key"]), c) for c in selector or [])


def _principal_of(by_id, out_edges, node_id, wanted, relation, what):
    n = by_id.get(node_id)
    if n is None:
        raise PolicyError("the graph holds no %s" % node_id)
    if n.get("type") != wanted:
        raise PolicyError("%s is a %s, not a %s: a snapshot is for %s" % (node_id, n.get("type"), wanted, what))
    roles = sorted(t for t in out_edges.get((node_id, relation), []) if t in by_id)
    return n, roles


def _side(rules, roles):
    """What one set of roles may do: {permission: {rule, resources}} for permits and for forbids.
    Resources are None when any rule covers every resource its selector admits, else the union."""
    permits, forbids = {}, {}
    for rule in rules:
        if not any(r["id"] in roles for r in rule["roles"]):
            continue
        table = permits if rule["effect"] == "permit" else forbids
        pid = rule["permission"]["id"]
        entry = table.setdefault(pid, {"rule": rule["id"], "permission": rule["permission"], "resources": set(), "all": False})
        if rule["resources"]:
            entry["resources"] |= {r["id"] for r in rule["resources"]}
        else:
            entry["all"] = True
    for table in (permits, forbids):
        for entry in table.values():
            entry["resources"] = None if entry["all"] else sorted(entry["resources"])
    return permits, forbids


def _meet(a, b):
    """The resources two sides share: None (every one) when both say so, else the narrower."""
    if a is None:
        return b
    if b is None:
        return a
    return sorted(set(a) & set(b))


def _paths(graph_index, resource_class, resources, selector):
    """The CodeModule paths reached by a permission on components: the resources named, else every
    current Component the selector admits."""
    by_id, out_edges, nodes = graph_index
    if resource_class != "Component":
        return []
    if resources is None:
        components = [n["id"] for n in nodes if n.get("type") == "Component" and _admits(selector, n)]
    else:
        components = list(resources)
    paths = set()
    for cid in components:
        for mid in out_edges.get((cid, "implemented_by"), []):
            m = by_id.get(mid)
            if m is not None and m.get("type") == "CodeModule" and _attrs(m).get("path"):
                paths.add(str(_attrs(m)["path"]).strip("/"))
    return sorted(paths)


def snapshot(graph, agent_id, principal_id, at=None, version=None, classes=None, ttl_hours=None):
    """The intersection of what an agent and a principal may do, with the paths it reaches. It
    expires `ttl_hours` after it is written (a day by default): a guard and the gates refuse it then."""
    try:
        ttl = float(DEFAULT_TTL_HOURS if ttl_hours is None else ttl_hours)
    except (TypeError, ValueError):
        raise PolicyError("--ttl is the snapshot's time to live in hours, a number above 0: not %r" % (ttl_hours,))
    if ttl <= 0:
        raise PolicyError("--ttl is the snapshot's time to live in hours, a number above 0: a snapshot that never expires is not one, nor one already expired")
    nodes = [n for n in (graph.get("nodes") or []) if (n.get("status") or "current") == "current"]
    by_id = {n["id"]: n for n in nodes}
    out_edges = {}
    for e in graph.get("edges") or []:
        if (e.get("status") or "current") == "current":
            out_edges.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
    agent, agent_roles = _principal_of(by_id, out_edges, agent_id, "Agent", "granted_role", "an agent (--agent) running for a principal (--principal)")
    principal, principal_roles = _principal_of(by_id, out_edges, principal_id, "Principal", "holds_role", "an agent (--agent) running for a principal (--principal)")
    rules = compile(graph, classes)["rules"]
    a_permits, a_forbids = _side(rules, set(agent_roles))
    p_permits, p_forbids = _side(rules, set(principal_roles))
    index = (by_id, out_edges, nodes)
    forbids = []
    for pid in sorted(set(a_forbids) | set(p_forbids)):
        a, p = a_forbids.get(pid), p_forbids.get(pid)
        permission = (a or p)["permission"]
        resources = None if (a and a["resources"] is None) or (p and p["resources"] is None) else sorted(set((a or {}).get("resources") or []) | set((p or {}).get("resources") or []))
        forbids.append({"permission": pid, "action": permission["action"], "resource_class": permission["resource_class"], "selector": permission["selector"],
                        "resources": resources, "via": {"agent": a["rule"] if a else None, "principal": p["rule"] if p else None},
                        "paths": _paths(index, permission["resource_class"], resources, permission["selector"]) if permission["action"] == "write" else []})
    permits = []
    for pid in sorted(set(a_permits) & set(p_permits)):
        if any(f["permission"] == pid and f["resources"] is None for f in forbids):
            continue
        a, p = a_permits[pid], p_permits[pid]
        resources = _meet(a["resources"], p["resources"])
        if resources == []:
            continue
        permission = a["permission"]
        permits.append({"permission": pid, "action": permission["action"], "resource_class": permission["resource_class"], "selector": permission["selector"],
                        "resources": resources, "via": {"agent": a["rule"], "principal": p["rule"]},
                        "paths": _paths(index, permission["resource_class"], resources, permission["selector"]) if permission["action"] == "write" else []})
    write = sorted({path for p in permits for path in p["paths"]})
    denied = sorted({path for f in forbids for path in f["paths"]})
    pa = _attrs(principal)
    now = _utcnow()
    snap = {"snapshot_version": SNAPSHOT_VERSION, "generated_at": at or datetime.date.today().isoformat(), "version": dict(version or {}),
            "written_at": now.strftime(STAMP), "ttl_hours": ttl if ttl != int(ttl) else int(ttl), "expires_at": (now + datetime.timedelta(hours=ttl)).strftime(STAMP),
            "agent": {"id": agent["id"], "label": agent.get("label") or agent["id"], "roles": agent_roles},
            "principal": {"id": principal["id"], "label": principal.get("label") or principal["id"], "kind": pa.get("kind"), "identity": pa.get("identity"),
                          "roles": principal_roles},
            "permits": permits, "forbids": forbids, "scopes": {"write": write, "denied": denied}, "hash": None, "signature": None}
    snap["hash"] = snapshot_hash(snap)
    return snap


def snapshot_hash(snap):
    body = {k: v for k, v in snap.items() if k not in ("hash", "signature")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_snapshot(graph, agent_id, principal_id, out, at=None, version=None, key_env=None, classes=None, ttl_hours=None):
    snap = snapshot(graph, agent_id, principal_id, at=at, version=version, classes=classes, ttl_hours=ttl_hours)
    if key_env:
        snap["signature"] = _sign(snap["hash"], key_env)
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snap, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return snap


def read_snapshot(path):
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, ValueError) as exc:
        raise PolicyError("%s cannot be read as a snapshot: %s" % (path, exc))
    if not isinstance(snap, dict) or "scopes" not in snap or "hash" not in snap:
        raise PolicyError("%s is not a policy snapshot (no scopes, no hash)" % path)
    return snap


def verify_snapshot(path, key_env=None):
    """[] when the snapshot is the one the engine wrote and, with a key, the signature verifies."""
    try:
        snap = read_snapshot(path)
    except PolicyError as exc:
        return [str(exc)]
    problems = []
    if snapshot_hash(snap) != snap.get("hash"):
        problems.append("the snapshot's hash is not its content's: it was edited since `oto policy snapshot` wrote it")
    if expired(snap):
        problems.append("the snapshot expired at %s: write it again with `oto policy snapshot`" % snap.get("expires_at"))
    signature = snap.get("signature")
    if signature and key_env:
        if signature.get("key") != key_env:
            problems.append("the signature was made with the key in %s, not %s" % (signature.get("key"), key_env))
        else:
            key = os.environ.get(key_env or "")
            if not key:
                problems.append("the signature names the key in %s, which is not set" % key_env)
            elif hmac.new(key.encode("utf-8"), str(snap.get("hash")).encode("utf-8"), hashlib.sha256).hexdigest() != signature.get("value"):
                problems.append("the signature does not verify with the key in %s" % key_env)
    return problems


# ---- denials as audit records ----

DENIED_ACTION = "policy denied"


def denial_detail(event):
    rule = event.get("rule")
    return "%s %s %s at %s: %s" % (event.get("tool") or "?", event.get("action") or "write", event.get("path") or "?", event.get("at") or "?",
                                   ("forbidden by %s" % rule) if rule else "no rule permits it")


def denials(project, events_path):
    """Every `denied` event of the file as an audit record of the project, each once.
    Returns {"events", "recorded", "already", "skipped"}."""
    from . import audit as _audit
    if not os.path.isfile(events_path):
        raise PolicyError("no such events file: %s (a guard writes .factory/events.jsonl beside the snapshot)" % events_path)
    seen = {r.get("detail") for r in _audit.read(project) if r.get("action") == DENIED_ACTION}
    counts = {"events": 0, "recorded": 0, "already": 0, "skipped": 0}
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
            if not isinstance(e, dict) or e.get("event") != "denied":
                counts["skipped"] += 1
                continue
            detail = denial_detail(e)
            if detail in seen:
                counts["already"] += 1
                continue
            nodes = [e.get("agent"), e.get("principal")] + ([e["rule"]] if e.get("rule") else [])
            _audit.append(project, DENIED_ACTION, e.get("principal"), nodes, "refused", detail)
            seen.add(detail)
            counts["recorded"] += 1
    return counts


# ---- one decision, the way the snapshot decides (E5) ----

TABLES_IN = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


def tables_in(sql):
    """The table names a SELECT reads: what follows FROM and JOIN, each once, a subquery excluded."""
    out = []
    for name in TABLES_IN.findall(sql or ""):
        if name.lower() not in ("select", "lateral") and name not in out:
            out.append(name)
    return out


def _covers(entry, node):
    return _admits(entry["permission"]["selector"], node) if entry["resources"] is None else node["id"] in entry["resources"]


def decision(graph, principal_id, action, node, agent_id=None, classes=None):
    """(allowed, reason, rule): may the principal (and the agent, when named) do `action` to `node`?
    A permit must cover it on every side named and no forbid may, the way the snapshot decides."""
    nodes = [n for n in (graph.get("nodes") or []) if (n.get("status") or "current") == "current"]
    by_id = {n["id"]: n for n in nodes}
    out_edges = {}
    for e in graph.get("edges") or []:
        if (e.get("status") or "current") == "current":
            out_edges.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
    sides = []
    principal, roles = _principal_of(by_id, out_edges, principal_id, "Principal", "holds_role", "a principal, the one who asks")
    sides.append((principal_id, roles))
    if agent_id:
        agent, agent_roles = _principal_of(by_id, out_edges, agent_id, "Agent", "granted_role", "the agent that asks for a principal")
        sides.append((agent_id, agent_roles))
    rules = [r for r in compile(graph, classes)["rules"] if r["permission"]["action"] == action]
    label = "%s (a %s)" % (node.get("label") or node["id"], node.get("type"))
    for who, held in sides:
        permits, forbids = _side(rules, set(held))
        for entry in forbids.values():
            if _covers(entry, node):
                return False, "%s may not %s %s: forbidden by %s" % (who, action, label, entry["rule"]), entry["rule"]
    for who, held in sides:
        permits, _f = _side(rules, set(held))
        if not any(_covers(entry, node) for entry in permits.values()):
            return False, "no rule permits %s to %s %s" % (who, action, label), None
    return True, None, None


# ---- the re-check before a write (E6) ----

def declared_classes(project):
    """The classes the project's vocabulary declares; the engine asks here so it opens no file of its own."""
    with open(project.ontology_config_path, encoding="utf-8") as f:
        return json.load(f).get("classes") or {}


def settings(project):
    cfg = project.config().get("policy") or {}
    return {"sign_with": cfg.get("sign_with") or None, "require_snapshot": bool(cfg.get("require_snapshot")),
            "ttl_hours": cfg.get("ttl_hours", DEFAULT_TTL_HOURS)}


def snapshot_path():
    """Where the snapshot a session runs under is: $OTO_POLICY_SNAPSHOT, else .factory/policy.json here."""
    return os.environ.get("OTO_POLICY_SNAPSHOT") or os.path.join(os.getcwd(), SNAPSHOT_NAME)


def _same_policy(snap, fresh):
    return all(snap.get(k) == fresh.get(k) for k in ("permits", "forbids", "scopes", "agent", "principal"))


def enforce(project, action, by):
    """Before a write: the snapshot the session runs under must be intact, signed when the project
    signs, not expired, and still what the graph says now for its agent and principal. Returns a note
    for the audit record, None when no snapshot is in play and none is required; raises PolicyError
    (after an audit record of the refusal) otherwise."""
    from . import audit as _audit
    from .curate import session as _session
    conf = settings(project)
    path = snapshot_path()
    if not os.path.isfile(path):
        if not conf["require_snapshot"]:
            return None
        problem = ("%s needs a policy snapshot: the project requires one (policy.require_snapshot). Write it with "
                   "`oto policy snapshot --agent <id> --principal <id>` and point OTO_POLICY_SNAPSHOT at it" % action)
        _audit.append(project, DENIED_ACTION, by, [], "refused", "%s: no snapshot (%s)" % (action, path))
        raise PolicyError(problem)
    problems = verify_snapshot(path, key_env=conf["sign_with"])
    snap = None
    try:
        snap = read_snapshot(path)
    except PolicyError as exc:
        problems.append(str(exc))
    if snap is not None and conf["sign_with"] and not snap.get("signature"):
        problems.append("the project signs its snapshots (policy.sign_with) and this one is unsigned")
    agent_id = (snap or {}).get("agent", {}).get("id") if snap else None
    principal_id = (snap or {}).get("principal", {}).get("id") if snap else None
    if snap is not None and not problems:
        with open(project.ontology_config_path, encoding="utf-8") as f:
            classes = json.load(f).get("classes") or {}
        try:
            fresh = snapshot(_session.live(project), agent_id, principal_id, classes=classes, ttl_hours=snap.get("ttl_hours") or DEFAULT_TTL_HOURS)
        except PolicyError as exc:
            problems.append("the snapshot's agent or principal is no longer in the graph: %s" % exc)
        else:
            if not _same_policy(snap, fresh):
                problems.append("the policy changed since the snapshot was written for %s as %s: write it again with `oto policy snapshot`"
                                % (agent_id, principal_id))
    if problems:
        _audit.append(project, DENIED_ACTION, by, [x for x in (agent_id, principal_id) if x], "refused", "%s: %s" % (action, "; ".join(problems)))
        raise PolicyError("%s refused under the policy snapshot %s: %s" % (action, path, "; ".join(problems)))
    return "under snapshot %s for %s as %s, expires %s" % (str(snap.get("hash"))[:12], agent_id, principal_id, snap.get("expires_at"))
