# -*- coding: utf-8 -*-
"""Compare a candidate graph against the live one, and say what it would do.

Curation is the only step that changes what the knowledge base believes, so it is the only step that
must never happen by accident. Edits land in a candidate file; this module reports exactly what
promoting it would change, and refuses to let a few specific mistakes through.

The most important check is the contradiction one. When a fact changes, the old fact must be kept and
marked superseded, not overwritten. An overwrite destroys the answer to "what did we believe on the
14th", which is the property the whole system exists to protect. So a changed value with no
supersession record is reported, every time.
"""
import re

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VALID_STATUS = ("current", "superseded", "proposed", "intended")

#: Fields whose change means the graph now asserts something different.
FACTUAL_FIELDS = ("type", "label", "summary", "attributes")

#: Fields that record provenance and time rather than the fact itself.
TEMPORAL_FIELDS = ("as_of", "valid_from", "valid_to", "status", "supersedes", "superseded_by",
                   "source_doc", "change_note")

#: Who attests a fact. Separated from both lists above and reported on its own, because a change
#: here changes nothing about what the graph says and everything about whether it can be trusted.
#: `oto vet` exists to rewrite these fields, and while they were unwatched it could rewrite the
#: provenance of the whole graph and `oto curate check` would print "nodes: ~0". A review gate that
#: cannot see the change it is reviewing is not a gate.
PROVENANCE_FIELDS = ("sources", "source_doc", "provenance", "provenance_note")

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"


class Finding:
    """One thing worth saying about a proposed change."""

    BLOCKING = "blocking"
    CONTRADICTION = "contradiction"
    GAP = "gap"

    __slots__ = ("severity", "subject", "detail")

    def __init__(self, severity, subject, detail):
        self.severity = severity
        self.subject = subject
        self.detail = detail

    def __repr__(self):
        return "%s %s: %s" % (self.severity, self.subject, self.detail)


def index_nodes(graph):
    return {n.get("id"): n for n in (graph.get("nodes") or []) if n.get("id")}


def edge_key(edge):
    return (edge.get("from"), edge.get("rel"), edge.get("to"))


def _changed_fields(old, new):
    """The factual fields whose value changed. An attribute added to a node is new knowledge, not
    a change; an attribute whose value differs, or that went missing, is."""
    out = []
    for f in FACTUAL_FIELDS:
        if f == "attributes":
            a, b = old.get(f) or {}, new.get(f) or {}
            if any(k not in b or b[k] != v for k, v in a.items()):
                out.append(f)
        elif old.get(f) != new.get(f):
            out.append(f)
    return out


def _provenance_fields(old, new):
    return [f for f in PROVENANCE_FIELDS if old.get(f) != new.get(f)]


def summarize(live, candidate):
    """What promoting the candidate would change."""
    old_nodes, new_nodes = index_nodes(live), index_nodes(candidate)
    old_edges = {edge_key(e) for e in (live.get("edges") or [])}
    new_edges = {edge_key(e) for e in (candidate.get("edges") or [])}

    changed, reprovenanced = [], []
    for nid in sorted(set(old_nodes) & set(new_nodes)):
        fields = _changed_fields(old_nodes[nid], new_nodes[nid])
        if fields:
            changed.append((nid, fields))
        provenance = _provenance_fields(old_nodes[nid], new_nodes[nid])
        if provenance:
            reprovenanced.append((nid, provenance))

    return {
        "nodes_added": sorted(set(new_nodes) - set(old_nodes)),
        "nodes_removed": sorted(set(old_nodes) - set(new_nodes)),
        "nodes_changed": changed,
        "nodes_reprovenanced": reprovenanced,
        "edges_added": sorted(new_edges - old_edges),
        "edges_removed": sorted(old_edges - new_edges),
    }


def check(live, candidate, vocabulary=None, known_assertions=None):
    """Every finding about the candidate, most severe first.

    `vocabulary` is the declared classes and properties. Without it the vocabulary checks are skipped,
    because reporting every type as undeclared would drown the real findings.

    `known_assertions` is the set of assertion identifiers on record. A fact citing one that is not
    there is blocking: without that check the identifier would be decoration, and an unverifiable
    citation is worse than none because it looks checkable.
    """
    findings = []
    nodes = candidate.get("nodes") or []
    edges = candidate.get("edges") or []
    by_id = index_nodes(candidate)
    live_by_id = index_nodes(live)

    # ---- blocking: the graph would not be usable ----
    seen = {}
    for node in nodes:
        nid = node.get("id")
        if not nid:
            findings.append(Finding(Finding.BLOCKING, "(no id)",
                                    "a node has no id: %s" % str(node)[:60]))
            continue
        seen[nid] = seen.get(nid, 0) + 1
    for nid, count in sorted(seen.items()):
        if count > 1:
            findings.append(Finding(Finding.BLOCKING, nid,
                                    "duplicate node id appears %d times" % count))

    for node in nodes:
        nid = node.get("id") or "(no id)"
        status = node.get("status", "current")
        if status not in VALID_STATUS:
            findings.append(Finding(Finding.BLOCKING, nid,
                                    "invalid status %r, expected one of %s"
                                    % (status, ", ".join(VALID_STATUS))))
        for field in ("as_of", "valid_from", "valid_to"):
            value = node.get(field)
            if value and not ISO_DATE.match(str(value)):
                findings.append(Finding(Finding.BLOCKING, nid,
                                        "%s=%r is not a YYYY-MM-DD date" % (field, value)))
        for field in ("supersedes", "superseded_by"):
            targets = node.get(field)
            if not targets:
                continue
            for target in (targets if isinstance(targets, list) else [targets]):
                if target not in by_id and target not in live_by_id:
                    findings.append(Finding(Finding.BLOCKING, nid,
                                            "%s points at unknown id %r" % (field, target)))

    for edge in edges:
        key = edge_key(edge)
        for end in ("from", "to"):
            if edge.get(end) not in by_id:
                findings.append(Finding(Finding.BLOCKING, "%s -%s-> %s" % key,
                                        "%s points at unknown node %r" % (end, edge.get(end))))

    if vocabulary:
        classes = vocabulary.get("classes") or {}
        properties = vocabulary.get("properties") or {}
        for node in nodes:
            if node.get("type") not in classes:
                findings.append(Finding(Finding.BLOCKING, node.get("id") or "(no id)",
                                        "type %r is not declared in the vocabulary"
                                        % node.get("type")))
        for edge in edges:
            if edge.get("rel") not in properties:
                findings.append(Finding(Finding.BLOCKING, "%s -%s-> %s" % edge_key(edge),
                                        "relation %r is not declared in the vocabulary"
                                        % edge.get("rel")))

    if known_assertions is not None:
        from . import assertions as _assertions
        for nid, detail in _assertions.check_nodes(nodes, known_assertions):
            findings.append(Finding(Finding.BLOCKING, nid, detail))

    # ---- contradiction: a fact changed with no supersession record ----
    for nid in sorted(set(by_id) & set(live_by_id)):
        old, new = live_by_id[nid], by_id[nid]
        fields = _changed_fields(old, new)
        if not fields:
            continue
        recorded = bool(new.get("supersedes")) or bool(new.get("superseded_by")) \
            or new.get("status") == "superseded" or old.get("status") == "superseded" \
            or (old.get("status") == "intended" and new.get("status") == "current")     # a plan became real
        if not recorded:
            findings.append(Finding(
                Finding.CONTRADICTION, nid,
                "%s changed with no supersession record. Keep the old fact and mark it superseded, "
                "rather than overwriting it." % ", ".join(fields)))

    # ---- supersession chains must be consistent both ways, with a clean date handoff ----
    def _lookup(target):
        return by_id.get(target) or live_by_id.get(target)

    for node in nodes:
        nid = node.get("id") or "(no id)"
        successor_id = node.get("superseded_by")
        if successor_id:
            successor = _lookup(successor_id)
            if successor is not None:
                back = successor.get("supersedes")
                back = back if isinstance(back, list) else [back] if back else []
                if nid not in back:
                    findings.append(Finding(Finding.BLOCKING, nid,
                                            "superseded_by %r, but that node does not record supersedes %r: "
                                            "the chain must point both ways" % (successor_id, nid)))
                if node.get("status") != "superseded":
                    findings.append(Finding(Finding.BLOCKING, nid,
                                            "has superseded_by but status is %r, not superseded"
                                            % node.get("status", "current")))
                if node.get("valid_to") and successor.get("valid_from") \
                        and node["valid_to"] != successor["valid_from"]:
                    findings.append(Finding(Finding.GAP, nid,
                                            "valid_to=%s but its successor's valid_from=%s: the dates should "
                                            "hand over" % (node["valid_to"], successor["valid_from"])))
        for old_id in (node.get("supersedes") if isinstance(node.get("supersedes"), list)
                       else [node.get("supersedes")] if node.get("supersedes") else []):
            old = _lookup(old_id)
            if old is not None and old.get("status") != "superseded":
                findings.append(Finding(Finding.BLOCKING, nid,
                                        "supersedes %r, but that node is still %r: retire it"
                                        % (old_id, old.get("status", "current"))))

    # ---- conformance: declared, but not as declared. Advisory, like `oto ontology check` ----
    if vocabulary:
        from ..model import vocabulary as _vocab
        declared = _vocab.Vocabulary.from_config(vocabulary)
        attrs = _vocab.attribute_conformance(declared, nodes)
        for nid, key, why, value in attrs["mistyped"]:
            findings.append(Finding(Finding.BLOCKING, nid, "attribute %s = %r: %s" % (key, value, why)))
        for (kind, key), count in attrs["undeclared"]:
            findings.append(Finding(Finding.GAP, "%s.%s" % (kind, key),
                                    "attribute carried by %d node(s) but not declared for %s: declare "
                                    "it in the vocabulary, or move it" % (count, kind)))
        report = _vocab.conformance(declared, nodes, edges)
        for label, key in (("domain", "domain_patterns"), ("range", "range_patterns")):
            for (relation, actual, expected), count in report.get(key) or []:
                findings.append(Finding(Finding.GAP, relation,
                                        "%s is %s on %d edge(s) but declared %s: widen the declaration "
                                        "or fix the edges" % (label, actual, count, expected)))

    # ---- gaps: usable, but the answer will be weaker ----
    for node in nodes:
        nid = node.get("id") or "(no id)"
        if nid in live_by_id:
            continue                       # only judge what this change introduces
        required = ["as_of", "valid_from"]
        if node.get("source_type") != "human_assertion":
            required.append("source_doc")
        for field in required:
            if not node.get(field):
                findings.append(Finding(Finding.GAP, nid, "no %s recorded" % field))
        if not (node.get("sources") or []):
            findings.append(Finding(Finding.GAP, nid, "cites no source, so it cannot be checked"))
        evidence = node.get("evidence") or []
        if not evidence and node.get("source_type") != "human_assertion":
            findings.append(Finding(Finding.GAP, nid,
                                    "no evidence recorded: a page, section or quote lets a reader verify it"))
        for item in evidence:
            if not isinstance(item, dict) or not item.get("doc"):
                findings.append(Finding(Finding.GAP, nid,
                                        'an evidence entry has no "doc"; expected {"doc", "where", "quote"}'))

    order = {Finding.BLOCKING: 0, Finding.CONTRADICTION: 1, Finding.GAP: 2}
    findings.sort(key=lambda f: (order[f.severity], str(f.subject)))
    return findings


def blocking(findings):
    return [f for f in findings if f.severity == Finding.BLOCKING]


def authored_text(candidate, live=None):
    """Every piece of prose the candidate INTRODUCES, for a privacy scan.

    Only new or changed text is scanned. Re-reporting what is already in the graph would bury the one
    thing that matters: what this change is about to add.
    """
    live_by_id = index_nodes(live or {})
    parts = []
    for node in candidate.get("nodes") or []:
        nid = node.get("id")
        old = live_by_id.get(nid)
        for field in ("label", "summary"):
            value = node.get(field)
            if value and (old is None or old.get(field) != value):
                parts.append(str(value))
        attributes = node.get("attributes") or {}
        old_attributes = (old or {}).get("attributes") or {}
        for key in sorted(attributes):
            if attributes[key] != old_attributes.get(key):
                parts.append("%s: %s" % (key, attributes[key]))
    return "\n".join(parts)
