# -*- coding: utf-8 -*-
"""The generated system's IAM (roadmap E7): the platform's bindings, derived from the access policy
the graph holds, a design-time output OTO never enforces (ADR-0005).

The policy pack says what a role may do (`oto policy compile`); the generated system runs as
principals, service accounts a `Component` `runs_as`, each holding roles. Read through those roles,
the active rules say which principal may do what on which resource, and the platform wants that as
bindings: a member (`serviceAccount:<identity>` for a service, `user:<identity>` for a person), a
platform role (the permission's `cloud_role`, `roles/bigquery.dataViewer`) and a resource (the
node's `resource_uri`). A forbid withholds the binding a permit would have made for the same member,
resource and action, as it outranks the permit in Cedar. What cannot bind is named and left out: a
permission with no platform role, a resource with no place on the platform, a principal with no
identity.

The bundle, `build/iam/` by default, beside the policy bundle:

    bindings.json            the bindings, the withheld ones, the members, what could not bind
    gcp.json                 the same bindings resource by resource, in the shape set-iam-policy takes
    controls.proposal.json   the generated controls as a proposal in the architecture vocabulary: one
                             Control per resource that safeguards it and the components running as its
                             members, derives_from the rules it came from, config holding the bindings
    iam-bindings.md          the document the controls quote, one line per binding
    manifest.json            like the policy bundle's: version, counts, file hashes, a content hash
                             over bindings.json, a signature with the key the project names

Only GCP is written in this release; the provider is a setting (`policy.provider`), and another is
a second shape over the same derivation. The controls enter the graph through the gates
(`oto policy iam --apply`), never by writing it; the CALM export then carries them.
"""
import datetime
import json
import os

from . import policy as _policy
from .data import _slug
from .project import ProjectError

BUNDLE_VERSION = 1
PROVIDER = "gcp"
PROVIDERS = ("gcp",)
GENERATOR = "oto policy iam"
REQUIREMENT_URL = "https://cynergis.ai/calm/controls/iam-bindings.requirement.json"
DOC = "iam-bindings"
CONTENT = "bindings.json"
FILES = ("bindings.json", "gcp.json", "controls.proposal.json", "iam-bindings.md")
MEMBER_PREFIX = {"service": "serviceAccount", "person": "user"}
RESOURCE_URI = "resource_uri"
CLOUD_ROLE = "cloud_role"
CONTROL = "Control"
RUNS_AS = "runs_as"


class IamError(ProjectError):
    pass


def member(principal):
    """The principal as GCP names a member, or None without an identity or a kind."""
    a = _policy._attrs(principal)
    identity = str(a.get("identity") or "").strip()
    prefix = MEMBER_PREFIX.get(a.get("kind"))
    if not identity or not prefix:
        return None
    return "%s:%s" % (prefix, identity)


def _ref(node):
    return {"id": node["id"], "type": node.get("type"), "label": node.get("label") or node["id"], "uri": _policy._attrs(node).get(RESOURCE_URI)}


def _resources_of(rule, nodes, by_id):
    """The nodes a compiled rule reaches: the ones it singles out, else every current node of the
    permission's class its selector admits."""
    if rule["resources"]:
        return [by_id[r["id"]] for r in rule["resources"] if r["id"] in by_id]
    p = rule["permission"]
    return [n for n in nodes if n.get("type") == p["resource_class"] and _policy._admits(p["selector"], n)]


def compile(graph, classes=None, provider=PROVIDER):
    """The bindings as data: {bundle_version, provider, bindings, withheld, members, resources, problems}."""
    if provider not in PROVIDERS:
        raise IamError("provider %r: this release writes %s (policy.provider in project.config.json)" % (provider, ", ".join(PROVIDERS)))
    policy = _policy.compile(graph, classes)
    nodes = [n for n in (graph.get("nodes") or []) if (n.get("status") or "current") == "current"]
    by_id = {n["id"]: n for n in nodes}
    out_edges = {}
    for e in graph.get("edges") or []:
        if (e.get("status") or "current") == "current":
            out_edges.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
    by_role = {}
    for rule in policy["rules"]:
        for who in rule["roles"]:
            by_role.setdefault(who["id"], []).append(rule)
    problems = list(policy["problems"])
    grants, withheld, members = {}, [], []
    for p in sorted((n for n in nodes if n.get("type") == "Principal"), key=lambda n: n["id"]):
        who = member(p)
        if not who:
            problems.append("%s has no identity%s: no member, no binding" % (p["id"], "" if _policy._attrs(p).get("kind") in MEMBER_PREFIX else " or no kind"))
            continue
        roles = sorted(t for t in out_edges.get((p["id"], "holds_role"), []) if t in by_id)
        rules, seen = [], set()
        for role in roles:
            for rule in by_role.get(role, []):
                if rule["id"] not in seen:
                    seen.add(rule["id"])
                    rules.append(rule)
        members.append({"principal": p["id"], "label": p.get("label") or p["id"], "member": who, "roles": roles, "rules": sorted(seen)})
        permits, forbids = {}, {}
        for rule in rules:
            action = rule["permission"]["action"]
            for r in _resources_of(rule, nodes, by_id):
                (permits if rule["effect"] == "permit" else forbids).setdefault((r["id"], action), []).append(rule)
        for (rid, action), permitted in sorted(permits.items()):
            node = by_id[rid]
            if (rid, action) in forbids:
                for rule in permitted:
                    withheld.append({"principal": p["id"], "member": who, "resource": _ref(node), "action": action,
                                     "role": _policy._attrs(by_id.get(rule["permission"]["id"], {})).get(CLOUD_ROLE),
                                     "permitted_by": [rule["id"]], "forbidden_by": sorted(f["id"] for f in forbids[(rid, action)])})
                continue
            for rule in permitted:
                permission = by_id.get(rule["permission"]["id"], {})
                role = _policy._attrs(permission).get(CLOUD_ROLE)
                if not role:
                    problems.append("%s: permission %s has no cloud_role: no binding on the platform" % (rule["id"], rule["permission"]["id"]))
                    continue
                uri = _policy._attrs(node).get(RESOURCE_URI)
                if not uri:
                    problems.append("%s has no resource_uri: no binding on it (%s)" % (rid, rule["id"]))
                    continue
                grant = grants.setdefault((rid, role), {"resource": _ref(node), "role": role, "members": set(), "principals": set(), "rules": set()})
                grant["members"].add(who)
                grant["principals"].add(p["id"])
                grant["rules"].add(rule["id"])
    bindings = []
    for key in sorted(grants):
        g = grants[key]
        bindings.append({"resource": g["resource"], "role": g["role"], "members": sorted(g["members"]), "principals": sorted(g["principals"]),
                         "rules": sorted(g["rules"])})
    unique = []
    for p in problems:
        if p not in unique:
            unique.append(p)
    return {"bundle_version": BUNDLE_VERSION, "provider": provider, "bindings": bindings, "withheld": withheld, "members": members,
            "resources": sorted({b["resource"]["id"] for b in bindings}), "problems": unique}


# ---- the platform's form ----

def gcp_policies(doc):
    """One IAM policy per resource, in the shape `set-iam-policy` takes: {resource, policy: {bindings}}."""
    by_uri = {}
    for b in doc.get("bindings") or []:
        by_uri.setdefault(b["resource"]["uri"], []).append({"role": b["role"], "members": list(b["members"])})
    return [{"resource": uri, "policy": {"bindings": sorted(by_uri[uri], key=lambda x: x["role"])}} for uri in sorted(by_uri)]


# ---- the document and the controls ----

def _binding_line(b):
    return "%s: %s for %s (%s)" % (b["resource"]["id"], b["role"], ", ".join(b["members"]), ", ".join(b["rules"]))


def _withheld_line(w):
    return "%s: %s withheld from %s, %s forbidden by %s (permitted by %s)" % (
        w["resource"]["id"], w.get("role") or w["action"], w["member"], w["action"], ", ".join(w["forbidden_by"]), ", ".join(w["permitted_by"]))


def document(doc, at):
    """(title, text): one line per binding, the quotes the generated controls cite."""
    title = "IAM bindings of the generated system"
    lines = ["# %s" % title, "",
             "Derived on %s by `%s` from the active rules of the access policy, read through the roles each principal holds, for %s. "
             "One line per binding; each generated control quotes its lines here. OTO does not enforce these: they ship with the system "
             "and the platform enforces them (ADR-0005)." % (at, GENERATOR, doc["provider"]), "", "## Bindings", ""]
    for b in doc.get("bindings") or []:
        lines.append("- %s" % _binding_line(b))
    if not doc.get("bindings"):
        lines.append("- no binding: no active rule reaches a principal with an identity on a resource with a place on the platform")
    if doc.get("withheld"):
        lines += ["", "## Withheld", ""]
        for w in doc["withheld"]:
            lines.append("- %s" % _withheld_line(w))
    if doc.get("problems"):
        lines += ["", "## Not bound", ""]
        for p in doc["problems"]:
            lines.append("- %s" % p)
    return title, "\n".join(lines).rstrip() + "\n"


def control_id(resource_id):
    return "control.iam-%s" % _slug(resource_id)


def propose(doc, graph, at, classes=None):
    """The generated controls as a proposal: one Control per bound resource. Empty when the vocabulary
    declares no Control (the architecture pack is not composed)."""
    if classes is not None and CONTROL not in set(classes):
        return {"source_doc": DOC, "as_of": at, "nodes": [], "edges": []}
    runs_as = {}
    for e in graph.get("edges") or []:
        if e.get("rel") == RUNS_AS and (e.get("status") or "current") == "current":
            runs_as.setdefault(e.get("to"), set()).add(e.get("from"))
    nodes, edges, seen = [], [], set()

    def edge(a, rel, b):
        if (a, rel, b) not in seen:
            seen.add((a, rel, b))
            edges.append({"from": a, "rel": rel, "to": b})

    for rid in doc.get("resources") or []:
        bound = [b for b in doc["bindings"] if b["resource"]["id"] == rid]
        held = [w for w in doc.get("withheld") or [] if w["resource"]["id"] == rid]
        resource = bound[0]["resource"]
        cid = control_id(rid)
        bindings = {"provider": doc["provider"], "resource": resource["uri"],
                    "bindings": [{"role": b["role"], "members": list(b["members"])} for b in bound],
                    "withheld": [{"member": w["member"], "role": w.get("role") or w["action"], "forbidden_by": list(w["forbidden_by"])} for w in held]}
        config = {"requirements": [{"requirement-url": REQUIREMENT_URL, "config": bindings}]}      # a CALM control body, as the export writes it back
        rules = sorted({r for b in bound for r in b["rules"]} | {r for w in held for r in w["permitted_by"] + w["forbidden_by"]})
        members = ", ".join(sorted({m for b in bound for m in b["members"]}))
        nodes.append({"id": cid, "type": CONTROL, "label": "IAM bindings on %s" % resource["label"],
                      "summary": "What the platform lets %s do on %s, derived from the access policy by %s; the platform enforces it, OTO does not." % (
                          members, resource["label"], GENERATOR),
                      "attributes": {"calm_id": "iam-%s" % _slug(rid), "requirement_url": REQUIREMENT_URL, "generated_by": GENERATOR,
                                     "config": json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":"))},
                      "valid_from": at,
                      "evidence": [{"doc": DOC, "where": "bindings", "quote": _binding_line(b)} for b in bound]
                      + [{"doc": DOC, "where": "withheld", "quote": _withheld_line(w)} for w in held]})
        edge(cid, "safeguards", rid)
        for pid in sorted({p for b in bound for p in b["principals"]} | {w["principal"] for w in held}):
            for component in sorted(runs_as.get(pid, ())):
                edge(cid, "safeguards", component)
        for rule in rules:
            edge(cid, "derives_from", rule)
    return {"source_doc": DOC, "as_of": at, "nodes": nodes, "edges": edges}


# ---- the bundle ----

def bundle(graph, out_dir, version=None, at=None, key_env=None, classes=None, provider=PROVIDER):
    """Write bindings.json, gcp.json, controls.proposal.json, iam-bindings.md and manifest.json into
    `out_dir`; return the manifest. Signed with the key in `key_env` when named, as the policy bundle."""
    doc = compile(graph, classes, provider=provider)
    at = at or datetime.date.today().isoformat()
    bindings = {"bundle_version": BUNDLE_VERSION, "generated_at": at, "version": dict(version or {}), "provider": doc["provider"],
                "bindings": doc["bindings"], "withheld": doc["withheld"], "members": doc["members"], "problems": doc["problems"]}
    signature = _policy._sign(_policy.content_hash(bindings), key_env) if key_env else None
    proposal = propose(doc, graph, at, classes)
    _title, text = document(doc, at)
    os.makedirs(out_dir, exist_ok=True)

    def write_json(name, value):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")

    write_json("bindings.json", bindings)
    write_json("gcp.json", gcp_policies(doc))
    write_json("controls.proposal.json", proposal)
    with open(os.path.join(out_dir, DOC + ".md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    manifest = {"bundle_version": BUNDLE_VERSION, "generated_at": at, "version": dict(version or {}), "provider": doc["provider"], "content": CONTENT,
                "bindings": len(doc["bindings"]), "resources": len(doc["resources"]), "members": len(doc["members"]), "controls": len(proposal["nodes"]),
                "withheld": len(doc["withheld"]), "problems": doc["problems"],
                "files": {name: _policy._file_hash(os.path.join(out_dir, name)) for name in FILES},
                "hash": _policy.content_hash(bindings), "signature": signature}
    write_json("manifest.json", manifest)
    return manifest


def describe(manifest):
    """One line about a bindings bundle."""
    signature = manifest.get("signature")
    return "%d binding(s) on %d resource(s) for %d member(s), %d control(s), %d withheld, hash %s, %s" % (
        manifest.get("bindings", 0), manifest.get("resources", 0), manifest.get("members", 0), manifest.get("controls", 0), manifest.get("withheld", 0),
        str(manifest.get("hash"))[:12], ("signed with %s" % signature["key"]) if signature else "unsigned")


def settings(project):
    """{provider}: `policy.provider` in project.config.json, gcp by default."""
    cfg = project.config().get("policy") or {}
    return {"provider": str(cfg.get("provider") or PROVIDER)}


def install_document(project, out_dir):
    """Copy the bundle's document into the corpus and the archive, where the gates look a quote up."""
    with open(os.path.join(out_dir, DOC + ".md"), encoding="utf-8") as f:
        text = f.read()
    corpus = os.path.join(project.layout.corpus, DOC + ".md")
    archive = os.path.join(project.layout.archive, DOC + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return corpus


def fold_derived(graph, derived):
    """The graph with the build's derived attributes folded in (`derived.json`): a table whose column
    is personal data is `pii` for a selector, as the served engine and the snapshot read it."""
    by_id = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    for d in (derived or {}).get("derived_attributes") or []:
        n = by_id.get(d.get("node"))
        if n is not None:
            attributes = n.get("attributes")
            if not isinstance(attributes, dict):
                attributes = n["attributes"] = {}
            attributes[d["name"]] = d.get("value")
    return graph


def built_graph(project):
    """The built graph with its derived attributes, or None when the project was never built."""
    built = os.path.join(project.layout.graph, "knowledge-graph.json")
    if not os.path.isfile(built):
        return None
    with open(built, encoding="utf-8") as f:
        graph = json.load(f)
    derived_path = os.path.join(project.layout.graph, "derived.json")
    derived = {}
    if os.path.isfile(derived_path):
        with open(derived_path, encoding="utf-8") as f:
            derived = json.load(f)
    return fold_derived(graph, derived)


def graph_for(project):
    """The graph the bindings are derived from: the built one when it exists, with the derived
    attributes folded in, else the live graph (and which it was)."""
    from .curate import session as _session
    graph = built_graph(project)
    if graph is not None:
        return graph, "build"
    return _session.live(project), "live"
