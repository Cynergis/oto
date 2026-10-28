# -*- coding: utf-8 -*-
"""A named person's decision about a fact, recorded: `oto decide <node> <attribute>=<value> --by <who> --at <date>`.

The vocabulary marks some attributes `decision: true`: a person's call about the fact rather than the
fact itself (a description's status, an element's readiness). Such an attribute moves without a
supersession when the node cites the assertion that moved it, and only then: `decide` records the
assertion by the person, sets the value, and applies under the gates the way `oto work` records a
state. A fact that is not a decision is refused here: it moves by a supersession, through a proposal.
Deciding what is already decided changes nothing and says so. `oto data confirm` is this, for a
table's or column's description.
"""
import json
import re

from .curate import session as _session
from .model import vocabulary as _vocab
from .project import ProjectError

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DecideError(ProjectError):
    """A refusal, in words the person can act on."""


def parse_assignment(text):
    """`readiness=ready` -> ("readiness", "ready")."""
    name, sep, value = (text or "").partition("=")
    if not sep or not name.strip() or not value.strip():
        raise DecideError("decide takes attribute=value, the decision attribute and the value it moves to: not %r" % text)
    return name.strip(), value.strip()


def move(project, node_id, attribute, value, by, at, note=None, also=None, action="decide", text=None):
    """Record the decision and apply it. Returns {"node", "label", "already", "attribute", "value", "assertion"?}.
    `also` are attribute values set in the same assertion (what the decision is about, stated)."""
    from . import assertion as _assertion, audit as _audit
    if not (by or "").strip():
        raise DecideError("--by names the person who decides: a decision has a name")
    if not at or not ISO_DATE.match(str(at)):
        raise DecideError("--at YYYY-MM-DD is required: the date of the decision is never defaulted")
    live = _session.live(project)
    node = next((n for n in live.get("nodes") or [] if n.get("id") == node_id), None)
    if node is None:
        raise DecideError("the graph holds no %s" % node_id)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    declared = _vocab.declared_attributes(config, node.get("type")) or {}
    spec = declared.get(attribute)
    if spec is None:
        raise DecideError("%s (a %s) declares no attribute %r; it has %s" % (node_id, node.get("type"), attribute, ", ".join(sorted(declared)) or "none"))
    if spec.get("decision") is not True:
        raise DecideError("%s.%s is a fact, not a decision: it moves by a supersession through a proposal, never by a signature. "
                          "The decisions of a %s are %s" % (node.get("type"), attribute, node.get("type"),
                                                           ", ".join(sorted(k for k, s in declared.items() if s.get("decision") is True)) or "none"))
    problem = _vocab.check_value(spec.get("type"), value, config.get("schemes") or {})
    if problem:
        kind, options = _vocab.parse_attribute_type(spec.get("type"), config.get("schemes") or {})
        raise DecideError("%s.%s takes %s, not %r: %s" % (node.get("type"), attribute, ", ".join(options) if kind in ("enum", "scheme") and options else spec.get("type"), value, problem))
    attributes = node.get("attributes") or {}
    current = attributes.get(attribute, spec.get("default"))
    also = {k: v for k, v in (also or {}).items() if v is not None}
    if current == value and all(attributes.get(k) == v for k, v in also.items()):
        _audit.append(project, action, by.strip(), [node_id], "unchanged", detail="%s.%s already %s" % (node_id, attribute, value))
        return {"node": node_id, "label": node.get("label") or node_id, "already": True, "attribute": attribute, "value": value}
    text = text or "%s decided %s of %s %s (%s): %s%s" % (by.strip(), attribute, node.get("type").lower(), node.get("label") or node_id, node_id, value,
                                                            " [%s]" % note.strip() if (note or "").strip() else "")

    def edit(candidate, source):
        target = next(n for n in candidate.get("nodes") or [] if n.get("id") == node_id)
        target.setdefault("attributes", {})[attribute] = value
        for k, v in also.items():
            target["attributes"][k] = v
        target["as_of"] = at
        for s in source["sources"]:
            if s not in (target.get("sources") or []):
                target.setdefault("sources", []).append(s)
        return {"node": node_id, "label": node.get("label") or node_id, "already": False, "attribute": attribute, "value": value}
    try:
        return _assertion.commit(project, text, by.strip(), at, [node_id], edit, action=action)
    except _assertion.WriteError as exc:
        raise DecideError(str(exc))
