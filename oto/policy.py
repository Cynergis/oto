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
    path = os.path.join(out_dir, "policies.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                policies = json.load(f)
        except ValueError:
            policies = None
        if policies is not None and content_hash(policies) != manifest.get("hash"):
            problems.append("policies.json: the content hash is not the manifest's")
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
