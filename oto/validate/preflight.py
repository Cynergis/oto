# -*- coding: utf-8 -*-
"""Validate a project BEFORE the build writes anything.

Without this, a build that fails halfway leaves a partly-written `build/` directory that looks
complete. The stages run in order and each writes as it goes, so the first failure is already too
late.

Pre-flight reads only the authored sources (the two config files and the curated graph), never a
generated file, and reports every problem it finds at once rather than stopping at the first.
"""
import json
import os

from ..project import ProjectError


def _load(path, label):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ProjectError("%s not found at %s" % (label, path))
    except json.JSONDecodeError as exc:
        raise ProjectError("%s is not valid JSON: %s" % (label, exc))


def preflight(project):
    """Raise ProjectError listing every problem, or return a summary dict."""
    problems = []

    identity = project.identity()                      # raises if the identity config is unusable

    ontology = _load(project.ontology_config_path, "ontology.config.json")
    classes = ontology.get("classes") or {}
    properties = ontology.get("properties") or {}
    if not classes:
        problems.append("ontology.config.json declares no classes")
    if not properties:
        problems.append("ontology.config.json declares no properties")

    graph = _load(project.graph_path, os.path.basename(project.graph_path))
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if nodes is None or edges is None:
        problems.append("%s must have both 'nodes' and 'edges' keys"
                        % os.path.basename(project.graph_path))
        nodes, edges = nodes or [], edges or []
    if not nodes:
        problems.append("%s declares no nodes" % os.path.basename(project.graph_path))

    # The integrity gate, run against the SOURCE of truth rather than a generated file.
    node_ids = set()
    duplicate_ids = set()
    undeclared_types = set()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            problems.append("a node has no id: %s" % str(n)[:80])
            continue
        if nid in node_ids:
            duplicate_ids.add(nid)
        node_ids.add(nid)
        if n.get("type") not in classes:
            undeclared_types.add(n.get("type"))

    undeclared_rels = set()
    dangling = []
    for e in edges:
        if e.get("rel") not in properties:
            undeclared_rels.add(e.get("rel"))
        for end in ("from", "to"):
            if e.get(end) not in node_ids:
                dangling.append("%s -%s-> %s" % (e.get("from"), e.get("rel"), e.get("to")))
                break

    if duplicate_ids:
        problems.append("duplicate node ids: %s" % ", ".join(sorted(duplicate_ids)[:8]))
    if undeclared_types:
        problems.append("node types not declared in ontology.config.json: %s"
                        % ", ".join(sorted(str(t) for t in undeclared_types)[:8]))
    if undeclared_rels:
        problems.append("relations not declared in ontology.config.json: %s"
                        % ", ".join(sorted(str(r) for r in undeclared_rels)[:8]))
    if dangling:
        problems.append("%d edge(s) point at an unknown node, first: %s" % (len(dangling), dangling[0]))

    problems += _lexicon_problems(os.path.join(project.data, "lexicon.json"), node_ids)

    # Rules are vocabulary: a malformed set fails here, before the rules stage would.
    from ..reason import rules as _rules
    try:
        declared_rules = _rules.load(project)
    except ValueError as exc:
        declared_rules, problems = [], problems + ["rules.json is not valid JSON: %s" % exc]
    problems += _rules.problems(declared_rules, ontology)

    # Declared attributes: a bad declaration or a value that contradicts one is blocking. An
    # attribute nobody declared on a class that declares others is advisory, unless the project
    # has said `strict_attributes`, because a passing build must not start failing because a
    # declaration was added yesterday.
    from ..model import vocabulary as _vocab
    problems += _vocab.declaration_problems(classes, ontology.get("attributes") or {})
    if not problems:
        report = _vocab.attribute_conformance(_vocab.Vocabulary.from_config(ontology), nodes)
        for nid, key, why, value in report["mistyped"][:8]:
            problems.append("%s.%s = %r: %s" % (nid, key, value, why))
        if ontology.get("strict_attributes"):
            for (kind, key), count in report["undeclared"][:8]:
                problems.append("attribute %s.%s is not declared (strict_attributes; %d node(s))" % (kind, key, count))

    if problems:
        raise ProjectError("the project is not ready to build:\n  - " + "\n  - ".join(problems))

    return {"name": identity["name"], "nodes": len(nodes), "edges": len(edges),
            "classes": len(classes), "properties": len(properties),
            "warnings": _advisories(project, ontology, nodes, edges)}


LEXICON_SHAPE = ('lexicon.json must be {"entries": [{"term": "...", "aka": ["..."], '
                 '"targets": ["<node id>"], "status": "current", "note": "..."}]}')


def _lexicon_problems(path, node_ids):
    """The lexicon is authored, optional, and read by the sqlite stage. Check it here so a wrong
    shape is one clear line before the build rather than a KeyError in the middle of it."""
    if not os.path.exists(path):
        return []
    try:
        payload = _load(path, "lexicon.json")
    except ProjectError as exc:
        return [str(exc)]
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        return [LEXICON_SHAPE]
    problems = []
    for number, entry in enumerate(payload["entries"], 1):
        if not isinstance(entry, dict) or not (entry.get("term") or "").strip():
            problems.append("lexicon entry %d has no `term`. %s" % (number, LEXICON_SHAPE))
            continue
        for target in entry.get("targets") or []:
            if target and target not in node_ids:
                problems.append("lexicon entry %r targets unknown node %r" % (entry["term"], target))
    return problems


def _advisories(project, ontology_config, nodes, edges):
    """Things worth saying that must not fail a build.

    Vocabulary drift and domain conformance are reported, not enforced. Turning a passing build into
    a failing one because a new report was added teaches people to bypass the gate.
    """
    from ..model import vocabulary as vocab

    out = []
    current = vocab.Vocabulary.from_config(ontology_config)
    locked = vocab.read_lock(project)
    if locked is not None:
        changes = vocab.impact(vocab.diff(locked, current), nodes, edges)
        breaking = [c for c in changes if c.severity == vocab.Change.BREAKING]
        if breaking:
            touched = sum(c.affected for c in breaking)
            out.append("vocabulary has %d breaking change(s) since version %d was accepted, "
                       "touching %d node(s) or edge(s). Run `oto ontology check`."
                       % (len(breaking), locked.version, touched))
        elif changes:
            out.append("vocabulary changed since version %d was accepted (%d non-breaking change(s)). "
                       "Run `oto ontology accept` to record it." % (locked.version, len(changes)))

    cfg = project.config()
    backend = ((cfg.get("serve") or {}).get("backend") or "sqlite").lower()
    if backend == "neo4j":
        targets = cfg.get("targets") or ["sqlite"]
        if "neo4j" not in targets or not (cfg.get("neo4j") or {}).get("uri"):
            out.append("project.config.json serves from Neo4j (serve.backend) but the build does not load it: "
                       "add \"neo4j\" to targets and set neo4j.uri, or the server will answer nothing.")
    elif backend != "sqlite":
        out.append("project.config.json names an unknown serve.backend %r; the engine serves sqlite." % backend)

    report = vocab.conformance(current, nodes, edges)
    total = report["domain_violations"] + report["range_violations"]
    if total:
        out.append("%d edge endpoint(s) do not match the declared domain or range. This affects the "
                   "RDF export, where they are inference rules. Run `oto ontology check`." % total)
    attrs = vocab.attribute_conformance(current, nodes)
    if attrs["undeclared"]:
        out.append("%d attribute key(s) are carried by classes that declare their attributes but not "
                   "these; declare them or set strict_attributes to refuse them. Run `oto ontology check`."
                   % len(attrs["undeclared"]))
    return out
