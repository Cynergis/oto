# -*- coding: utf-8 -*-
"""Composing an ontology from the ontologies it extends.

`extends` in the manifest names the parts an ontology is built on, in order. The composition is
resolved depth-first, bases before the ontologies that extend them, each name once. Then the
parts are applied in that order, so the extending ontology wins over anything it extends; the
report says what it overrode, and a few overrides are refused rather than reported:

    class definition         extender wins; reported as redescribed
    relation signature       widening the domain or range is accepted and reported;
                             narrowing, or changing to something else, is refused
    attribute type           extender wins; a change is reported
    schemes                  merged by name; the extender's replaces one it redeclares, reported
    rules                    merged by id; the same id with a different body is refused
    actions                  merged by id; the extender's wins (an action is a binding, not a claim)
    rationale                the extender's entries apply only to names it declares itself
    sample graph             merged by node id, extender wins; edges united
    lexicon, interview, gold concatenated, bases first; the guide is the leaf's, the bases'
    appended under "Inherited from"
    namespaces               a term belongs to the first part that declares it; each part that
                             states a `namespace` in its manifest is recorded with its terms
    temporal vocabulary      taken from the first part that declares it and never merged,
                             because supersession depends on it being one thing

Everything here reads an ontology's own files (`ontologies.load_raw`) and never the composed
form, so composing cannot recurse into itself.
"""
import json
import os

from . import namespaces as _namespaces
from . import vocabulary as _vocabulary


class OntologyError(ValueError):
    """An ontology cannot be composed or used; the message names the ontology and the reason."""


def _declared(spec):
    return [x.strip() for x in (spec or "").split("|") if x.strip()]


def resolve(name, _load_manifest, _seen=None, _stack=None):
    """The ordered list of ontology names to apply: bases first, `name` last, each once.

    `_load_manifest(name)` returns the manifest dict for an ontology name, or raises KeyError.
    """
    seen = [] if _seen is None else _seen
    stack = [] if _stack is None else _stack
    if name in stack:
        raise OntologyError("ontology %r extends itself through %s" % (name, " -> ".join(stack + [name])))
    if name in seen:
        return seen
    try:
        manifest = _load_manifest(name)
    except KeyError:
        via = (" (extended by %r)" % stack[-1]) if stack else ""
        raise OntologyError("unknown ontology %r%s" % (name, via))
    for base in manifest.get("extends") or []:
        resolve(base, _load_manifest, seen, stack + [name])
    seen.append(name)
    return seen


def _guide(guides):
    """The leaf's guide first; what the bases say follows, marked."""
    leaf_part, leaf_text = guides[-1]
    text = leaf_text
    for part, inherited in guides[:-1]:
        text += "\n\n---\n\n## Inherited from `%s`\n\n%s" % (part, inherited)
    return text


def compose(name, parts, loader):
    """Apply the parts in order. `parts` is the resolved name list; `loader(name)` returns a dict
    with keys config, sample, readme, rationale, rules, lexicon, interview, gold, manifest.

    Returns a dict with the same keys as a part plus `report`, or raises OntologyError.
    """
    classes, properties, attributes, temporal, schemes = {}, {}, {}, None, {}
    temporal_from = None
    rationale = {"classes": {}, "properties": {}}
    rules, rule_owner = {}, {}
    sample_nodes, sample_edges = {}, []
    lexicon, interview, guides, gold = [], [], [], []
    actions, action_owner = {}, {}
    namespaces = {}
    readmes = []
    report = {"parts": list(parts), "redescribed": [], "widened": [], "retyped": [], "inverse_changed": [], "schemes_replaced": [],
              "rationale_ignored": [], "rules_shared": [], "sample_overridden": [], "actions_overridden": []}
    leaf = None

    for part in parts:
        raw = loader(part)
        config = raw["config"]
        malformed = _vocabulary.shape_problems(config)
        if malformed:
            raise OntologyError("ontology %r is not in the form the engine reads: %s" % (part, "; ".join(malformed[:5])))
        leaf = raw
        own_classes = config.get("classes") or {}
        own_props = config.get("properties") or {}

        for kind, spec in own_classes.items():
            if kind in classes and (classes[kind].get("definition") or "").strip() != (spec.get("definition") or "").strip():
                report["redescribed"].append((kind, part))
            classes[kind] = dict(spec)

        for relation, spec in own_props.items():
            spec = dict(spec)
            if relation in properties:
                old = properties[relation]
                for label in ("domain", "range"):
                    before, after = set(_declared(old.get(label))), set(_declared(spec.get(label)))
                    if after == before:
                        continue
                    if after > before:
                        report["widened"].append((relation, label, part, sorted(after - before)))
                    elif after < before:
                        raise OntologyError("ontology %r narrows the %s of %r from %s to %s; an ontology may widen "
                                            "what it extends, never narrow it"
                                            % (part, label, relation, "|".join(sorted(before)), "|".join(sorted(after))))
                    else:
                        raise OntologyError("ontology %r changes the %s of %r from %s to %s; declare a new relation "
                                            "instead" % (part, label, relation, "|".join(sorted(before)), "|".join(sorted(after))))
                if (old.get("inverse") or None) != (spec.get("inverse") or None):
                    report["inverse_changed"].append((relation, part, old.get("inverse"), spec.get("inverse")))
            properties[relation] = spec

        if config.get("temporal") and temporal is None:
            temporal, temporal_from = dict(config["temporal"]), part

        for kind, declared in (config.get("attributes") or {}).items():
            for attr, spec in (declared or {}).items():
                previous = (attributes.get(kind) or {}).get(attr)
                if previous is not None and previous.get("type") != spec.get("type"):
                    report["retyped"].append((kind, attr, part, previous.get("type"), spec.get("type")))
                attributes.setdefault(kind, {})[attr] = dict(spec)

        for scheme_name, scheme in (config.get("schemes") or {}).items():
            if scheme_name in schemes and schemes[scheme_name] != scheme:
                report["schemes_replaced"].append((scheme_name, part))
            schemes[scheme_name] = json.loads(json.dumps(scheme))

        # What the part's own vocabulary already records (an exported ontology carries where its
        # terms came from) is kept; the rest of what it declares is its own.
        _namespaces.inherit(namespaces, config.get(_namespaces.SECTION))
        if raw["manifest"].get("namespace"):
            _namespaces.claim(namespaces, part, raw["manifest"]["namespace"], _namespaces.own_terms(config),
                              temporal=temporal_from == part)

        record = raw["rationale"] or {}
        for section, owned in (("classes", own_classes), ("properties", own_props)):
            for key, entry in (record.get(section) or {}).items():
                if key in owned:
                    rationale[section][key] = dict(entry)
                elif key in (classes if section == "classes" else properties):
                    report["rationale_ignored"].append((section, key, part))
                else:
                    rationale[section][key] = dict(entry)      # a rationale for nothing; the self-check reports it

        for rule in raw["rules"] or []:
            rid = rule.get("id")
            if rid in rules:
                if json.dumps(rules[rid], sort_keys=True) != json.dumps(rule, sort_keys=True):
                    raise OntologyError("ontology %r declares rule %r differently from %r; rules merge by id and "
                                        "an id means one rule" % (part, rid, rule_owner[rid]))
                report["rules_shared"].append((rid, rule_owner[rid], part))
            else:
                rules[rid] = dict(rule)
                rule_owner[rid] = part

        for node in (raw["sample"] or {}).get("nodes") or []:
            nid = node.get("id")
            if nid in sample_nodes:
                report["sample_overridden"].append((nid, part))
            sample_nodes[nid] = dict(node)
        for edge in (raw["sample"] or {}).get("edges") or []:
            key = (edge.get("from"), edge.get("rel"), edge.get("to"))
            if key not in {(e.get("from"), e.get("rel"), e.get("to")) for e in sample_edges}:
                sample_edges.append(dict(edge))

        for action in raw.get("actions") or []:
            aid = action.get("id")
            if aid in actions:
                report["actions_overridden"].append((aid, action_owner[aid], part))
            actions[aid] = dict(action)
            action_owner[aid] = part
        lexicon += list((raw["lexicon"] or {}).get("entries") or [])
        if raw["interview"]:
            interview.append((part, raw["interview"].strip()))
        if raw.get("guide"):
            guides.append((part, raw["guide"].strip()))
        gold += list(raw["gold"] or [])
        if raw["readme"]:
            readmes.append((part, raw["readme"]))

    if leaf is None:
        raise OntologyError("nothing to compose for %r" % name)
    config = {}
    for key, value in leaf["config"].items():                 # the leaf's own scalars: name, versions, notes
        if key not in ("classes", "properties", "temporal", "attributes", "schemes", _namespaces.SECTION):
            config[key] = value
    config["classes"] = classes
    config["properties"] = properties
    if temporal is not None:
        config["temporal"] = temporal
    if attributes:
        config["attributes"] = attributes
    if schemes:
        config["schemes"] = schemes
    if _namespaces.settled(namespaces):
        config[_namespaces.SECTION] = _namespaces.settled(namespaces)
    report["temporal_from"] = temporal_from

    if len(parts) == 1:
        readme = leaf["readme"]
    else:
        readme = leaf["readme"].rstrip() + "\n"
        for part, text in readmes[:-1]:
            readme += "\n---\n\n## Inherited from `%s`\n\n%s\n" % (part, text.strip())

    return {"config": config, "sample": {"nodes": list(sample_nodes.values()), "edges": sample_edges},
            "readme": readme, "rationale": rationale, "rules": list(rules.values()),
            "lexicon": {"entries": lexicon} if lexicon else None,
            "interview": "\n\n".join(text for _part, text in interview) if interview else None,
            "guide": _guide(guides) if guides else None,
            "actions": list(actions.values()),
            "gold": gold, "manifest": leaf["manifest"], "report": report}


def report_lines(report):
    """The composition report as text, one line per thing a person should know."""
    lines = []
    if len(report["parts"]) > 1:
        lines.append("composed from %s" % " -> ".join(report["parts"]))
        if report.get("temporal_from"):
            lines.append("temporal vocabulary from %s" % report["temporal_from"])
    for kind, part in report["redescribed"]:
        lines.append("class %s redescribed by %s" % (kind, part))
    for relation, label, part, added in report["widened"]:
        lines.append("relation %s: %s widened by %s with %s" % (relation, label, part, "|".join(added)))
    for kind, attr, part, before, after in report["retyped"]:
        lines.append("attribute %s.%s retyped by %s: %s -> %s" % (kind, attr, part, before, after))
    for scheme_name, part in report.get("schemes_replaced") or []:
        lines.append("scheme %s replaced by %s" % (scheme_name, part))
    for relation, part, before, after in report["inverse_changed"]:
        lines.append("relation %s: inverse changed by %s: %r -> %r" % (relation, part, before, after))
    for section, key, part in report["rationale_ignored"]:
        lines.append("rationale for inherited %s %s in %s ignored (only the declaring ontology's counts)"
                     % (section[:-1] if section.endswith("s") else section, key, part))
    for aid, owner, part in report.get("actions_overridden") or []:
        lines.append("action %s from %s replaced by %s" % (aid, owner, part))
    for rid, owner, part in report["rules_shared"]:
        lines.append("rule %s declared identically by %s and %s" % (rid, owner, part))
    for nid, part in report["sample_overridden"]:
        lines.append("sample node %s overridden by %s" % (nid, part))
    return lines
