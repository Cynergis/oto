# -*- coding: utf-8 -*-
"""Forward chaining to a fixpoint, with every conclusion carrying what it rests on.

A derived edge or attribute records `derived_by` (the rule), `premises` (the node ids bound and
the edge keys used, asserted or derived), and `depth` (one more than its deepest derived premise).
An asserted fact always wins: a derived edge that duplicates one is dropped, a derived attribute
never overwrites an asserted value. Policy rules produce findings and change nothing.
"""
from .match import Graph, matches, BELIEVED_OR_INTENDED

MAX_ROUNDS = 50


class DoesNotConverge(Exception):
    pass


def _edge_key(edge):
    return "%s -%s-> %s" % (edge["from"], edge["rel"], edge["to"])


def run(rules, nodes, edges, covers=None, declared=None):
    """Return {"edges": [...], "attributes": [...], "findings": [...], "per_rule": {...}, "notes": [...]}.
    `covers` is what each class covers (model/vocabulary.covers), so a pattern on a class matches its kinds;
    `declared` is what each class declares (questions.declared_names), so a declared name is the term."""
    graph = Graph(nodes, edges, covers=covers, declared=declared)
    asserted_keys = set(graph.keys)
    derived_edges, derived_attributes, notes = [], [], []
    depth_of = {}
    per_rule = {r["id"]: {"derived": 0, "flagged": 0} for r in rules}
    derive_rules = [r for r in rules if r.get("kind") == "derive"]
    policy_rules = [r for r in rules if r.get("kind") == "policy"]

    for round_number in range(1, MAX_ROUNDS + 2):
        if round_number > MAX_ROUNDS:
            raise DoesNotConverge("rules did not reach a fixpoint in %d rounds" % MAX_ROUNDS)
        new_facts = 0
        for rule in derive_rules:
            for bindings, used in matches(graph, rule["when"]):
                premises = sorted(set(bindings.values())) + [_edge_key(e) for e in used]
                depth = 1 + max([depth_of.get(_edge_key(e), 0) for e in used] or [0])
                action = rule["then"]
                if "edge" in action:
                    src, rel, dst = action["edge"]
                    edge = {"from": bindings[src], "rel": rel, "to": bindings[dst], "status": "derived",
                            "derived_by": rule["id"], "premises": premises, "depth": depth}
                    key = (edge["from"], rel, edge["to"])
                    if key in asserted_keys:
                        continue                              # the document already says it
                    if graph.add_edge(edge):
                        derived_edges.append(edge)
                        depth_of[_edge_key(edge)] = depth
                        per_rule[rule["id"]]["derived"] += 1
                        new_facts += 1
                else:
                    var, name, value = action["attribute"]
                    nid = bindings[var]
                    if (graph.nodes[nid].get("attributes") or {}).get(name) is not None:
                        continue                              # asserted wins
                    if graph.derived_attributes.get(nid, {}).get(name) is not None:
                        continue
                    graph.derived_attributes.setdefault(nid, {})[name] = value
                    derived_attributes.append({"node": nid, "name": name, "value": value,
                                               "derived_by": rule["id"], "premises": premises, "depth": depth})
                    per_rule[rule["id"]]["derived"] += 1
                    new_facts += 1
        if not new_facts:
            break

    findings = []
    # A policy also sees intended facts (a plan gone stale is a finding); it never feeds back.
    seen = Graph(nodes, [dict(e) for e in edges] + [dict(e) for e in derived_edges], graph.derived_attributes, covers=covers,
                 statuses=BELIEVED_OR_INTENDED, declared=declared)
    for rule in policy_rules:
        for bindings, used in matches(seen, rule["when"]):
            subject = bindings[next(iter(bindings))] if bindings else None
            findings.append({"rule": rule["id"], "severity": rule.get("severity", "warn"),
                             "node": subject, "message": rule["then"]["flag"],
                             "bindings": dict(sorted(bindings.items()))})
            per_rule[rule["id"]]["flagged"] += 1
    findings.sort(key=lambda f: (f["severity"] != "blocking", f["rule"], str(f["node"])))

    return {"edges": derived_edges, "attributes": derived_attributes, "findings": findings,
            "per_rule": per_rule, "notes": notes, "rounds": round_number}


def explain(result, nodes_by_id, target):
    """The chain under one derived fact: rule, then each premise down to asserted evidence.
    `target` is a derived edge or attribute record from `result`."""
    lines = ["%s  (derived by rule %s, depth %d)" % (
        "%s -%s-> %s" % (target["from"], target["rel"], target["to"]) if "rel" in target
        else "%s.%s = %r" % (target["node"], target["name"], target["value"]),
        target["derived_by"], target["depth"])]
    derived_by_key = {_edge_key(e): e for e in result["edges"]}
    for premise in target["premises"]:
        if premise in derived_by_key:
            lines += ["  " + line for line in explain(result, nodes_by_id, derived_by_key[premise])]
        elif " -" in premise and "-> " in premise:
            lines.append("  %s  (asserted)" % premise)
        else:
            node = nodes_by_id.get(premise) or {}
            evidence = (node.get("evidence") or [{}])[0]
            where = ("%s %s" % (evidence.get("doc", ""), evidence.get("where", ""))).strip()
            lines.append("  %s  [%s] %s%s" % (premise, node.get("type", "?"), node.get("label", ""),
                                               ("  source: " + where) if where else
                                               ("  source: " + node["source_doc"] if node.get("source_doc") else "")))
    return lines
