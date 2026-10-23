# -*- coding: utf-8 -*-
"""Possible duplicates by meaning: a new entity close to one the graph holds under another name.

The name check in `batch.py` flags a new id whose label or alias is already taken (SUSPECT). It cannot
see "Central Depot" proposed beside "Central Garage". An embedding of each entity (its label, class,
aliases and summary, described as `oto lexicon` describes them, with the bench's model) can: every
entity of the same class at or above a similarity floor is listed, for the person to decide. It is
advisory and opt-in (`--duplicates`): it never refuses a change, because a model's similarity is an
opinion about two names, not a fact about two things.

Measured on a small fleet-maintenance graph with BAAI/bge-small-en-v1.5: four plausible duplicates
scored 0.91-0.97 against their originals, four genuinely new entities of the same classes at most
0.85 ("Brake disc, front" against the front brake pad set). The 0.88 floor sits between them; it is a
starting point from eight examples, not a calibration. A runner-up margin is not required: a real
duplicate may have a close sibling (the rear pads are near the front pads), so every match above the
floor is listed rather than only the best.
"""
import sys

DEFAULT_MIN_SIMILARITY = 0.88
SHOWN = 3


def available():
    """(usable, reason): the model is the bench's, behind the same extra."""
    from ..bench import dense as _dense
    return _dense.available()


def embed(texts):
    from ..model import lexicon as _lexicon
    return _lexicon.default_embed(texts)


def _links(node):
    out = set()
    for key in ("supersedes", "superseded_by"):
        value = node.get(key)
        out.update(value if isinstance(value, list) else [value] if value else [])
    return out


def find(graph, new_ids, embed=None, min_similarity=DEFAULT_MIN_SIMILARITY, limit=SHOWN):
    """[{id, label, type, matches: [{id, label, similarity}]}] for each new id with a same-class entity at
    or above the floor. Versions of one fact (a supersession) are not duplicates of each other."""
    from ..model.lexicon import _describe, _unit
    nodes = [n for n in (graph or {}).get("nodes") or [] if n.get("id") and n.get("status", "current") == "current"]
    by_id = {n["id"]: n for n in nodes}
    new = [by_id[i] for i in new_ids if i in by_id]
    if not new:
        return []
    kinds = {n.get("type") for n in new}
    pool = [n for n in nodes if n.get("type") in kinds]
    vectors = [_unit(v) for v in (embed or sys.modules[__name__].embed)([_describe(n) for n in pool])]
    vector = {n["id"]: v for n, v in zip(pool, vectors)}
    out = []
    for node in new:
        related = _links(node) | {other["id"] for other in pool if node["id"] in _links(other)}
        matches = []
        for other in pool:
            if other["id"] == node["id"] or other.get("type") != node.get("type") or other["id"] in related:
                continue
            similarity = sum(a * b for a, b in zip(vector[node["id"]], vector[other["id"]]))
            if similarity >= min_similarity:
                matches.append({"id": other["id"], "label": other.get("label"), "similarity": round(similarity, 3)})
        if matches:
            matches.sort(key=lambda m: (-m["similarity"], m["id"]))
            out.append({"id": node["id"], "label": node.get("label"), "type": node.get("type"), "matches": matches[:limit]})
    return out


def describe(match):
    return ", ".join("%s (%.2f)" % (m["id"], m["similarity"]) for m in match["matches"])
