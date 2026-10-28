# -*- coding: utf-8 -*-
"""The CALM pack's adapter (ADR-0006, step 3): the FINOS Common Architecture Language Model read into
the architecture graph and written back out, chosen by `oto arch import --framework calm`.

A CALM node is an estate node (System, Component, DataStore, Environment, Role by its node-type: an
ldap directory is a store of identities; any other type a Component) carrying the framework-neutral
attributes the architecture pack declares: `external_id` (CALM's unique-id), `external_type` (the
node-type as given) and `external_payload` (what CALM carries that no question asks for: metadata,
details, kept as the JSON it gave). A relationship is a `Relationship` node with its ends, kind and
protocol; controls and flows are nodes; the plain estate edges are derived beside them (part_of from
composed-of in a system, runs_in from deployed-in in a network, exposes from a node's interfaces,
consumes and depends_on from connects) so the estate's own questions answer. The model's document
carries `framework: calm` and its header as payload, which is how the export finds the model.

`read_model` writes a document in the corpus (`build/documents/calm-<slug>.md`, kept in `archive/`:
one line per node, interface, relationship, control, flow and step, each the evidence its fact
quotes) and a proposal that goes through the gates like any other change. `write_model` walks the
live graph back into a CALM model: export of import equals the input, up to what the graph cannot
tell from absence. What CALM does not say is not invented: a node CALM deploys nowhere runs nowhere
unless `environment` names the estate's environment, and a node CALM composes in nothing is part of
nothing, which the estate's shape names at the gate. `migrate` rewrites a graph written before the
architecture pack's release 5 (`calm_id`, `calm_type`, `calm_metadata`, `calm_details`, `calm_header`,
`calm_option`) into the neutral names.

Aligned with CALM 1.0 (https://calm.finos.org/release/1.0/meta/core.json); the core schema is
unchanged through 1.3. The engine knows none of this: the architecture pack's manifest no longer
names CALM, and this module is loaded through the calm pack's `provides.adapters`.
"""
import json
import os

from ..arch import ArchError, CONTROL, DECISION, DOCUMENT, FLOW, INTERFACE, ISO_DATE, PREFIX, RELATIONSHIP, STEP
from ..data import _slug

FRAMEWORK = "calm"
IAM_BINDING = "IamBinding"                       # the policy pack's binding node: exported as a control when both packs are composed
IAM_REQUIREMENT_URL = "https://cynergis.ai/controls/iam-bindings.requirement.json"
NODE_CLASS = {"system": "System", "ecosystem": "System", "service": "Component", "webclient": "Component",
              "database": "DataStore", "data-asset": "DataStore", "datastore": "DataStore", "ldap": "DataStore", "network": "Environment", "actor": "Role"}
DEFAULT_CLASS = "Component"
DEFAULT_TYPE = {"System": "system", "Component": "service", "DataStore": "database", "Environment": "network", "Role": "actor"}
SHAPES = ("interacts", "connects", "deployed-in", "composed-of", "options")
PROTOCOLS = ("HTTP", "HTTPS", "FTP", "SFTP", "JDBC", "WebSocket", "SocketIO", "LDAP", "AMQP", "TLS", "mTLS", "TCP")
HEADER_SKIP = ("nodes", "relationships", "controls", "flows")


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
    lines = ["# %s" % doc_title, "", "Read from %s on %s by `oto arch import --framework calm`%s. One line per node, interface, relationship, control, "
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
            attributes = {"external_id": str(cid)}
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
         model.get("description") or "A CALM model, as `oto arch import` read it.", {"kind": "architecture", "framework": FRAMEWORK, "external_payload": _json(header)}, "title", title)
    interfaces = {}
    for uid, item in nodes.items():
        n, cls, nid = item["node"], item["class"], item["id"]
        attributes = {"external_id": uid, "external_type": str(n["node-type"])}
        payload = {k: n[k] for k in ("metadata", "details") if n.get(k) is not None}
        if payload:
            attributes["external_payload"] = _json(payload)
        node(nid, cls, n.get("name") or uid, n.get("description") or "", attributes, "nodes", "%s (%s)" % (uid, n["node-type"]))
        for i in n.get("interfaces") or []:
            if not isinstance(i, dict) or not i.get("unique-id"):
                raise ArchError("an interface of node %r carries no unique-id" % uid)
            iuid = str(i["unique-id"])
            iid = "interface.%s" % _slug(iuid)
            if iuid in interfaces:
                raise ArchError("interface %r is declared twice" % iuid)
            rest = {k: v for k, v in i.items() if k != "unique-id"}
            iattr = {"external_id": iuid, "config": _json(rest)}
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
        attributes = {"external_id": ruid, "kind": kind}
        if rel.get("protocol"):
            if rel["protocol"] in PROTOCOLS:
                attributes["protocol"] = rel["protocol"]
            else:
                gaps.append("relationship %s speaks %r, not one of CALM's protocols; kept in metadata only" % (ruid, rel["protocol"]))
        if rel.get("metadata") is not None:
            attributes["external_payload"] = _json({"metadata": rel["metadata"]})
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
                     {"status": "proposed", "external_payload": _json(decision)}, "relationships", "%s option %d" % (ruid, n))
                edge(rid, "offers_option", did)
        controls(ruid, rel.get("controls"), rid, "relationships")
    controls("model", model.get("controls"), None, "controls")
    for flow in model.get("flows") or []:
        if not isinstance(flow, dict) or not flow.get("unique-id"):
            raise ArchError("a CALM flow carries unique-id, name, description and transitions")
        fuid = str(flow["unique-id"])
        fid = "flow.%s" % _slug(fuid)
        attributes = {"external_id": fuid}
        if flow.get("requirement-url"):
            attributes["requirement_url"] = flow["requirement-url"]
        if flow.get("metadata") is not None:
            attributes["external_payload"] = _json({"metadata": flow["metadata"]})
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


def read_model(project, path, at, name=None, environment=None):
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
        from ..data import _graph_ids
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


def write_model(project):
    """The live graph's CALM facts as a model: nodes with a external_id, relationships, controls and flows."""
    from ..curate import session as _session
    graph = _session.live(project)
    nodes = [n for n in graph.get("nodes") or [] if n.get("id")]
    by_id = {n["id"]: n for n in nodes}
    edges = graph.get("edges") or []
    headers = [n for n in nodes if n.get("type") == DOCUMENT and (n.get("attributes") or {}).get("framework") == FRAMEWORK]
    if not headers and not any(n.get("type") == RELATIONSHIP for n in nodes):
        raise ArchError("the graph holds no CALM model: nothing to export (oto arch import --framework calm --file <model> first)")
    model = dict(_loads((headers[0].get("attributes") or {}).get("external_payload"), {})) if headers else {}
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
    iam_controls = {}                                                # node id -> {control id: body}, the policy pack's bindings as controls
    for b in nodes:
        if b.get("type") != IAM_BINDING:
            continue
        ba = attrs(b)
        cid = "iam-%s" % (b["id"].split(".", 1)[1] if "." in b["id"] else b["id"])
        body = {"description": b.get("summary") or "",
                "requirements": [{"requirement-url": IAM_REQUIREMENT_URL,
                                  "config": {"provider": ba.get("provider"), "resource": ba.get("resource_uri"),
                                             "bindings": _loads(ba.get("bindings"), []), "withheld": _loads(ba.get("withheld"), [])}}]}
        targets = set(outgoing.get((b["id"], "binds"), []))
        for pid in outgoing.get((b["id"], "grants"), []):
            targets |= {e["from"] for e in edges if e.get("rel") == "runs_as" and e.get("to") == pid}
        for t in targets:
            iam_controls.setdefault(t, {})[cid] = body

    def control_map(cids):
        mapping = {}
        for cid in cids:
            c = by_id.get(cid)
            if c is None:
                continue
            body = {"description": c.get("summary") or ""}
            body.update(_loads(attrs(c).get("config"), {}))
            mapping[attrs(c).get("external_id") or cid] = body
        return mapping

    calm_nodes = []
    for n in nodes:
        if n.get("type") not in PREFIX or not attrs(n).get("external_id"):
            continue
        item = {"unique-id": attrs(n)["external_id"], "node-type": attrs(n).get("external_type") or DEFAULT_TYPE[n["type"]],
                "name": n.get("label") or attrs(n)["external_id"], "description": n.get("summary") or ""}
        payload = _loads(attrs(n).get("external_payload"), {})
        if payload.get("details") is not None:
            item["details"] = payload["details"]
        interfaces = []
        for iid in exposes.get(n["id"], []):
            i = by_id[iid]
            if attrs(i).get("external_id"):
                interfaces.append(dict({"unique-id": attrs(i)["external_id"]}, **_loads(attrs(i).get("config"), {})))
        if interfaces:
            item["interfaces"] = interfaces
        controls = control_map(safeguarded.get(n["id"], []))
        controls.update(iam_controls.get(n["id"], {}))
        if controls:
            item["controls"] = controls
        if payload.get("metadata") is not None:
            item["metadata"] = payload["metadata"]
        calm_nodes.append(item)
    external_id_of = lambda nid: attrs(by_id.get(nid, {})).get("external_id") or nid  # noqa: E731
    relationships = []
    for n in nodes:
        if n.get("type") != RELATIONSHIP:
            continue
        kind = attrs(n).get("kind")
        item = {"unique-id": attrs(n).get("external_id") or n["id"]}
        if n.get("summary"):
            item["description"] = n["summary"]
        sources = outgoing.get((n["id"], "connects_from"), [])
        targets = outgoing.get((n["id"], "connects_to"), [])
        if kind == "interacts":
            item["relationship-type"] = {"interacts": {"actor": external_id_of(sources[0]) if sources else None, "nodes": [external_id_of(t) for t in targets]}}
        elif kind == "connects":
            via = outgoing.get((n["id"], "via"), [])
            src = {"node": external_id_of(sources[0]) if sources else None}
            dst = {"node": external_id_of(targets[0]) if targets else None}
            src_if = [external_id_of(i) for i in via if sources and i in exposes.get(sources[0], [])]
            dst_if = [external_id_of(i) for i in via if targets and i in exposes.get(targets[0], [])]
            if src_if:
                src["interfaces"] = src_if
            if dst_if:
                dst["interfaces"] = dst_if
            item["relationship-type"] = {"connects": {"source": src, "destination": dst}}
        elif kind in ("deployed-in", "composed-of"):
            item["relationship-type"] = {kind: {"container": external_id_of(sources[0]) if sources else None, "nodes": [external_id_of(t) for t in targets]}}
        elif kind == "options":
            item["relationship-type"] = {"options": [_loads(attrs(by_id[d]).get("external_payload"), {"description": by_id[d].get("label")})
                                                     for d in outgoing.get((n["id"], "offers_option"), []) if d in by_id]}
        if attrs(n).get("protocol"):
            item["protocol"] = attrs(n)["protocol"]
        if _loads(attrs(n).get("external_payload"), {}).get("metadata") is not None:
            item["metadata"] = _loads(attrs(n)["external_payload"], {})["metadata"]
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
        item = {"unique-id": attrs(n).get("external_id") or n["id"], "name": n.get("label") or "", "description": n.get("summary") or ""}
        if attrs(n).get("requirement_url"):
            item["requirement-url"] = attrs(n)["requirement_url"]
        steps = [s for s in nodes if s.get("type") == STEP and n["id"] in outgoing.get((s["id"], "step_of"), [])]
        transitions = []
        for s in sorted(steps, key=lambda s: attrs(s).get("sequence", 0)):
            over = outgoing.get((s["id"], "over"), [])
            t = {"relationship-unique-id": external_id_of(over[0]) if over else None, "sequence-number": attrs(s).get("sequence"), "description": s.get("summary") or ""}
            if attrs(s).get("direction"):
                t["direction"] = attrs(s)["direction"]
            transitions.append(t)
        item["transitions"] = transitions
        controls = control_map(safeguarded.get(n["id"], []))
        if controls:
            item["controls"] = controls
        if _loads(attrs(n).get("external_payload"), {}).get("metadata") is not None:
            item["metadata"] = _loads(attrs(n)["external_payload"], {})["metadata"]
        flows.append(item)
    if flows:
        model["flows"] = flows
    return model


# ---- a graph written before release 5 of the architecture pack ----

RENAMED = {"calm_id": "external_id", "calm_type": "external_type"}
PAYLOAD = {"calm_metadata": "metadata", "calm_details": "details"}


def migrate_attributes(node):
    """The node's attributes with CALM's former names read as the neutral ones; True when anything changed."""
    a = node.get("attributes")
    if not isinstance(a, dict):
        return False
    changed = False
    for old, new in RENAMED.items():
        if old in a:
            a[new] = a.pop(old)
            changed = True
    payload = _loads(a.get("external_payload"), {}) if a.get("external_payload") else {}
    for old, key in PAYLOAD.items():
        if old in a:
            payload[key] = _loads(a.pop(old), {})
            changed = True
    if payload:
        a["external_payload"] = _json(payload)
    if "calm_header" in a:
        a["external_payload"] = a.pop("calm_header")
        a["framework"] = FRAMEWORK
        changed = True
    if "calm_option" in a:
        a["external_payload"] = a.pop("calm_option")
        changed = True
    return changed


def migrate(project, by):
    """Rewrite the live graph's CALM-named attributes into the architecture pack's neutral names, once,
    with an audit record. Refused while a candidate is open. Returns the number of nodes changed."""
    from .. import audit as _audit
    from ..curate import session as _session
    if _session.exists(project):
        raise ArchError("a candidate is open: apply or abort it before migrating (oto curate apply / abort)")
    if not (by or "").strip():
        raise ArchError("--by names who migrates")
    path = os.path.join(project.data, "graph.json")
    with open(path, encoding="utf-8") as f:
        graph = json.load(f)
    changed = [n["id"] for n in graph.get("nodes") or [] if migrate_attributes(n)]
    if changed:
        previous = os.path.join(project.data, "graph.previous.json")
        with open(path, encoding="utf-8") as f:
            before = f.read()
        with open(previous, "w", encoding="utf-8", newline="\n") as f:
            f.write(before)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
            f.write("\n")
        _audit.append(project, "arch migrate", by.strip(), changed, "applied",
                      "calm_* attributes read as external_id, external_type, external_payload and framework on %d node(s)" % len(changed))
    return len(changed)
