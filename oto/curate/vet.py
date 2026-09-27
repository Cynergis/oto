# -*- coding: utf-8 -*-
"""Audit the graph against the documents that are actually in the corpus.

A graph accumulates citations to documents that later leave: a deck is de-scoped, a draft is
replaced, a file is renamed. The facts stay, still claiming a source nobody can open. The graph
still answers, and every answer it grounds in a missing document is unfalsifiable.

So this compares what the graph cites against what the corpus holds, and reports the gap. Two
lessons from the first project it ran on shape the design.

**An unmatched tag is usually an alias, not a phantom.** `kickoff` may be the kick-off document under
a different filename, and a curation tag such as `manual-update-2026-03` is a deliberate marker, not
a missing file. Treating either as a dead citation deletes real knowledge. So the audit reports and
the operator whitelists; nothing is inferred from a name.

**Removal is not the default here, and in the original tool it was.** Applying the default rule there
gutted an org chart, because structural facts often cite one document and have no vetted neighbour to
re-source to. Losing a fact is worse than carrying a stale citation: the citation can be fixed later,
the fact has to be re-derived from a document that may be gone. So `apply` strips dead citations and
re-sources what it can, and removes a node only when the operator names it.
"""
import json
import os

#: A source tag that is a deliberate marker rather than a filename. These are never dead citations.
CURATION_PREFIXES = ("manual-", "curation-", "assertion-", "human-")


#: The curated graph names edge endpoints `from` and `to`. The SQLite table names the same columns
#: `src` and `dst`. Both spellings exist in this system, which is exactly how code ends up reading
#: the wrong one and silently finding nothing: an early version of this module used the database
#: names against the JSON graph, so it reported every at-risk fact as unattested and dropped no
#: edges at all. This raises instead of guessing, so a schema change is loud.
def _endpoints(edge):
    if "from" in edge or "to" in edge:
        return edge.get("from"), edge.get("to")
    raise KeyError("edge has no `from`/`to`: %r" % (sorted(edge),))


def _sources(node):
    """Every source tag a node cites, from either field, deduplicated and ordered."""
    tags = []
    for tag in (node.get("sources") or []):
        if tag and tag not in tags:
            tags.append(tag)
    doc = node.get("source_doc")
    if doc and doc not in tags:
        tags.append(doc)
    return tags


def corpus_slugs(project):
    """The document slugs the corpus actually holds."""
    directory = project.layout.corpus
    if not os.path.isdir(directory):
        return set()
    slugs = set()
    for name in os.listdir(directory):
        stem, extension = os.path.splitext(name)
        if extension.lower() in (".md", ".markdown", ".txt"):
            slugs.add(stem)
    return slugs


def is_curation_tag(tag):
    return any(tag.startswith(prefix) for prefix in CURATION_PREFIXES)


def audit(graph, vetted, extra_vetted=()):
    """What the graph cites that the corpus does not hold.

    Returns a dict with:
      `vetted`    the accepted source tags
      `dead`      {tag: node count} for tags nothing accepts
      `pure`      nodes whose every citation is dead: the facts genuinely at risk
      `mixed`     nodes with at least one live citation: a citation to strip, not a fact to lose
      `curation`  dead-looking tags that are curation markers, listed apart so nobody deletes them
    """
    accepted = set(vetted) | set(extra_vetted)
    dead, pure, mixed, curation = {}, [], [], {}

    for node in graph.get("nodes", []):
        tags = _sources(node)
        if not tags:
            continue
        bad = [t for t in tags if t not in accepted]
        for tag in bad:
            if is_curation_tag(tag):
                curation[tag] = curation.get(tag, 0) + 1
            else:
                dead[tag] = dead.get(tag, 0) + 1
        real_bad = [t for t in bad if not is_curation_tag(t)]
        if not real_bad:
            continue
        entry = {"id": node.get("id"), "type": node.get("type"), "label": node.get("label"),
                 "cites": tags, "dead": real_bad}
        (pure if len(real_bad) == len(tags) else mixed).append(entry)

    return {"vetted": sorted(accepted), "dead": dead, "pure": pure, "mixed": mixed,
            "curation": curation}


def attesting_neighbours(graph, node_id, accepted):
    """Neighbours of `node_id` that cite a live source, and the sources they cite.

    Used to re-source a fact whose own citation died but which a surviving document discusses. The
    result is sorted so the same graph always produces the same replacement.

    This is an inference, and a fallible one. Adjacency is not attestation: that a surviving document
    mentions a neighbouring entity does not prove it mentions this one. In a system whose whole value
    is traceable provenance, a citation that looks original and is really a guess is the worst
    available outcome, so `rewrite` marks every re-sourced node. Nothing here writes a silent guess.
    """
    neighbours = set()
    for edge in graph.get("edges", []):
        source, target = _endpoints(edge)
        if source == node_id:
            neighbours.add(target)
        elif target == node_id:
            neighbours.add(source)
    found = set()
    for node in graph.get("nodes", []):
        if node.get("id") in neighbours:
            found |= {t for t in _sources(node) if t in accepted}
    return sorted(found)


def plan(graph, report, remove=(), fallback=None):
    """What `apply` would do, without doing it.

    Every `pure` node reaches exactly one of four outcomes, and the report names which:
      removed     the operator asked for it by id
      resourced   a neighbour citing a live document attests it
      fallback    no attesting neighbour, and the operator named a fallback source
      orphaned    none of the above: the fact would keep no citation at all
    An `orphaned` node is not removed. It is reported so a person decides, because losing a fact is
    worse than carrying a citation that has to be fixed.
    """
    accepted = set(report["vetted"])
    asked = set(remove)
    actions = {"removed": [], "resourced": [], "fallback": [], "orphaned": [], "stripped": []}

    for entry in report["mixed"]:
        actions["stripped"].append({"id": entry["id"], "drops": entry["dead"]})

    for entry in report["pure"]:
        node_id = entry["id"]
        if node_id in asked:
            actions["removed"].append({"id": node_id, "label": entry["label"]})
            continue
        attested = attesting_neighbours(graph, node_id, accepted)
        if attested:
            actions["resourced"].append({"id": node_id, "label": entry["label"],
                                         "to": attested})
        elif fallback:
            actions["fallback"].append({"id": node_id, "label": entry["label"], "to": [fallback]})
        else:
            actions["orphaned"].append({"id": node_id, "label": entry["label"],
                                        "cites": entry["dead"]})

    unknown = sorted(asked - set(e["id"] for e in report["pure"]))
    return actions, unknown


def orphaned_edges(graph, removed_ids):
    """Edges that would dangle once `removed_ids` are gone."""
    gone = set(removed_ids)
    return [e for e in graph.get("edges", [])
            if any(end in gone for end in _endpoints(e))]


def rewrite(graph, report, actions, as_of):
    """The graph with dead citations stripped, facts re-sourced, and named nodes removed.

    Returns a new object. The input is not modified, so a caller can show a plan and then decide.
    """
    accepted = set(report["vetted"])
    removed = set(e["id"] for e in actions["removed"])
    replacement = {}
    for key in ("resourced", "fallback"):
        for entry in actions[key]:
            replacement[entry["id"]] = entry["to"]
    # An orphaned fact is reported as "left alone for you to decide", so it must be left alone. An
    # earlier version stripped its citations along with everyone else's, which left the node with
    # `sources: []` and `source_doc: null` and made the report a lie. A dead citation you can see is
    # better than none: it names the document to go and find. Untouched means untouched.
    untouched = set(e["id"] for e in actions["orphaned"])

    nodes = []
    for node in graph.get("nodes", []):
        node_id = node.get("id")
        if node_id in removed:
            continue
        if node_id in untouched:
            nodes.append(dict(node))
            continue
        fresh = dict(node)
        if node_id in replacement:
            was = _sources(node)
            fresh["sources"] = list(replacement[node_id])
            fresh["source_doc"] = replacement[node_id][0]
            fresh["as_of"] = as_of
            # The mark is the point. A reader, or a later audit, must be able to tell an inferred
            # citation from one a document actually supports.
            fresh["provenance"] = "inferred"
            fresh["provenance_note"] = (
                "Citation inferred by `oto vet` on %s from a neighbouring entity, because the "
                "document(s) this fact cited (%s) are no longer in the corpus. Adjacency is not "
                "attestation: confirm that %s states this before treating it as sourced."
                % (as_of, ", ".join(was) or "none", ", ".join(replacement[node_id])))
        else:
            kept = [t for t in _sources(node)
                    if t in accepted or is_curation_tag(t)]
            if kept != _sources(node):
                fresh["sources"] = kept
                fresh["as_of"] = as_of
                if fresh.get("source_doc") and fresh["source_doc"] not in kept:
                    # `kept` is non-empty for every node that reaches here: an orphan is untouched
                    # above. The guard stays so a future change cannot write a null into the field.
                    if not kept:
                        raise AssertionError("would write a null source_doc for %s" % node_id)
                    fresh["source_doc"] = kept[0]
        nodes.append(fresh)

    edges = [e for e in graph.get("edges", [])
             if not any(end in removed for end in _endpoints(e))]

    out = dict(graph)
    out["nodes"] = nodes
    out["edges"] = edges
    return out
