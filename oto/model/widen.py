# -*- coding: utf-8 -*-
"""Propose honest domain and range declarations from how relations are actually used.

A declaration the data violates is worse than a loose one, because `rdfs:domain` and `rdfs:range` are
inference rules in the RDF export: a reasoner infers the wrong type for every violating edge. But
widening every declaration to match whatever the data does removes the constraint entirely, and then
the export documents nothing.

So this triages instead of blessing. For each violating pattern it counts how often it occurs:

  * **frequent** — the relation is genuinely used this way and the declaration never caught up.
    Widening is the honest fix.
  * **rare** — one or two edges. That is more likely a mistake in the data than a gap in the model,
    and widening it would hide the mistake permanently.

Only the frequent patterns go into the proposal. The rare ones are listed for a person to look at.
Nothing is applied: the output is a proposed config beside the real one, for review.
"""
import json
import os

PROPOSAL_SUFFIX = ".proposed.json"

#: A pattern occurring at least this often is treated as real usage rather than an error. Chosen
#: because a genuine modelling gap shows up repeatedly, while a typo shows up once.
FREQUENT = 5


def _union(spec):
    return [x.strip() for x in (spec or "").split("|") if x.strip()]


def analyse(config, nodes, edges, frequent=FREQUENT):
    """Per relation, what the data does against what is declared."""
    properties = config.get("properties") or {}
    types = {n.get("id"): n.get("type") for n in nodes}

    observed = {}
    for edge in edges:
        relation = edge.get("rel")
        if relation not in properties:
            continue
        key = (types.get(edge.get("from")), types.get(edge.get("to")))
        observed.setdefault(relation, {})
        observed[relation][key] = observed[relation].get(key, 0) + 1

    findings = []
    for relation in sorted(observed):
        spec = properties[relation]
        declared_from = _union(spec.get("domain"))
        declared_to = _union(spec.get("range"))

        # Count per ENDPOINT TYPE, not per pair, before thresholding. Thresholding pairs put the
        # same type in both buckets: a type used 11 times with one partner and 4 with another looked
        # both frequent and rare, which is nonsense and unreadable.
        from_counts, to_counts = {}, {}
        for (from_type, to_type), count in observed[relation].items():
            if declared_from and from_type not in declared_from:
                from_counts[from_type] = from_counts.get(from_type, 0) + count
            if declared_to and to_type not in declared_to:
                to_counts[to_type] = to_counts.get(to_type, 0) + count

        widen_from = {k: v for k, v in from_counts.items() if v >= frequent}
        rare_from = {k: v for k, v in from_counts.items() if v < frequent}
        widen_to = {k: v for k, v in to_counts.items() if v >= frequent}
        rare_to = {k: v for k, v in to_counts.items() if v < frequent}

        if not (widen_from or widen_to or rare_from or rare_to):
            continue
        findings.append({
            "relation": relation,
            "declared_domain": spec.get("domain") or "",
            "declared_range": spec.get("range") or "",
            "widen_domain": dict(sorted(widen_from.items(), key=lambda kv: -kv[1])),
            "widen_range": dict(sorted(widen_to.items(), key=lambda kv: -kv[1])),
            "inspect_domain": dict(sorted(rare_from.items(), key=lambda kv: -kv[1])),
            "inspect_range": dict(sorted(rare_to.items(), key=lambda kv: -kv[1])),
        })
    return findings


def propose(config, findings):
    """A copy of the config with the frequent patterns folded in. Rare ones are left alone."""
    proposed = json.loads(json.dumps(config))
    properties = proposed.get("properties") or {}
    changed = []
    for finding in findings:
        relation = finding["relation"]
        spec = dict(properties.get(relation) or {})
        if finding["widen_domain"]:
            spec["domain"] = "|".join(sorted(set(_union(spec.get("domain"))) | set(finding["widen_domain"])))
        if finding["widen_range"]:
            spec["range"] = "|".join(sorted(set(_union(spec.get("range"))) | set(finding["widen_range"])))
        if finding["widen_domain"] or finding["widen_range"]:
            properties[relation] = spec
            changed.append(relation)
    proposed["properties"] = properties

    # A widening is a vocabulary change, so it needs a version. Silently reusing the old one would
    # make the lock meaningless.
    proposed["ontology_version"] = int(config.get("ontology_version") or 0) + 1
    return proposed, changed


def proposal_path(project):
    base = project.ontology_config_path
    return base[:-len(".json")] + PROPOSAL_SUFFIX if base.endswith(".json") else base + PROPOSAL_SUFFIX


def write_proposal(project, proposed):
    path = proposal_path(project)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposed, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
