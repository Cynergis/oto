# -*- coding: utf-8 -*-
"""Architecture decision records: markdown in the repository, compiled into Decision nodes (G1-G3).

An ADR stays what engineers already write, a markdown file under `docs/adr/`, and goes through the
same pull request as everything else. Its frontmatter is what the graph reads; its body is what a
person reads, and the sentence under `## Decision` is the quote the node cites. `oto curate propose
--from docs/adr/0017-....md` turns one into a proposal deterministically, no model involved; `oto
curate add`, `check` and `apply` take it from there.

    ---
    id: ADR-0017                       required; the node is decision.adr-0017
    title: Returns net of fees         the label (else the first heading)
    status: accepted                   proposed | accepted (a superseded one is superseded the engine's way)
    decided_on: 2026-10-20             YYYY-MM-DD; the node's date, valid_from and as_of
    decided_by: Payments team          a Role or Team of the graph, by id, label or alias
    governs: [a.b, c.d]                what the decision shaped: ids of the graph (G3)
    resolves: [openquestion.x]         the questions it settles
    about: [...]                       what it concerns
    supersedes: ADR-0009               the decision it reverses: that node is retired on decided_on
    ---

The frontmatter is a small subset of YAML read by hand, because the engine has no YAML library and
needs none: `key: value`, `key: [a, b]`, and a `- item` list under a key. Anything else is refused,
named. A target the graph does not hold is reported as unresolved and the edge is not proposed; a
supersession of a decision the graph lacks is not written, so the gate never sees a dangling one.
"""
import re

ID = re.compile(r"^ADR-\d{1,6}$", re.IGNORECASE)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("proposed", "accepted")
LINKS = {"governs": "governs", "resolves": "resolves", "about": "about"}
KEYS = ("id", "title", "status", "decided_on", "decided_by", "governs", "resolves", "about", "supersedes")
FENCE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _list(text):
    inner = text.strip()[1:-1]
    return [_scalar(x) for x in inner.split(",") if x.strip()]


def frontmatter(block):
    """{key: value} from the fenced lines; a value is a string, a list, or {"_nested": True} for
    what this subset does not read (reported by `problems`)."""
    out, key = {}, None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            item = raw.strip()
            if item.startswith("- ") and key is not None and isinstance(out.get(key), list):
                out[key].append(_scalar(item[2:]))
            else:
                out[key] = {"_nested": True} if key is not None else out.get(key)
            continue
        name, sep, value = raw.partition(":")
        if not sep:
            continue
        key = name.strip()
        value = value.strip()
        if value == "":
            out[key] = []                              # a dashed list follows, or nothing
        elif value.startswith("[") and value.endswith("]"):
            out[key] = _list(value)
        else:
            out[key] = _scalar(value)
    return out


def sections(body):
    """{heading: the paragraph text under it}, headings at any level, text joined by spaces."""
    out, current, lines = {}, None, []

    def close():
        if current is not None:
            text = " ".join(l.strip() for l in lines if l.strip())
            out[current] = text
    for line in body.splitlines():
        m = HEADING.match(line)
        if m:
            close()
            current, lines = m.group(2), []
        elif current is not None:
            lines.append(line)
    close()
    return out


def parse(text):
    """{"front", "body", "sections", "title"} of an ADR's text; an absent fence gives an empty front."""
    m = FENCE.match(text)
    front = frontmatter(m.group(1)) if m else {}
    body = (text[m.end():] if m else text).lstrip("\n")
    found = sections(body)
    heading = HEADING.search(body)
    title = front.get("title") if isinstance(front.get("title"), str) else None
    return {"front": front, "body": body, "sections": found, "title": title or (heading.group(2) if heading else None)}


def is_adr(text):
    """A file with a fence, an `id` like ADR-0017 and a Decision section is one."""
    record = parse(text)
    return bool(isinstance(record["front"].get("id"), str) and ID.match(record["front"]["id"]) and record["sections"].get("Decision"))


def problems(record):
    """What is wrong with an ADR, in words. [] when it compiles."""
    front, out = record["front"], []
    if not front:
        return ["no frontmatter: an ADR starts with --- id: ADR-0001 ... ---"]
    for key, value in front.items():
        if key not in KEYS:
            out.append("frontmatter key %r is not one the graph reads (%s)" % (key, ", ".join(KEYS)))
        elif isinstance(value, dict):
            out.append("frontmatter key %r holds a nested map; the graph reads a value, [a, b] or a dashed list" % key)
    identifier = front.get("id")
    if not (isinstance(identifier, str) and ID.match(identifier)):
        out.append("`id` is required, as ADR-<number>: it names the node (decision.adr-<number>)")
    if front.get("status") not in STATUSES:
        out.append("`status` is one of %s, not %r; a reversed decision is superseded by the one that reverses it" % (" | ".join(STATUSES), front.get("status")))
    if not (isinstance(front.get("decided_on"), str) and ISO_DATE.match(front["decided_on"])):
        out.append("`decided_on` is the date, YYYY-MM-DD: the node's date and the day the superseded decision ends")
    for key in LINKS:
        if key in front and not isinstance(front[key], list):
            out.append("`%s` is a list of ids: [a.b, c.d]" % key)
    if "supersedes" in front and not (isinstance(front["supersedes"], str) and ID.match(front["supersedes"])):
        out.append("`supersedes` names one ADR id, ADR-<number>")
    if not record["sections"].get("Decision"):
        out.append("a `## Decision` section with the decision in one paragraph is required: its first sentence is the quote the node cites")
    if not record["title"]:
        out.append("a title: `title:` in the frontmatter, or a heading")
    return out


def node_id(adr_id):
    return "decision.%s" % adr_id.lower()


def first_sentence(text):
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip())
    return m.group(1) if m else text.strip()


def propose(record, doc, graph_ids, labels=None):
    """A proposal from a parsed ADR: the Decision node cited to `doc` (the ADR's slug in the
    corpus) with the first sentence of its Decision section as the quote, its edges to what the
    graph holds, a Document node for the ADR itself that the decision is `documented_in`, and the
    supersession of the decision it reverses when the graph holds it. `labels` maps a label or alias
    to an id, for `decided_by`. Returns {"source_doc", "as_of",
    "nodes", "edges", "unresolved": [what named nothing in the graph]}."""
    front = record["front"]
    labels = labels or {}
    nid = node_id(front["id"])
    decision = record["sections"]["Decision"]
    quote = first_sentence(decision)
    node = {"id": nid, "type": "Decision", "label": record["title"], "summary": quote,
            "attributes": {"status": front["status"], "decided_on": front["decided_on"], "rationale": decision},
            "valid_from": front["decided_on"],
            "evidence": [{"doc": doc, "where": "Decision", "quote": quote},
                         {"doc": doc, "where": "frontmatter", "quote": "decided_on: %s" % front["decided_on"]}]}
    # The ADR is the document that records the decision: a Document node of its own, so the decision
    # cites it (`documented_in`) and the corpus question knows it is there.
    paper = {"id": "document.%s" % doc, "type": "Document", "label": record["title"], "summary": "ADR %s, the record of this decision." % front["id"],
             "attributes": {"kind": "adr"}, "valid_from": front["decided_on"],
             "evidence": [{"doc": doc, "where": "title", "quote": record["title"]}]}
    nodes, edges, unresolved = [node, paper], [{"from": nid, "rel": "documented_in", "to": paper["id"]}], []

    def target(term):
        if term in graph_ids:
            return term
        if term in labels:
            return labels[term]
        if term.lower() in labels:
            return labels[term.lower()]
        unresolved.append(term)
        return None
    for key, rel in LINKS.items():
        for term in front.get(key) or []:
            found = target(term)
            if found:
                edges.append({"from": nid, "rel": rel, "to": found})
    if front.get("decided_by"):
        found = target(front["decided_by"])
        if found:
            edges.append({"from": nid, "rel": "decided_by", "to": found})
    if front.get("supersedes"):
        old = node_id(front["supersedes"])
        if old in graph_ids:
            note = "%s supersedes %s on %s: %s" % (front["id"], front["supersedes"], front["decided_on"], quote)
            node["supersedes"] = old
            node["change_note"] = note
            nodes.append({"id": old, "status": "superseded", "valid_to": front["decided_on"], "superseded_by": nid, "change_note": note})
        else:
            unresolved.append(old)
    return {"source_doc": doc, "as_of": front["decided_on"], "nodes": nodes, "edges": edges, "unresolved": unresolved}
