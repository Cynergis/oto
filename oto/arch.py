# -*- coding: utf-8 -*-
"""The architecture graph's commands (roadmap Epic H): a CALM model in and out (H1), the code map
and compile on merge (H2).

    oto arch import --calm model.json --at YYYY-MM-DD [--name <slug>] [--environment environment.<id>]
    oto arch export --calm [--out model.json]
    oto arch map --repo <path> --repository repo.<id> --at YYYY-MM-DD [--name <slug>]
    oto arch compile --at YYYY-MM-DD --by <who> [--note "..."]
    oto arch impact --decision <id|ADR-nnn> | --orphans | --untraced | --files <paths...> [--format text|markdown]

`map` scans a code repository by a declared convention (`oto.codemap.json` at its root, else every
directory under `src/` is a module of the component named after it) into a code-map document and a
proposal: a `CodeModule` per module with its path and language, `located_in` the repository the
estate declares, `implemented_by` from the component the convention names when the graph holds it
(a module whose component the graph lacks is proposed untraced, never a component invented: AR9
lists it), and the last `Commit` that `touches` each module when the repository is a git checkout.
Mapped again after a merge, the modules are the same facts and the new commit is one more node.

`compile` runs what project.config.json declares under `arch` ({"calm": [paths], "environment":
environment.<id>, "codemap": {"repo": path, "repository": repo.<id>}}): the imports and the map,
through the gates and applied with the merge in the note, then built. A merge the gates refuse
leaves no candidate behind and names the findings. The `oto architecture` workflow runs it on
every merge to main, so the graph matches main and nobody edits it by hand.

`import` reads a CALM 1.x model (the FINOS Common Architecture Language Model; the pack is aligned
with release 1.0 and the core schema is unchanged through 1.3) into a document in the corpus
(`build/documents/calm-<slug>.md`, kept in `archive/`: one line per node, interface, relationship,
control, flow and step, each the evidence its fact quotes) and a proposal in the architecture
vocabulary that goes through the gates like any other change. A CALM node is an estate node
(System, Component, DataStore, Environment, Role by its node-type: an ldap directory is a store of identities; any other type a Component) with
`calm_id` and `calm_type`; a relationship is a `Relationship` node with its ends, kind and protocol;
controls and flows are nodes; and the plain estate edges are derived beside them (part_of from
composed-of in a system, runs_in from deployed-in in a network, exposes from a node's interfaces,
consumes and depends_on from connects) so the estate's own questions answer. What CALM carries that
no question asks for (metadata, details, an interface's fields, a control's requirements, an
option's lists, the model's own header) is kept as the JSON it was given, never read.

`export` walks the live graph back into a CALM model: export of import equals the input, up to what
the graph cannot tell from absence (an empty interfaces or controls list, an empty description).
What CALM does not say is not invented: a node CALM deploys nowhere runs nowhere unless
`--environment` names the estate's environment it runs in, and a node CALM composes in nothing is
part of nothing, which the estate's shape names at the gate.
"""
import collections
import contextlib
import fnmatch
import glob as _glob
import io
import json
import os
import re
import subprocess

from .data import _slug
from .project import ProjectError

NODE_CLASS = {"system": "System", "ecosystem": "System", "service": "Component", "webclient": "Component",
              "database": "DataStore", "data-asset": "DataStore", "datastore": "DataStore", "ldap": "DataStore", "network": "Environment", "actor": "Role"}
DEFAULT_CLASS = "Component"
PREFIX = {"System": "system", "Component": "component", "DataStore": "datastore", "Environment": "environment", "Role": "role"}
DEFAULT_TYPE = {"System": "system", "Component": "service", "DataStore": "database", "Environment": "network", "Role": "actor"}
SHAPES = ("interacts", "connects", "deployed-in", "composed-of", "options")
PROTOCOLS = ("HTTP", "HTTPS", "FTP", "SFTP", "JDBC", "WebSocket", "SocketIO", "LDAP", "AMQP", "TLS", "mTLS", "TCP")
HEADER_SKIP = ("nodes", "relationships", "controls", "flows")
RELATIONSHIP, CONTROL, FLOW, STEP, INTERFACE, DECISION, DOCUMENT = "Relationship", "Control", "Flow", "FlowStep", "Interface", "Decision", "Document"
MODULE, COMMIT = "CodeModule", "Commit"
CONVENTION_NAME = "oto.codemap.json"
DEFAULT_CONVENTION = {"modules": [{"path": "src/*", "component": "component.{name}"}]}
DEFAULT_IGNORE = (".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "target", ".tox", ".mypy_cache", ".pytest_cache")
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".java": "java",
             ".go": "go", ".rs": "rust", ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".sql": "sql", ".sh": "shell", ".scala": "scala", ".php": "php",
             ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".tf": "terraform", ".dart": "dart", ".ex": "elixir", ".exs": "elixir"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ArchError(ProjectError):
    """A refusal, in words the person can act on."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def model_slug(path, name=None):
    """calm-<slug>: from --name, else the file's stem without .calm or .architecture."""
    if name:
        return "calm-%s" % _slug(name)
    stem = os.path.basename(path)
    for suffix in (".json", ".calm", ".architecture", ".model"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return "calm-%s" % _slug(stem)


def _shape(rel):
    """(kind, body) of a relationship: `relationship-type` as CALM writes it, or the older form where
    it is a string and the body sits beside it."""
    rt = rel.get("relationship-type")
    if isinstance(rt, dict):
        keys = [k for k in rt if k in SHAPES]
        if len(keys) != 1 or len(rt) != 1:
            raise ArchError("relationship %r must carry exactly one of %s in relationship-type" % (rel.get("unique-id"), ", ".join(SHAPES)))
        return keys[0], rt[keys[0]]
    if isinstance(rt, str) and rt in SHAPES:
        return rt, rel.get(rt) or {}
    raise ArchError("relationship %r has no relationship-type among %s" % (rel.get("unique-id"), ", ".join(SHAPES)))


# ---- reading ----

def _nodes_of(model):
    nodes = model.get("nodes")
    if not isinstance(nodes, list):
        raise ArchError("not a CALM model: `nodes` is a list of nodes (unique-id, node-type, name, description)")
    out, slugs = {}, {}
    for n in nodes:
        if not isinstance(n, dict) or not n.get("unique-id") or not n.get("node-type"):
            raise ArchError("a CALM node carries unique-id and node-type: %s" % _json(n)[:80])
        uid = str(n["unique-id"])
        if uid in out:
            raise ArchError("node %r is declared twice" % uid)
        cls = NODE_CLASS.get(str(n["node-type"]).lower(), DEFAULT_CLASS)
        nid = "%s.%s" % (PREFIX[cls], _slug(uid))
        if nid in slugs:
            raise ArchError("nodes %r and %r would share the id %s: rename one" % (slugs[nid], uid, nid))
        slugs[nid] = uid
        out[uid] = {"id": nid, "class": cls, "node": n}
    return out


def _lines(model, nodes, at, source, doc_title):
    """The document: one line per fact, the quotes the proposal cites."""
    lines = ["# %s" % doc_title, "", "Read from %s on %s by `oto arch import --calm`%s. One line per node, interface, relationship, control, "
             "flow and step: each fact in the graph quotes its line here. What CALM carries beyond these lines (metadata, details, an interface's "
             "fields, a control's requirements) is kept on the facts as the JSON the model gave." % (source, at, " (schema %s)" % model["$schema"] if model.get("$schema") else ""), "",
             "## Nodes", ""]
    for uid, item in nodes.items():
        n = item["node"]
        lines.append("- %s (%s): %s" % (uid, n["node-type"], n.get("name") or uid))
        for i in n.get("interfaces") or []:
            lines.append("  - interface %s" % i.get("unique-id"))
        for cid, body in (n.get("controls") or {}).items():
            lines.append("  - control %s/%s: %s" % (uid, cid, (body or {}).get("description") or ""))
    lines += ["", "## Relationships", ""]
    for rel in model.get("relationships") or []:
        kind, body = _shape(rel)
        head = "%s (%s%s)" % (rel["unique-id"], kind, ", %s" % rel["protocol"] if rel.get("protocol") else "")
        lines.append("- %s%s" % (head, ": %s" % rel["description"] if rel.get("description") else ""))
        if kind == "options":
            for n, decision in enumerate(body or [], 1):
                lines.append("  - %s option %d: %s" % (rel["unique-id"], n, (decision or {}).get("description") or ""))
        for cid, cbody in (rel.get("controls") or {}).items():
            lines.append("  - control %s/%s: %s" % (rel["unique-id"], cid, (cbody or {}).get("description") or ""))
    if model.get("controls"):
        lines += ["", "## Controls", ""]
        for cid, body in model["controls"].items():
            lines.append("- control model/%s: %s" % (cid, (body or {}).get("description") or ""))
    if model.get("flows"):
        lines += ["", "## Flows", ""]
        for flow in model["flows"]:
            lines.append("- flow %s: %s" % (flow["unique-id"], flow.get("name") or flow["unique-id"]))
            for t in sorted(flow.get("transitions") or [], key=lambda t: t.get("sequence-number", 0)):
                lines.append("  - step %s over %s: %s" % (t.get("sequence-number"), t.get("relationship-unique-id"), t.get("description") or ""))
            for cid, cbody in (flow.get("controls") or {}).items():
                lines.append("  - control %s/%s: %s" % (flow["unique-id"], cid, (cbody or {}).get("description") or ""))
    return "\n".join(lines).rstrip() + "\n"


def document(model, doc, at, source="the model"):
    title = "CALM model %s" % (model.get("name") or model.get("title") or doc[5:] if doc.startswith("calm-") else doc)
    nodes = _nodes_of(model)
    return title, _lines(model, nodes, at, source, title)


def propose(model, doc, at, environment=None, source="the model"):
    """(proposal, gaps): the CALM model as nodes and edges of the architecture vocabulary, every node
    quoting its line of the document; the gaps are what the model does not say and the estate asks."""
    if not isinstance(model, dict):
        raise ArchError("not a CALM model: a JSON object with `nodes` and `relationships`")
    nodes = _nodes_of(model)
    relationships = model.get("relationships")
    if relationships is None:
        relationships = []
    if not isinstance(relationships, list):
        raise ArchError("not a CALM model: `relationships` is a list")
    title, _text = document(model, doc, at, source)
    out_nodes, edges, gaps = [], [], []
    seen_edges = set()

    def node(nid, kind, label, summary, attributes, where, quote):
        out_nodes.append({"id": nid, "type": kind, "label": label, "summary": summary, "attributes": attributes, "valid_from": at,
                          "evidence": [{"doc": doc, "where": where, "quote": quote}]})

    def edge(a, rel, b):
        if (a, rel, b) not in seen_edges:
            seen_edges.add((a, rel, b))
            edges.append({"from": a, "rel": rel, "to": b})

    def controls(scope, mapping, target, where):
        for cid, body in (mapping or {}).items():
            body = body or {}
            cnid = "control.%s-%s" % (_slug(scope), _slug(cid))
            attributes = {"calm_id": str(cid)}
            requirements = body.get("requirements") or []
            if requirements and isinstance(requirements[0], dict) and requirements[0].get("requirement-url"):
                attributes["requirement_url"] = requirements[0]["requirement-url"]
                if requirements[0].get("config-url"):
                    attributes["config_url"] = requirements[0]["config-url"]
            else:
                gaps.append("control %s/%s cites no requirement-url; the vocabulary requires one" % (scope, cid))
            rest = {k: v for k, v in body.items() if k != "description"}
            attributes["config"] = _json(rest)
            node(cnid, CONTROL, str(cid), body.get("description") or "", attributes, where, "control %s/%s" % (scope, cid))
            if target:
                edge(cnid, "safeguards", target)

    header = {k: v for k, v in model.items() if k not in HEADER_SKIP}
    node("document.%s" % doc, DOCUMENT, title,
         model.get("description") or "A CALM model, as `oto arch import` read it.", {"kind": "architecture", "calm_header": _json(header)}, "title", title)
    interfaces = {}
    for uid, item in nodes.items():
        n, cls, nid = item["node"], item["class"], item["id"]
        attributes = {"calm_id": uid, "calm_type": str(n["node-type"])}
        if n.get("metadata") is not None:
            attributes["calm_metadata"] = _json(n["metadata"])
        if n.get("details") is not None:
            attributes["calm_details"] = _json(n["details"])
        node(nid, cls, n.get("name") or uid, n.get("description") or "", attributes, "nodes", "%s (%s)" % (uid, n["node-type"]))
        for i in n.get("interfaces") or []:
            if not isinstance(i, dict) or not i.get("unique-id"):
                raise ArchError("an interface of node %r carries no unique-id" % uid)
            iuid = str(i["unique-id"])
            iid = "interface.%s" % _slug(iuid)
            if iuid in interfaces:
                raise ArchError("interface %r is declared twice" % iuid)
            rest = {k: v for k, v in i.items() if k != "unique-id"}
            iattr = {"calm_id": iuid, "config": _json(rest)}
            if i.get("definition-url"):
                iattr["definition_url"] = i["definition-url"]
            url = i.get("url") or ((i.get("config") or {}).get("url") if isinstance(i.get("config"), dict) else None)
            if url:
                iattr["url"] = url
            node(iid, INTERFACE, i.get("name") or iuid, i.get("description") or "", iattr, uid, "interface %s" % iuid)
            interfaces[iuid] = {"id": iid, "owner": uid}
            if cls in ("System", "Component"):
                edge(nid, "exposes", iid)
            else:
                gaps.append("%s (%s) declares interface %s, and the estate's exposes is a system's or a component's" % (uid, n["node-type"], iuid))
        controls(uid, n.get("controls"), nid, uid)

    def ref(uid, what):
        if uid not in nodes:
            raise ArchError("%s names node %r, which the model does not declare" % (what, uid))
        return nodes[uid]

    composed, deployed = set(), set()
    for rel in relationships:
        if not isinstance(rel, dict) or not rel.get("unique-id"):
            raise ArchError("a CALM relationship carries unique-id and relationship-type: %s" % _json(rel)[:80])
        ruid = str(rel["unique-id"])
        kind, body = _shape(rel)
        rid = "relationship.%s" % _slug(ruid)
        attributes = {"calm_id": ruid, "kind": kind}
        if rel.get("protocol"):
            if rel["protocol"] in PROTOCOLS:
                attributes["protocol"] = rel["protocol"]
            else:
                gaps.append("relationship %s speaks %r, not one of CALM's protocols; kept in metadata only" % (ruid, rel["protocol"]))
        if rel.get("metadata") is not None:
            attributes["calm_metadata"] = _json(rel["metadata"])
        head = "%s (%s%s)" % (ruid, kind, ", %s" % rel["protocol"] if rel.get("protocol") else "")
        node(rid, RELATIONSHIP, rel.get("description") or ruid, rel.get("description") or "", attributes, "relationships", head)
        what = "relationship %s" % ruid
        if kind == "interacts":
            actor = ref(body.get("actor"), what)
            edge(rid, "connects_from", actor["id"])
            for t in body.get("nodes") or []:
                edge(rid, "connects_to", ref(t, what)["id"])
        elif kind == "connects":
            src, dst = body.get("source") or {}, body.get("destination") or {}
            s, d = ref(src.get("node"), what), ref(dst.get("node"), what)
            edge(rid, "connects_from", s["id"])
            edge(rid, "connects_to", d["id"])
            named = False
            for side, consumer in ((src, d), (dst, s)):
                for iuid in side.get("interfaces") or []:
                    if iuid not in interfaces:
                        gaps.append("%s names interface %r, which no node declares" % (what, iuid))
                        continue
                    named = True
                    edge(rid, "via", interfaces[iuid]["id"])
                    if consumer["class"] in ("System", "Component"):
                        edge(consumer["id"], "consumes", interfaces[iuid]["id"])
            if not named and s["class"] in ("System", "Component") and d["class"] in ("System", "Component"):
                edge(s["id"], "depends_on", d["id"])
        elif kind in ("deployed-in", "composed-of"):
            container = ref(body.get("container"), what)
            edge(rid, "connects_from", container["id"])
            for t in body.get("nodes") or []:
                member = ref(t, what)
                edge(rid, "connects_to", member["id"])
                if kind == "composed-of" and container["class"] == "System" and member["class"] in ("Component", "Interface", "DataStore"):
                    edge(member["id"], "part_of", container["id"])
                    composed.add(t)
                if kind == "deployed-in" and container["class"] == "Environment" and member["class"] in ("Component", "DataStore"):
                    edge(member["id"], "runs_in", container["id"])
                    deployed.add(t)
        elif kind == "options":
            for n, decision in enumerate(body or [], 1):
                decision = decision or {}
                did = "decision.%s-%d" % (_slug(ruid), n)
                node(did, DECISION, decision.get("description") or "%s option %d" % (ruid, n), decision.get("description") or "",
                     {"status": "proposed", "calm_option": _json(decision)}, "relationships", "%s option %d" % (ruid, n))
                edge(rid, "offers_option", did)
        controls(ruid, rel.get("controls"), rid, "relationships")
    controls("model", model.get("controls"), None, "controls")
    for flow in model.get("flows") or []:
        if not isinstance(flow, dict) or not flow.get("unique-id"):
            raise ArchError("a CALM flow carries unique-id, name, description and transitions")
        fuid = str(flow["unique-id"])
        fid = "flow.%s" % _slug(fuid)
        attributes = {"calm_id": fuid}
        if flow.get("requirement-url"):
            attributes["requirement_url"] = flow["requirement-url"]
        if flow.get("metadata") is not None:
            attributes["calm_metadata"] = _json(flow["metadata"])
        node(fid, FLOW, flow.get("name") or fuid, flow.get("description") or "", attributes, "flows", "flow %s" % fuid)
        for t in flow.get("transitions") or []:
            seq = t.get("sequence-number")
            rel_uid = t.get("relationship-unique-id")
            rid = "relationship.%s" % _slug(str(rel_uid))
            if not any(r.get("unique-id") == rel_uid for r in relationships):
                raise ArchError("flow %s steps over relationship %r, which the model does not declare" % (fuid, rel_uid))
            sid = "flowstep.%s-%s" % (_slug(fuid), seq)
            sattr = {"sequence": int(seq)}
            if t.get("direction"):
                sattr["direction"] = t["direction"]
            node(sid, STEP, "%s, step %s" % (flow.get("name") or fuid, seq), t.get("description") or "", sattr, fuid, "step %s over %s" % (seq, rel_uid))
            edge(sid, "step_of", fid)
            edge(sid, "over", rid)
        controls(fuid, flow.get("controls"), fid, "flows")
    for uid, item in nodes.items():
        if item["class"] in ("Component", "DataStore") and uid not in deployed:
            if environment:
                edge(item["id"], "runs_in", environment)
            else:
                gaps.append("%s runs nowhere CALM says (no deployed-in with a network container): pass --environment environment.<id>, or the estate's "
                            "shape blocks it at the gate" % uid)
        if item["class"] == "Component" and uid not in composed:
            gaps.append("%s is composed in no system (no composed-of with a system container): the estate requires part_of, and the gate will say so "
                        "until the model does" % uid)
    return {"source_doc": doc, "as_of": at, "nodes": out_nodes, "edges": edges}, gaps


def import_calm(project, path, at, name=None, environment=None):
    """Read the model, write the document and the proposal. Returns {"doc", "document", "archive",
    "proposal", "nodes", "relationships", "controls", "flows", "gaps", "schema"}."""
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date the model was read is never defaulted")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if RELATIONSHIP not in classes or FLOW not in classes:
        raise ArchError("the vocabulary declares no Relationship and Flow: the architecture ontology does (oto init --ontology architecture, or compose it)")
    if not os.path.isfile(path):
        raise ArchError("no such model: %s" % path)
    with open(path, encoding="utf-8") as f:
        try:
            model = json.load(f)
        except ValueError as exc:
            raise ArchError("%s is not JSON: %s" % (path, exc))
    if environment:
        from .data import _graph_ids
        if environment not in _graph_ids(project):
            raise ArchError("the graph holds no %s: --environment names an Environment the estate declares" % environment)
    doc = model_slug(path, name)
    source = os.path.basename(path)
    title, text = document(model, doc, at, source)
    proposal, gaps = propose(model, doc, at, environment=environment, source=source)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    count = lambda kind: sum(1 for n in proposal["nodes"] if n["type"] == kind)  # noqa: E731
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "schema": model.get("$schema"),
            "nodes": sum(1 for n in proposal["nodes"] if n["type"] in PREFIX), "relationships": count(RELATIONSHIP),
            "controls": count(CONTROL), "flows": count(FLOW), "interfaces": count(INTERFACE), "gaps": gaps}


# ---- writing back ----

def _loads(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def export_calm(project):
    """The live graph's CALM facts as a model: nodes with a calm_id, relationships, controls and flows."""
    from .curate import session as _session
    graph = _session.live(project)
    nodes = [n for n in graph.get("nodes") or [] if n.get("id")]
    by_id = {n["id"]: n for n in nodes}
    edges = graph.get("edges") or []
    headers = [n for n in nodes if n.get("type") == DOCUMENT and (n.get("attributes") or {}).get("calm_header")]
    if not headers and not any(n.get("type") == RELATIONSHIP for n in nodes):
        raise ArchError("the graph holds no CALM model: nothing to export (oto arch import --calm <model> first)")
    model = dict(_loads((headers[0].get("attributes") or {}).get("calm_header"), {})) if headers else {}
    attrs = lambda n: n.get("attributes") or {}  # noqa: E731
    exposes = {n["id"]: [e["to"] for e in edges if e.get("from") == n["id"] and e.get("rel") == "exposes" and by_id.get(e["to"], {}).get("type") == INTERFACE] for n in nodes}
    outgoing = {}
    for e in edges:
        outgoing.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
    safeguarded = {}
    for e in edges:
        if e.get("rel") == "safeguards":
            safeguarded.setdefault(e["to"], []).append(e["from"])
    attached = {c for targets in safeguarded.values() for c in targets}

    def control_map(cids):
        mapping = {}
        for cid in cids:
            c = by_id.get(cid)
            if c is None:
                continue
            body = {"description": c.get("summary") or ""}
            body.update(_loads(attrs(c).get("config"), {}))
            mapping[attrs(c).get("calm_id") or cid] = body
        return mapping

    calm_nodes = []
    for n in nodes:
        if n.get("type") not in PREFIX or not attrs(n).get("calm_id"):
            continue
        item = {"unique-id": attrs(n)["calm_id"], "node-type": attrs(n).get("calm_type") or DEFAULT_TYPE[n["type"]],
                "name": n.get("label") or attrs(n)["calm_id"], "description": n.get("summary") or ""}
        if attrs(n).get("calm_details"):
            item["details"] = _loads(attrs(n)["calm_details"], {})
        interfaces = []
        for iid in exposes.get(n["id"], []):
            i = by_id[iid]
            if attrs(i).get("calm_id"):
                interfaces.append(dict({"unique-id": attrs(i)["calm_id"]}, **_loads(attrs(i).get("config"), {})))
        if interfaces:
            item["interfaces"] = interfaces
        controls = control_map(safeguarded.get(n["id"], []))
        if controls:
            item["controls"] = controls
        if attrs(n).get("calm_metadata"):
            item["metadata"] = _loads(attrs(n)["calm_metadata"], {})
        calm_nodes.append(item)
    calm_id_of = lambda nid: attrs(by_id.get(nid, {})).get("calm_id") or nid  # noqa: E731
    relationships = []
    for n in nodes:
        if n.get("type") != RELATIONSHIP:
            continue
        kind = attrs(n).get("kind")
        item = {"unique-id": attrs(n).get("calm_id") or n["id"]}
        if n.get("summary"):
            item["description"] = n["summary"]
        sources = outgoing.get((n["id"], "connects_from"), [])
        targets = outgoing.get((n["id"], "connects_to"), [])
        if kind == "interacts":
            item["relationship-type"] = {"interacts": {"actor": calm_id_of(sources[0]) if sources else None, "nodes": [calm_id_of(t) for t in targets]}}
        elif kind == "connects":
            via = outgoing.get((n["id"], "via"), [])
            src = {"node": calm_id_of(sources[0]) if sources else None}
            dst = {"node": calm_id_of(targets[0]) if targets else None}
            src_if = [calm_id_of(i) for i in via if sources and i in exposes.get(sources[0], [])]
            dst_if = [calm_id_of(i) for i in via if targets and i in exposes.get(targets[0], [])]
            if src_if:
                src["interfaces"] = src_if
            if dst_if:
                dst["interfaces"] = dst_if
            item["relationship-type"] = {"connects": {"source": src, "destination": dst}}
        elif kind in ("deployed-in", "composed-of"):
            item["relationship-type"] = {kind: {"container": calm_id_of(sources[0]) if sources else None, "nodes": [calm_id_of(t) for t in targets]}}
        elif kind == "options":
            item["relationship-type"] = {"options": [_loads(attrs(by_id[d]).get("calm_option"), {"description": by_id[d].get("label")})
                                                     for d in outgoing.get((n["id"], "offers_option"), []) if d in by_id]}
        if attrs(n).get("protocol"):
            item["protocol"] = attrs(n)["protocol"]
        if attrs(n).get("calm_metadata"):
            item["metadata"] = _loads(attrs(n)["calm_metadata"], {})
        controls = control_map(safeguarded.get(n["id"], []))
        if controls:
            item["controls"] = controls
        relationships.append(item)
    model["nodes"] = calm_nodes
    model["relationships"] = relationships
    top = control_map([c["id"] for c in nodes if c.get("type") == CONTROL and c["id"] not in attached])
    if top:
        model["controls"] = top
    flows = []
    for n in nodes:
        if n.get("type") != FLOW:
            continue
        item = {"unique-id": attrs(n).get("calm_id") or n["id"], "name": n.get("label") or "", "description": n.get("summary") or ""}
        if attrs(n).get("requirement_url"):
            item["requirement-url"] = attrs(n)["requirement_url"]
        steps = [s for s in nodes if s.get("type") == STEP and n["id"] in outgoing.get((s["id"], "step_of"), [])]
        transitions = []
        for s in sorted(steps, key=lambda s: attrs(s).get("sequence", 0)):
            over = outgoing.get((s["id"], "over"), [])
            t = {"relationship-unique-id": calm_id_of(over[0]) if over else None, "sequence-number": attrs(s).get("sequence"), "description": s.get("summary") or ""}
            if attrs(s).get("direction"):
                t["direction"] = attrs(s)["direction"]
            transitions.append(t)
        item["transitions"] = transitions
        controls = control_map(safeguarded.get(n["id"], []))
        if controls:
            item["controls"] = controls
        if attrs(n).get("calm_metadata"):
            item["metadata"] = _loads(attrs(n)["calm_metadata"], {})
        flows.append(item)
    if flows:
        model["flows"] = flows
    return model


# ---- the code map ----

def convention_for(repo_path):
    """`oto.codemap.json` at the repository root, else the default: every directory under src/ is a
    module of the component named after it."""
    path = os.path.join(repo_path, CONVENTION_NAME)
    if not os.path.isfile(path):
        return DEFAULT_CONVENTION
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError as exc:
            raise ArchError("%s is not JSON: %s" % (path, exc))


def _ignored(relative, ignore):
    parts = relative.replace(os.sep, "/").split("/")
    for pattern in ignore:
        if any(fnmatch.fnmatch(part, pattern) for part in parts) or fnmatch.fnmatch(relative.replace(os.sep, "/"), pattern):
            return True
    return False


def _language(directory, ignore):
    counts = collections.Counter()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not _ignored(d, ignore)]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in LANGUAGES:
                counts[LANGUAGES[ext]] += 1
    return counts.most_common(1)[0][0] if counts else None


def _last_commit(repo_path, relative):
    try:
        out = subprocess.run(["git", "-C", repo_path, "log", "-1", "--format=%H%x1f%ad%x1f%an%x1f%s", "--date=short", "--", relative],
                             check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not out:
        return None
    sha, date, author, subject = (out.split("\x1f") + ["", "", "", ""])[:4]
    return {"sha": sha, "committed_on": date, "author": author, "message": subject}


def scan(repo_path, convention):
    """{"modules": [{"path", "component", "language", "commit"}], "git": bool}: the repository read by
    the convention, modules in path order, each once (the first spec that names a path wins)."""
    if not isinstance(convention, dict) or not isinstance(convention.get("modules"), list):
        raise ArchError("a code-map convention is {\"modules\": [{\"path\": \"src/*\", \"component\": \"component.{name}\"}, ...], \"ignore\": [...]}")
    ignore = list(DEFAULT_IGNORE) + [str(x) for x in convention.get("ignore") or []]
    is_git = os.path.isdir(os.path.join(repo_path, ".git"))
    found, seen = [], set()
    for spec in convention["modules"]:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not spec["path"].strip():
            raise ArchError("every module spec names a `path` (a directory or a glob, relative to the repository) and a `component` (an id with {name}, or null)")
        excepted = {str(x).strip("/") for x in spec.get("except") or []}
        matches = sorted(d for d in _glob.glob(os.path.join(repo_path, spec["path"].strip("/"))) if os.path.isdir(d))
        for directory in matches:
            relative = os.path.relpath(directory, repo_path).replace(os.sep, "/")
            if relative in seen or relative in excepted or _ignored(relative, ignore):
                continue
            seen.add(relative)
            component = spec.get("component")
            if isinstance(component, str):
                component = component.replace("{name}", _slug(relative.rsplit("/", 1)[-1])) or None
            found.append({"path": relative, "component": component, "language": _language(directory, ignore),
                          "commit": _last_commit(repo_path, relative) if is_git else None})
    found.sort(key=lambda m: m["path"])
    return {"modules": found, "git": is_git}


def _repository_slug(repository_id):
    return _slug(repository_id.split(".", 1)[1] if "." in repository_id else repository_id)


def module_id(repository_id, path):
    return "codemodule.%s-%s" % (_repository_slug(repository_id), _slug(path))


def module_line(module):
    return "%s (%s)" % (module["path"], module.get("language") or "unknown")


def commit_line(commit):
    """The full sha, so the gate finds the value the fact carries in the document it cites."""
    return "%s %s %s" % (commit["sha"], commit["committed_on"], commit["author"])


def codemap_document(found, repository_id, repo_path, at, source):
    repo = _repository_slug(repository_id)
    title = "Code map of %s" % repo
    lines = ["# %s" % title, "", "Read from %s on %s by `oto arch map` (%s). One line per module, with its language and the component the convention "
             "names, and one per last commit that touched it; each fact in the graph quotes its line here." % (repo_path, at, source), "", "## Modules", ""]
    for m in found["modules"]:
        lines.append("- %s: %s" % (module_line(m), m["component"] or "no component"))
        if m.get("commit"):
            lines.append("  - %s: %s" % (commit_line(m["commit"]), m["commit"]["message"]))
    return title, "\n".join(lines).rstrip() + "\n"


def propose_codemap(found, repository_id, doc, at, graph_ids, repo_path, source):
    """(proposal, gaps): modules, their commits and the edges to the estate's repository and components."""
    repo = _repository_slug(repository_id)
    title, _text = codemap_document(found, repository_id, repo_path, at, source)
    nodes = [{"id": "document.%s" % doc, "type": DOCUMENT, "label": title, "summary": "The code map of %s as `oto arch map` read it; the date is the fact's own." % repo,
              "attributes": {"kind": "architecture"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": title}]}]
    edges, gaps, commits = [], [], {}
    for m in found["modules"]:
        mid = module_id(repository_id, m["path"])
        attributes = {"path": m["path"]}
        if m.get("language"):
            attributes["language"] = m["language"]
        nodes.append({"id": mid, "type": MODULE, "label": m["path"], "summary": "The %s module of %s." % (m["path"], repo), "attributes": attributes,
                      "valid_from": at, "evidence": [{"doc": doc, "where": "modules", "quote": module_line(m)}]})
        edges.append({"from": mid, "rel": "located_in", "to": repository_id})
        if m["component"]:
            if m["component"] in graph_ids:
                edges.append({"from": m["component"], "rel": "implemented_by", "to": mid})
            else:
                gaps.append("%s: the convention names %s, which the graph lacks; the module is proposed untraced (AR9 lists it)" % (m["path"], m["component"]))
        if m.get("commit"):
            c = m["commit"]
            cid = "commit.%s" % c["sha"][:12]
            if cid not in commits:
                commits[cid] = True
                nodes.append({"id": cid, "type": COMMIT, "label": "%s %s" % (c["sha"][:7], c["message"]), "summary": c["message"],
                              "attributes": {"sha": c["sha"], "committed_on": c["committed_on"], "author": c["author"], "message": c["message"]},
                              "valid_from": c["committed_on"] or at, "evidence": [{"doc": doc, "where": "modules", "quote": commit_line(c)}]})
            edges.append({"from": cid, "rel": "touches", "to": mid})
    if not found["git"]:
        gaps.append("%s is not a git checkout: no commits recorded" % repo_path)
    return {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": edges}, gaps


def map_repo(project, repo_path, repository_id, at, name=None):
    """Scan, write the document and the proposal. Returns {"doc", "document", "archive", "proposal",
    "modules", "commits", "gaps", "convention"}."""
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date the code was read is never defaulted")
    if not repository_id:
        raise ArchError("--repository repo.<id> names the Repository the estate declares (SA14), where these modules live")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if MODULE not in classes or COMMIT not in classes:
        raise ArchError("the vocabulary declares no CodeModule and Commit: the architecture ontology does (oto init --ontology architecture, or compose it)")
    if not os.path.isdir(repo_path):
        raise ArchError("no such repository: %s" % repo_path)
    from .data import _graph_ids
    graph_ids = _graph_ids(project)
    if repository_id not in graph_ids:
        raise ArchError("the graph holds no %s. The estate declares the repository (a Repository node, SA14) before the code map describes it" % repository_id)
    convention = convention_for(repo_path)
    source = CONVENTION_NAME if os.path.isfile(os.path.join(repo_path, CONVENTION_NAME)) else "the default convention, src/*"
    found = scan(repo_path, convention)
    doc = "codemap-%s" % (_slug(name) if name else _repository_slug(repository_id))
    title, text = codemap_document(found, repository_id, repo_path, at, source)
    proposal, gaps = propose_codemap(found, repository_id, doc, at, graph_ids, repo_path, source)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "modules": len(found["modules"]),
            "commits": sum(1 for n in proposal["nodes"] if n["type"] == COMMIT), "gaps": gaps, "convention": source}


# ---- compile on merge ----

def compile_project(project, at, by, note=None):
    """What project.config.json declares under `arch`, imported and mapped, through the gates, applied
    and built. Returns {"proposals": [...], "gaps": [...], "applied": True, "built": True}. Refused
    at the gate, it aborts the candidate and raises with the findings."""
    from .curate import session as _session
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date of the merge is never defaulted")
    if not (by or "").strip():
        raise ArchError("--by names who compiles: the workflow, or a person")
    arch_cfg = project.config().get("arch") or {}
    calm_paths = arch_cfg.get("calm") or []
    codemap = arch_cfg.get("codemap") or {}
    if not calm_paths and not codemap:
        raise ArchError("project.config.json declares no `arch`: {\"calm\": [\"<model.json>\", ...], \"environment\": \"environment.<id>\", "
                        "\"codemap\": {\"repo\": \"<path>\", \"repository\": \"repo.<id>\"}}. Nothing to compile")
    if _session.exists(project):
        raise ArchError("a candidate is open: apply or abort it before compiling (oto curate apply / abort)")
    proposals, gaps = [], []
    for relative in calm_paths:
        done = import_calm(project, os.path.join(project.data, relative), at, environment=arch_cfg.get("environment"))
        proposals.append(done["proposal"])
        gaps += done["gaps"]
    if codemap:
        if not codemap.get("repository"):
            raise ArchError("arch.codemap names no `repository`: the Repository the estate declares")
        done = map_repo(project, os.path.join(project.data, codemap.get("repo") or "."), codemap["repository"], at)
        proposals.append(done["proposal"])
        gaps += done["gaps"]
    apply_proposals(project, proposals, by, note or "compiled by oto arch compile")
    return {"proposals": proposals, "gaps": gaps, "applied": True, "built": True}


def apply_proposals(project, proposals, by, note):
    """Open a candidate, add each proposal, check, apply with `by` and `note`, build. Refused at the
    gate, it aborts the candidate and raises with the findings; the graph is unchanged. A command
    that generates facts a person never typed (a CALM import, the IAM bindings) lands them this way,
    through the same gates as everything else, never by writing the graph."""
    from .cli import main as _main
    root = project.data
    if not (by or "").strip():
        raise ArchError("--by names who applies: the workflow, or a person")

    def run(*args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = _main(list(args) + ["--project", root])
        return code, out.getvalue()

    code, out = run("curate", "start")
    if code != 0:
        raise ArchError("could not open a candidate:\n%s" % out.strip())
    try:
        for path in proposals:
            code, out = run("curate", "add", "--from", path)
            if code != 0:
                raise ArchError("refused while adding %s:\n%s" % (os.path.relpath(path, root), out.strip()))
        code, out = run("curate", "check")
        if code != 0:
            findings = out.split("gap (")[0] if "blocking (" in out.split("gap (")[0] else out
            findings = findings[findings.index("blocking ("):] if "blocking (" in findings else findings
            raise ArchError("refused at the gate; the graph is unchanged:\n%s" % findings.strip())
        code, out = run("curate", "apply", "--by", by.strip(), "--note", note.strip())
        if code != 0:
            raise ArchError("could not apply:\n%s" % out.strip())
    except ArchError:
        run("curate", "abort")
        raise
    code, out = run("build")
    if code != 0:
        raise ArchError("applied, but the build failed:\n%s" % out.strip())


# ---- impact (H4) ----

def _graph_index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    out, inc = {}, {}
    for e in graph.get("edges") or []:
        out.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
        inc.setdefault((e.get("to"), e.get("rel")), []).append(e.get("from"))
    return nodes, out, inc


def decision_id(term):
    """decision.adr-007 as given, or ADR-007 the way a decision record names itself."""
    from . import adr as _adr
    term = (term or "").strip()
    return _adr.node_id(term) if _adr.ID.match(term) else term


def impact(graph, decision):
    """{"id", "label", "status", "superseded_by", "governs": [{"id", "label", "type", "connections", "modules", "proposals"}],
    "reached": [labels], "modules": [paths], "proposals": [labels]} for a decision."""
    nodes, out, inc = _graph_index(graph)
    did = decision_id(decision)
    d = nodes.get(did)
    if d is None:
        raise ArchError("the graph holds no %s" % did)
    if d.get("type") != "Decision":
        raise ArchError("%s is a %s, not a Decision" % (did, d.get("type")))
    report = {"id": did, "label": d.get("label") or did, "status": "superseded" if d.get("status") == "superseded" else (d.get("attributes") or {}).get("status") or d.get("status"),
              "superseded_by": d.get("superseded_by"), "superseded_by_label": nodes.get(d.get("superseded_by"), {}).get("label") if d.get("superseded_by") else None,
              "governs": [], "reached": [], "modules": [], "proposals": []}
    for gid in out.get((did, "governs"), []) + [x for x in out.get((did, "about"), []) if x not in out.get((did, "governs"), [])]:
        g = nodes.get(gid)
        if g is None:
            continue
        item = {"id": gid, "label": g.get("label") or gid, "type": g.get("type"), "connections": [], "modules": [], "proposals": []}
        for rid in inc.get((gid, "connects_from"), []) + inc.get((gid, "connects_to"), []):
            r = nodes.get(rid)
            if r is None:
                continue
            others = [x for x in out.get((rid, "connects_to"), []) + out.get((rid, "connects_from"), []) if x != gid]
            for other in others or [None]:
                item["connections"].append({"id": rid, "label": r.get("label") or rid, "kind": (r.get("attributes") or {}).get("kind"),
                                            "protocol": (r.get("attributes") or {}).get("protocol"),
                                            "other": nodes.get(other, {}).get("label") if other else None, "other_id": other})
                if other and nodes.get(other, {}).get("label") not in report["reached"] and other != gid:
                    report["reached"].append(nodes.get(other, {}).get("label") or other)
        for mid in out.get((gid, "implemented_by"), []):
            m = nodes.get(mid)
            if m and m.get("type") == "CodeModule":
                path = (m.get("attributes") or {}).get("path") or m.get("label")
                item["modules"].append(path)
                if path not in report["modules"]:
                    report["modules"].append(path)
        for pid in inc.get((gid, "proposes_change_to"), []):
            p = nodes.get(pid)
            if p and ((p.get("attributes") or {}).get("status") or "proposed") == "proposed":
                item["proposals"].append(p.get("label") or pid)
                if (p.get("label") or pid) not in report["proposals"]:
                    report["proposals"].append(p.get("label") or pid)
        report["governs"].append(item)
    return report


def render_impact(report, fmt="text"):
    md = fmt == "markdown"
    head = "## Impact of %s" % report["label"] if md else "Impact of %s" % report["label"]
    L = [head, ""]
    status = "Status: %s" % report["status"]
    if report.get("superseded_by"):
        status += ", superseded by %s" % (report.get("superseded_by_label") or report["superseded_by"])
    L.append(status + ".")
    L.append("")
    if not report["governs"]:
        L.append("Governs nothing the graph holds.")
    else:
        L.append("Governs %d node(s):" % len(report["governs"]))
        for g in report["governs"]:
            bits = ["%d connection(s)" % len(g["connections"])]
            if g["modules"]:
                bits.append("module(s) %s" % ", ".join(g["modules"]))
            if g["proposals"]:
                bits.append("open proposal(s) %s" % ", ".join(g["proposals"]))
            L.append("- %s (%s): %s" % (g["label"], g["id"], ", ".join(bits)))
    if report["reached"]:
        L.append("")
        L.append("Reached through their connections: %s." % ", ".join(report["reached"]))
    if report["modules"]:
        L.append("")
        L.append("Modules to check: %s." % ", ".join(report["modules"]))
    if report["proposals"]:
        L.append("")
        L.append("Open change proposals: %s." % ", ".join(report["proposals"]))
    return "\n".join(L).rstrip() + "\n"


ORPHAN_TYPES = ("System", "Component", "DataStore", "Interface")


def orphans(graph):
    """Systems, components, stores and interfaces no relationship reaches: not an end of any
    Relationship, and for an interface, exposed or consumed by nothing and on no connection."""
    nodes, out, inc = _graph_index(graph)
    found = []
    for n in nodes.values():
        if n.get("type") not in ORPHAN_TYPES or n.get("status") == "superseded":
            continue
        nid = n["id"]
        if n["type"] == "Interface":
            reached = inc.get((nid, "exposes"), []) or inc.get((nid, "consumes"), []) or inc.get((nid, "via"), [])
            why = "exposed by nothing, consumed by nothing, on no connection"
        else:
            reached = inc.get((nid, "connects_from"), []) or inc.get((nid, "connects_to"), [])
            why = "an end of no relationship"
        if not reached:
            found.append({"id": nid, "label": n.get("label") or nid, "type": n["type"], "why": why})
    return sorted(found, key=lambda x: (x["type"], x["label"]))


def untraced(graph):
    """{"modules": [{"id", "path"}], "components": [{"id", "label"}]}: modules nothing implements, components with no module."""
    nodes, out, inc = _graph_index(graph)
    modules = [{"id": n["id"], "path": (n.get("attributes") or {}).get("path") or n.get("label")} for n in nodes.values()
               if n.get("type") == "CodeModule" and n.get("status") != "superseded" and not inc.get((n["id"], "implemented_by"))]
    components = [{"id": n["id"], "label": n.get("label") or n["id"]} for n in nodes.values()
                  if n.get("type") == "Component" and n.get("status") != "superseded"
                  and not any(nodes.get(m, {}).get("type") == "CodeModule" for m in out.get((n["id"], "implemented_by"), []))]
    return {"modules": sorted(modules, key=lambda m: m["path"]), "components": sorted(components, key=lambda c: c["label"])}


def render_orphans(found, fmt="text"):
    L = ["## Orphans" if fmt == "markdown" else "Orphans: nodes no relationship reaches", ""]
    if not found:
        L.append("none: every system, component, store and interface is an end of a relationship.")
    for o in found:
        L.append("- %s (%s, %s): %s" % (o["label"], o["id"], o["type"], o["why"]))
    return "\n".join(L).rstrip() + "\n"


def render_untraced(found, fmt="text"):
    L = ["## Untraced code" if fmt == "markdown" else "Untraced code", ""]
    L.append("Modules nothing implements (%d):" % len(found["modules"]))
    L += ["- %s (%s)" % (m["path"], m["id"]) for m in found["modules"]] or ["- none"]
    L.append("")
    L.append("Components with no module (%d):" % len(found["components"]))
    L += ["- %s (%s)" % (c["label"], c["id"]) for c in found["components"]] or ["- none"]
    return "\n".join(L).rstrip() + "\n"


def impact_of_files(project, paths, fmt="markdown"):
    """The impact of every decision record among `paths`, rendered; "" when none is one. A record
    whose decision the graph does not hold yet is named, so the reviewer knows."""
    from . import adr as _adr
    from .curate import session as _session
    graph = None
    out = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if not _adr.is_adr(text):
            continue
        record = _adr.parse(text)
        adr_id = str(record["front"].get("id") or "").strip()
        did = _adr.node_id(adr_id) if adr_id else None
        if graph is None:
            graph = _session.live(project)
        try:
            out.append(render_impact(impact(graph, did), fmt))
        except ArchError:
            head = "## %s" if fmt == "markdown" else "%s"
            out.append((head % ("Impact of %s" % (adr_id or os.path.basename(path)))) + "\n\nThe decision is not in the graph yet (%s): its impact is what this pull request adds. "
                       "Once applied, `oto arch impact --decision %s` reads it.\n" % (did or "no id", adr_id or "<id>"))
    return "\n".join(out)
