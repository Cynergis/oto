# -*- coding: utf-8 -*-
"""Knowledge that came from a person, not a document.

Most facts arrive in a document, and the document is their provenance. But some of the most valuable
corrections arrive in conversation: "that is wrong, the owner changed in March". Today that either gets
lost, or it gets written into the graph with no source at all, which is worse: an unsourced fact looks
exactly like a sourced one and nobody can check it.

So a spoken statement gets the same treatment a document gets. It is recorded, it gets an identifier,
and any fact derived from it cites that identifier. The log is append-only, because the point is to be
able to answer "why does the graph say this" months later, and an editable log cannot.

    assertions.jsonl        one JSON object per line, never rewritten
    node.source_type        "document" (the default) or "human_assertion"
    node.sources            ["assertion:a-0007"] for an asserted fact

A fact citing an assertion that is not in the log is a blocking error. Without that check the
identifier would be decoration.
"""
import json
import os
import re

LOG_NAME = "assertions.jsonl"
PREFIX = "assertion:"
ID_PATTERN = re.compile(r"^a-\d{4,}$")

DOCUMENT = "document"
HUMAN_ASSERTION = "human_assertion"
INFERENCE = "inference"
SOURCE_TYPES = (DOCUMENT, HUMAN_ASSERTION, INFERENCE)


def log_path(project):
    return os.path.join(project.data, LOG_NAME)


def read(project):
    """Every recorded assertion, in the order they were made."""
    path = log_path(project)
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"id": "(unparseable)", "line": number, "raw": line[:120]})
    return out


def known_ids(project):
    return {entry.get("id") for entry in read(project) if entry.get("id")}


def next_id(project):
    highest = 0
    for entry in read(project):
        identifier = entry.get("id") or ""
        if ID_PATTERN.match(identifier):
            highest = max(highest, int(identifier[2:]))
    return "a-%04d" % (highest + 1)


def record(project, text, by, at, about=None, supersedes=None):
    """Append one assertion. Returns the entry.

    `at` is required and never defaulted to the current time. A correction usually refers to when
    something became true in the world, which is not when it was typed, and guessing that date
    silently is how a temporal graph starts lying.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("an assertion needs text")
    if not (by or "").strip():
        raise ValueError("an assertion needs an author: an unattributed claim cannot be followed up")
    if not (at or "").strip():
        raise ValueError("an assertion needs a date")

    entry = {
        "id": next_id(project),
        "at": at,
        "by": by.strip(),
        "text": text,
        "about": about or [],
        "supersedes": supersedes or [],
    }
    path = log_path(project)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def reference(identifier):
    """The string a node puts in `sources` to cite an assertion."""
    return PREFIX + identifier


def cited_ids(node):
    """Assertion identifiers a node cites, whether through sources or source_doc."""
    out = set()
    values = list(node.get("sources") or [])
    if node.get("source_doc"):
        values.append(node["source_doc"])
    for value in values:
        if isinstance(value, str) and value.startswith(PREFIX):
            out.add(value[len(PREFIX):])
    return out


def check_nodes(nodes, known):
    """Problems with how nodes cite assertions. Returns a list of (node id, detail)."""
    problems = []
    for node in nodes:
        nid = node.get("id") or "(no id)"
        source_type = node.get("source_type")
        if source_type is not None and source_type not in SOURCE_TYPES:
            problems.append((nid, "source_type %r is not one of %s"
                             % (source_type, ", ".join(SOURCE_TYPES))))
        cited = cited_ids(node)
        for identifier in sorted(cited):
            if identifier not in known:
                problems.append((nid, "cites assertion %r, which is not in the log" % identifier))
        if source_type == HUMAN_ASSERTION and not cited:
            problems.append((nid, "is marked as a human assertion but cites no assertion identifier"))
        if cited and source_type not in (HUMAN_ASSERTION, None):
            problems.append((nid, "cites an assertion but its source_type is %r" % source_type))
    return problems


def summarize(nodes):
    """How the graph's facts are sourced. A count, not an impression."""
    counts = {DOCUMENT: 0, HUMAN_ASSERTION: 0, INFERENCE: 0, "unrecorded": 0}
    for node in nodes:
        source_type = node.get("source_type")
        if source_type in counts:
            counts[source_type] += 1
        elif source_type is None:
            # No explicit type means a document, which is the historical default.
            counts[DOCUMENT] += 1
        else:
            counts["unrecorded"] += 1
    return counts
