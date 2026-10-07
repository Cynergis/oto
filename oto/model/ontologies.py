# -*- coding: utf-8 -*-
"""Starter vocabularies.

A blank `ontology.config.json` is the single biggest reason a team without an ontologist gives up.
An ontology is not a finished model. It is a first draft that already builds, so the team edits
something concrete instead of facing an empty file.

Each ontology is a directory holding a vocabulary and what goes with it:

    manifest.json             manifest: name, release, what it extends, what it carries (optional)
    ontology.config.json      the vocabulary
    ontology.rationale.json   why each class exists
    README.md                 why these classes exist, what to change, what to have validated
    sample.graph.json         a tiny valid graph, so `oto build` works immediately
    rules.json                derive and policy rules (optional)
    questions.json            competency questions that run (reason/questions.py)
    lexicon.json              seed jargon and synonyms for the domain (optional)
    interview.md              the questions the interview asks in this domain (optional)
    guide.md                  what this domain's graph is for and how to read it: what the
                              concierge skill quotes to a newcomer (optional)
    actions/<id>.json         what can be done about an entity, in MCP tool shape, bound to the
                              graph; installed as the project's actions/ (optional)
    gold/patterns.jsonl       question patterns per class, for evaluation (optional)

An ontology may extend others (`extends` in the manifest); `load` returns the composed result, so
a project gets the whole vocabulary, and `load_raw` returns an ontology's own files. See
`ontology_compose.py` for what an extending ontology may override.

The sample graph matters more than it looks. A team that can run the whole loop on day one, and see a
cited answer come back, understands what they are building. A team staring at an empty config does not.

Ontologies come from two places, and a project can be turned into one:

    oto/ontologies/<name>/       shipped with the package
    ~/.oto/ontologies/<name>/    yours, written by `oto ontology export` (OTO_ONTOLOGIES overrides)
    any directory path          passed directly to `oto init --ontology <path>`

A user ontology with the same name as a shipped one shadows it, so a team can keep its own edited
version of `auto-claims` under the same name.
"""
import json
import os
import types

from . import namespaces as _namespaces
from . import ontology_compose as _compose
from . import ontology_manifest as _manifest
from .ontology_compose import OntologyError  # noqa: F401  (re-exported: callers catch it here)

# Shipped inside the package (oto/ontologies/<name>/), so an installed engine finds them.
ONTOLOGY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ontologies")
USER_DIR_ENV = "OTO_ONTOLOGIES"
CONFIG_NAME = "ontology.config.json"
SAMPLE_NAME = "sample.graph.json"
README_NAME = "README.md"
RATIONALE_NAME = "ontology.rationale.json"
RULES_NAME = "rules.json"
QUESTIONS_NAME = "questions.json"
LEXICON_NAME = "lexicon.json"
INTERVIEW_NAME = "interview.md"
GUIDE_NAME = "guide.md"
ACTIONS_NAME = "actions"
GOLD_NAME = os.path.join("gold", "patterns.jsonl")
MANIFEST_NAME = _manifest.MANIFEST_NAME
BUILTIN = "built-in"
USER = "user"
FETCHED = "fetched"
PATH = "path"


def _root():
    return os.path.normpath(ONTOLOGY_DIR)


def user_dir():
    return os.path.expanduser(os.environ.get(USER_DIR_ENV) or os.path.join("~", ".oto", "ontologies"))


def _roots():
    """(directory, origin), user first so it shadows the shipped set."""
    return [(user_dir(), USER), (_root(), BUILTIN)]


def _is_ontology_dir(path):
    return os.path.isdir(path) and os.path.exists(os.path.join(path, CONFIG_NAME))


def dir_for(name, roots=None):
    """The directory an ontology name resolves to, or None. A name may be a path.

    `roots` are extra directories searched first: a registry checkout, so an ontology and the
    siblings it extends resolve together before anything on this machine.
    """
    if os.sep in name or (os.altsep and os.altsep in name) or name.startswith("."):
        path = os.path.abspath(name)
        return path if _is_ontology_dir(path) else None
    for root in list(roots or []) + [r for r, _origin in _roots()]:
        path = os.path.join(root, name)
        if _is_ontology_dir(path):
            return path
    return None


def origin(name):
    """Where an ontology comes from: built-in, user (yours), fetched (from a registry or a URL), or path."""
    path = dir_for(name)
    if path is None:
        return None
    for root, kind in _roots():
        if os.path.dirname(path) == os.path.normpath(root):
            if kind == USER and _manifest.read(path).get("source"):
                return FETCHED
            return kind
    return PATH


def available():
    """Ontology names, sorted. A directory counts only if it holds a vocabulary."""
    names = set()
    for root, _origin in _roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            if _is_ontology_dir(os.path.join(root, name)):
                names.add(name)
    return sorted(names)


def path_for(name, filename):
    base = dir_for(name)
    if base is None:
        raise KeyError(name)
    return os.path.join(base, filename)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_text(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_gold(path):
    """Question patterns, one JSON object per line. A bad line is kept as a marker for the self-check."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_malformed": number})
    return out


def manifest_dir(base):
    """The manifest of an ontology directory, defaults filled in."""
    config = _read_json(os.path.join(base, CONFIG_NAME), {})
    return _manifest.read(base, fallback_summary=(config.get("_summary") or "").strip())


def manifest_for(name, roots=None):
    """The manifest, defaults filled in. Raises KeyError for an unknown ontology."""
    base = dir_for(name, roots)
    if base is None:
        raise KeyError(name)
    return manifest_dir(base)


def load_raw(name, roots=None):
    """An ontology's own files, uncomposed: config, sample, readme, rationale, rules, questions,
    lexicon, interview, gold, manifest. Raises KeyError for an unknown ontology."""
    base = dir_for(name, roots)
    if base is None:
        raise KeyError(name)
    return load_raw_dir(base)


def load_raw_dir(base):
    rules = _read_json(os.path.join(base, RULES_NAME), {"rules": []})
    questions = _read_json(os.path.join(base, QUESTIONS_NAME), {"questions": {}})
    rationale = _read_json(os.path.join(base, RATIONALE_NAME), {})
    return {"config": _read_json(os.path.join(base, CONFIG_NAME), {}),
            "sample": _read_json(os.path.join(base, SAMPLE_NAME), {"nodes": [], "edges": []}),
            "readme": _read_text(os.path.join(base, README_NAME)),
            "rationale": {"classes": rationale.get("classes") or {}, "properties": rationale.get("properties") or {}},
            "rules": list(rules.get("rules") or []) if isinstance(rules, dict) else list(rules),
            "questions": dict((questions.get("questions") if "questions" in questions else questions) or {})
            if isinstance(questions, dict) else {},
            "lexicon": _read_json(os.path.join(base, LEXICON_NAME), None),
            "interview": _read_text(os.path.join(base, INTERVIEW_NAME)) or None,
            "guide": _read_text(os.path.join(base, GUIDE_NAME)) or None,
            "actions": _read_actions(base),
            "gold": _read_gold(os.path.join(base, GOLD_NAME)),
            "manifest": manifest_dir(base)}


def _read_actions(base):
    """The action files an ontology ships, readable ones only: [dict]. The self-check names the rest."""
    from ..actions import model as _actions
    return [action for _rel, action, error in _actions.load_dir(os.path.join(base, ACTIONS_NAME))
            if not error and isinstance(action.get("id"), str)]


def parts(name, roots=None):
    """The ontologies a name composes, bases first, the name last. Raises OntologyError."""
    if dir_for(name, roots) is None:
        raise KeyError(name)
    return _compose.resolve(name, lambda n: manifest_for(n, roots))


def composed(name, roots=None):
    """The ontology with everything it extends applied. Raises KeyError or OntologyError.
    With `roots`, a checkout is searched first for the ontology and what it extends."""
    return _compose.compose(name, parts(name, roots), lambda n: load_raw(n, roots))


def rules_for(name):
    """The rules an ontology ships, its bases included, or an empty list."""
    return composed(name)["rules"]


def questions_for(name):
    """The competency questions an ontology ships, its bases included: {id: question}."""
    return composed(name)["questions"]


def rationale_for(name):
    """The recorded reasoning, its bases included."""
    return composed(name)["rationale"]


def lexicon_for(name):
    return composed(name)["lexicon"]


def interview_for(name):
    return composed(name)["interview"]


def guide_for(name):
    return composed(name)["guide"]


def actions_for(name):
    """The actions an ontology ships, its bases included, or an empty list."""
    return composed(name)["actions"]


def gold_for(name):
    return composed(name)["gold"]


def load(name):
    """Return (vocabulary config, sample graph, readme text), composed. Raises KeyError if unknown."""
    result = composed(name)
    return result["config"], result["sample"], result["readme"]


def summary(name):
    """One line for a listing."""
    manifest = manifest_for(name)
    try:
        config, sample, _ = load(name)
    except OntologyError:
        config, sample = {}, {}
    return {
        "name": name,
        "title": config.get("name", name),
        "release": manifest["release"],
        "domain": manifest.get("domain"),
        "extends": list(manifest.get("extends") or []),
        "classes": len(config.get("classes") or {}),
        "properties": len(config.get("properties") or {}),
        "sample_nodes": len(sample.get("nodes") or []),
        "about": (manifest.get("summary") or config.get("_summary") or "").strip(),
        "carries": list(manifest.get("carries") or []),
        "origin": origin(name),
    }


def self_check(name, roots=None):
    """Problems with an ontology. An empty list means it is usable.

    Checked here rather than only in a build, because a broken ontology wastes the time of the person
    least able to diagnose it.
    """
    base = dir_for(name, roots)
    if base is None:
        return ["unknown ontology %r" % name]
    problems = _manifest.problems(base)
    try:
        result = composed(name, roots)
    except OntologyError as exc:
        return problems + [str(exc)]
    config, sample, readme = result["config"], result["sample"], result["readme"]
    classes = config.get("classes") or {}
    properties = config.get("properties") or {}

    if not classes:
        problems.append("declares no classes")
    if not properties:
        problems.append("declares no properties")
    if not config.get("ontology_version"):
        problems.append("has no ontology_version")
    if not readme.strip():
        problems.append("has no README explaining the choices")

    from . import vocabulary as _vocab
    malformed = _vocab.shape_problems(config) or _vocab.hierarchy_problems(config) + _vocab.scheme_problems(config)
    if malformed:
        return problems + malformed

    for relation, spec in sorted(properties.items()):
        for position in ("domain", "range"):
            for kind in _union(spec.get(position)):
                if kind not in classes:
                    problems.append("relation %r names an undeclared class in its %s: %s"
                                    % (relation, position, kind))
        if not (spec.get("definition") or "").strip():
            problems.append("relation %r has no definition" % relation)

    for kind, spec in sorted(classes.items()):
        if not (spec.get("definition") or "").strip():
            problems.append("class %r has no definition" % kind)

    problems += _vocab.declaration_problems(classes, config.get("attributes") or {}, config.get("schemes") or {})
    from ..reason import rules as _rules
    problems += _rules.problems(result["rules"], config)
    from ..reason import questions as _questions, shapes as _shapes
    question_problems = _questions.problems(result["questions"], config)
    problems += question_problems
    problems += _shapes.problems(config)
    if not question_problems:
        problems += _shapes.rule_question_problems(result["rules"], result["questions"])
    from ..actions import model as _actions
    own_actions = _actions.load_dir(os.path.join(base, ACTIONS_NAME))
    for rel, _action, error in own_actions:
        if error:
            problems.append("%s: %s" % (rel, error))
    composed_actions = [(os.path.join(ACTIONS_NAME, a["id"] + ".json"), a, None) for a in result["actions"]]
    problems += _actions.problems(composed_actions, config) if composed_actions else []
    sample_ids = {n.get("id") for n in (sample.get("nodes") or [])}
    for action in result["actions"]:
        if action.get("executed_by") and action["executed_by"] not in sample_ids:
            problems.append("action %r is executed_by %r, which the sample does not hold" % (action["id"], action["executed_by"]))
    # The questions are the ontology's contract: the sample must answer every one it must, and
    # every term must be cited by a question that runs, or nobody can tell what the term is for.
    if not question_problems:
        for term in _questions.uncovered(result["questions"], config):
            problems.append("no question cites %s %s: what does it exist to answer? (questions.json)"
                            % ("attribute" if "." in term else ("class" if term in classes else "relation"), term))
    if not problems:
        for item in _shapes.findings(config, sample.get("nodes") or [], sample.get("edges") or []):
            problems.append("the sample breaks a declared shape: %s" % item["message"])
        # a sample that breaks the ontology's own blocking policy is not an example of it
        from ..reason import engine as _engine
        try:
            outcome = _engine.run(result["rules"], sample.get("nodes") or [], sample.get("edges") or [],
                                  covers=_vocab.covers(classes), declared=_questions.declared_names(config))
        except _engine.DoesNotConverge as exc:
            problems.append(str(exc))
        else:
            for finding in outcome["findings"]:
                if finding["severity"] == "blocking":
                    problems.append("the sample breaks its own policy %s: %s (%s)" % (finding["rule"], finding["message"], finding.get("node") or "graph"))
        for finding in _questions.findings(result["questions"], sample.get("nodes") or [], sample.get("edges") or [],
                                           _vocab.covers(classes), declared=_questions.declared_names(config)):
            for item in finding["unanswered"] or [{"label": "(graph)", "status": finding["status"], "gaps": finding["gaps"]}]:
                problems.append("the sample cannot answer %s as required: %s, %s%s"
                                % (finding["id"], item["label"], item["status"],
                                   ("; " + "; ".join(item["gaps"])) if item["gaps"] else ""))
        attrs = _vocab.attribute_conformance(_vocab.Vocabulary.from_config(config), sample.get("nodes") or [])
        for nid, key, why, value in attrs["mistyped"]:
            problems.append("sample node %r attribute %s = %r: %s" % (nid, key, value, why))
        for (kind, key), _count in attrs["undeclared"]:
            problems.append("sample uses attribute %s.%s that the ontology does not declare" % (kind, key))

    # An ontology is the exemplar. Shipping one with no recorded reasoning teaches that the
    # reasoning is optional, which is the habit this whole file exists to prevent.
    from . import rationale as _rationale
    record = result["rationale"]
    coverage = _rationale.report(config, record)
    problems += coverage["problems"]
    for missing in coverage["classes_missing"]:
        problems.append("class %r has no recorded rationale" % missing)

    # The sample must be usable with THIS vocabulary, or the first build fails.
    ids = set()
    for node in sample.get("nodes") or []:
        ids.add(node.get("id"))
        if node.get("type") not in classes:
            problems.append("sample node %r has undeclared type %r"
                            % (node.get("id"), node.get("type")))
        for field in ("as_of", "valid_from", "source_doc", "status"):
            if not node.get(field):
                problems.append("sample node %r is missing %s" % (node.get("id"), field))
    for edge in sample.get("edges") or []:
        if edge.get("rel") not in properties:
            problems.append("sample edge uses undeclared relation %r" % edge.get("rel"))
        for end in ("from", "to"):
            if edge.get(end) not in ids:
                problems.append("sample edge %s points at unknown node %r"
                                % (edge.get("rel"), edge.get(end)))

    # The optional files: a seed lexicon, the interview, the gold patterns.
    for number, entry in enumerate(((result["lexicon"] or {}).get("entries") or []), 1):
        if not isinstance(entry, dict) or not entry.get("term"):
            problems.append("lexicon entry %d has no `term`" % number)
            continue
        for target in entry.get("targets") or []:
            if target not in ids and entry.get("status") != "not_ingested":
                problems.append("lexicon entry %r targets %r, which the sample does not hold" % (entry["term"], target))
    if result["interview"] is not None and not any(line.startswith("## ") for line in result["interview"].splitlines()):
        problems.append("interview.md has no questions: one `## ` heading per question, the reasoning under it")
    own_guide = load_raw(name, roots)["guide"] if dir_for(name, roots) else result["guide"]
    if own_guide is not None and not any(line.startswith("## ") for line in own_guide.splitlines()):
        problems.append("guide.md has no sections: one `## ` heading per topic (what the graph is for, the "
                        "questions it answers, where to start, common mistakes)")
    for entry in result["gold"]:
        if "_malformed" in entry:
            problems.append("gold/patterns.jsonl line %d is not JSON" % entry["_malformed"])
        elif not isinstance(entry, dict) or not isinstance(entry.get("pattern"), str) or not entry.get("pattern", "").strip():
            problems.append("gold pattern %r needs a `pattern` string" % (entry,))
        elif entry.get("class") not in classes:
            problems.append("gold pattern %r names class %r, which the ontology does not declare"
                            % (entry["pattern"][:40], entry.get("class")))

    # Publishability: an ontology leaves the machine, so it must carry no client name and no
    # personal data. Deny terms come from the environment, never from a file in the ontology.
    problems += publishability_problems(name, sample, roots)
    return problems


def publishability_problems(name, sample=None, roots=None):
    """Deny terms found in any part's text files, and personal data in the composed sample."""
    from ..validate import privacy as _privacy

    out = []
    terms = sorted({t.strip().lower() for t in os.environ.get("OTO_DENY_TERMS", "").split(",") if t.strip()})
    if terms:
        for part in parts(name, roots):
            base = dir_for(part, roots)
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for filename in sorted(filenames):
                    path = os.path.join(dirpath, filename)
                    try:
                        text = _read_text(path).lower()
                    except (OSError, UnicodeDecodeError):
                        continue
                    hits = [t for t in terms if t in text]
                    if hits:
                        out.append("%s in %s names a deny term (%s); an ontology must not"
                                   % (os.path.relpath(path, base), part, ", ".join(hits)))
    if sample is None:
        sample = composed(name, roots)["sample"]
    text = "\n".join(" ".join([str(n.get("label") or ""), str(n.get("summary") or ""),
                                " ".join(n.get("aliases") or []), json.dumps(n.get("attributes") or {})])
                      for n in sample.get("nodes") or [])
    findings = _privacy.scan(text)
    if _privacy.blocking(findings):
        out.append("the sample holds personal data or a credential: %s" % _privacy.summarize(findings))
    return out


# ---- turning a project into an ontology ----

SAMPLE_STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "sample",
                "status": "current", "sources": ["sample"]}


def _union(spec):
    return [x.strip() for x in (spec or "").split("|") if x.strip()]


def synthetic_sample(config):
    """One example node per class and one edge per relation, invented, so the sample carries no
    data from the project it came from and still exercises every declared term."""
    classes = config.get("classes") or {}
    properties = config.get("properties") or {}
    nodes, edges, ids = [], [], {}

    from .vocabulary import concepts_of, parse_attribute_type, declared_attributes

    def example_value(spec):
        kind, options = parse_attribute_type(spec)
        if kind in ("enum", "scheme"):
            return next(iter(concepts_of(spec, config.get("schemes") or {})), "example")
        return {"string": "example", "number": 1.5, "integer": 1, "boolean": True, "date": "2026-01-01", "list": ["example"]}[kind]

    ids_kind = {}

    def node_for(kind, suffix=""):
        nid = "%s.example%s" % (kind.lower(), suffix)
        if nid not in ids:
            ids[nid] = True
            ids_kind[nid] = kind
            # every declared attribute, inherited ones included, so a required one is never missing
            attributes = {a: example_value(spec["type"]) for a, spec in declared_attributes(config, kind).items()}
            nodes.append(dict(id=nid, type=kind, label="%s example%s" % (kind, suffix.replace("-", " ")),
                              aliases=[], summary=(classes[kind].get("definition") or "").strip() or "An example.",
                              attributes=attributes, tags=[kind.lower()], **SAMPLE_STAMP))
        return nid

    for kind in classes:
        node_for(kind)
    seen = set()
    out_count = {}

    def link(src, relation, dst):
        """One edge, unless the relation's declared `max` is already met on the subject."""
        high = properties[relation].get("max")
        if (src, relation, dst) in seen or (high is not None and out_count.get((src, relation), 0) >= high):
            return
        seen.add((src, relation, dst))
        out_count[(src, relation)] = out_count.get((src, relation), 0) + 1
        edges.append({"from": src, "rel": relation, "to": dst})

    # Every declared pair of domain and range, so a question about any of them finds an edge; a
    # relation from a class to itself points at a twin of the example.
    for relation, spec in properties.items():
        domain, rng = _union(spec.get("domain")), _union(spec.get("range"))
        if not domain:
            continue
        if not rng:                                            # any class: point the example at its own kind
            rng = domain
        for kind in domain:
            for other in rng:
                link(node_for(kind), relation, node_for(other, "-2") if other == kind else node_for(other))
    # A twin is an example of its class too: it takes part in everything the example does, so a
    # question that every instance must answer (and a policy that none may violate) sees it whole.
    # When the example's `max` on a relation is spent (a component is part of one system), the twin
    # gets a twin of the subject instead, so it is reached the way the example is.
    done = set()
    while True:
        twins = [n["id"] for n in nodes if n["id"].endswith(".example-2") and n["id"] not in done]
        if not twins:
            break
        for twin in twins:
            done.add(twin)
            example = twin[:-2]
            for edge in list(edges):
                if edge["from"] == example and edge["to"] != twin:
                    link(twin, edge["rel"], edge["to"])
                if edge["to"] == example and edge["from"] != twin:
                    src, rel = edge["from"], edge["rel"]
                    high = properties[rel].get("max")
                    if high is not None and out_count.get((src, rel), 0) >= high and not src.endswith(".example-2"):
                        src = node_for(ids_kind[src], "-2")
                    link(src, rel, twin)
    return {"_about": "An invented sample so `oto build` works the moment the ontology is installed. "
                      "Replace it.", "nodes": nodes, "edges": edges}


def sample_from_graph(graph, config, limit):
    """Up to `limit` real nodes, round-robin across classes so every class is represented, plus the
    edges among them. The caller must privacy-scan the result before shipping it anywhere."""
    by_class = {}
    for node in graph.get("nodes") or []:
        if node.get("status", "current") == "current" and node.get("type") in (config.get("classes") or {}):
            by_class.setdefault(node["type"], []).append(node)
    chosen, ids = [], set()
    while len(chosen) < limit and any(by_class.values()):
        for kind in sorted(by_class):
            if by_class[kind] and len(chosen) < limit:
                node = by_class[kind].pop(0)
                chosen.append(dict(node))
                ids.add(node["id"])
    edges = [dict(e) for e in (graph.get("edges") or [])
             if e.get("from") in ids and e.get("to") in ids and e.get("rel") in (config.get("properties") or {})]
    return {"_about": "A sample taken from a real project. Replace it.", "nodes": chosen, "edges": edges}


def _readme(name, config, rationale, source_name, confirmed):
    classes = config.get("classes") or {}
    properties = config.get("properties") or {}
    entries = rationale.get("classes") or {}
    lines = ["# %s — starter vocabulary" % config.get("name", name), "",
             "Exported from the project **%s** (vocabulary version %s) with `oto ontology export`."
             % (source_name, config.get("_exported_from_version", "?")), "",
             "A first draft, not a finished model. **Edit it.** An ontology adopted unchanged is a worse "
             "outcome than no ontology, because nobody owns it and nobody recognizes the words.", ""]
    if confirmed:
        lines += ["In the source project, %d of %d classes had been confirmed by a named domain expert. "
                  "That confirmation does not carry over: `validated_by` is empty here until someone "
                  "who knows *your* domain confirms each class." % (confirmed, len(classes)), ""]
    lines += ["## Classes, and the question each answers", ""]
    for kind in classes:
        entry = entries.get(kind) or {}
        lines.append("- **%s**: %s" % (kind, (classes[kind].get("definition") or "").strip()))
        if entry.get("question"):
            lines.append("  - *Question:* %s" % entry["question"].strip())
        if entry.get("why"):
            lines.append("  - *Why a class:* %s" % entry["why"].strip())
    lines += ["", "## Relations", "", "| Relation | Domain | Range | Meaning |", "| --- | --- | --- | --- |"]
    for relation, spec in properties.items():
        lines.append("| `%s` | %s | %s | %s |" % (relation, spec.get("domain") or "", spec.get("range") or "",
                                                  spec.get("definition") or ""))
    lines += ["", "## Growing it", "", "```bash",
              "oto ontology check --project <root>      # what a change breaks, and conformance",
              "oto ontology rationale --project <root>  # which classes still lack a confirmed reason",
              "oto ontology accept --project <root>     # record the vocabulary as the baseline",
              "```", ""]
    return "\n".join(lines)


def export(project, name, to=None, from_graph=0, summary=None, force=False):
    """Write an ontology from a project's vocabulary. Returns (path, problems).

    Refuses when the rationale is incomplete: an ontology is the exemplar, and shipping one whose
    classes have no recorded reason teaches that the reasoning is optional. Refuses a real-data
    sample that the privacy scan blocks.
    """
    from ..validate import privacy as _privacy
    from . import rationale as _rationale

    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    record = _rationale.load(project)
    coverage = _rationale.report(config, record)
    if coverage["classes_missing"] or coverage["problems"]:
        raise ValueError("the vocabulary is not ready to be an ontology: %d class(es) have no recorded "
                         "reason and %d rationale problem(s). Run `oto ontology rationale` and fix "
                         "them first." % (len(coverage["classes_missing"]), len(coverage["problems"])))

    target = os.path.join(os.path.abspath(to) if to else user_dir(), name)
    if os.path.exists(target) and not force:
        raise FileExistsError(target)

    identity = project.identity()
    exported = dict(config)
    exported["_about"] = ("Starter vocabulary exported from the project %r. A FIRST DRAFT to edit, "
                          "not a finished model. A relation is {domain, range, inverse, definition}. "
                          "Use A|B for a union." % identity["name"])
    exported["_exported_from_version"] = config.get("ontology_version", 1)
    exported["_summary"] = (summary or config.get("_summary") or "").strip()
    exported["ontology_version"] = 1
    exported["strict_domains"] = False

    rationale = {"_about": ("Why each class and relation exists. `validated_by` is empty on purpose: "
                            "confirmation in the source project does not carry to a new domain."),
                 "classes": {}, "properties": {}}
    for section in ("classes", "properties"):
        for key, entry in (record.get(section) or {}).items():
            copied = dict(entry)
            copied["validated_by"] = ""
            rationale[section][key] = copied
    confirmed = len(coverage["classes_validated"])

    if from_graph:
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        sample = sample_from_graph(graph, config, from_graph)
        text = "\n".join(" ".join([str(n.get("label") or ""), str(n.get("summary") or ""),
                                    " ".join(n.get("aliases") or []), json.dumps(n.get("attributes") or {})])
                          for n in sample["nodes"])
        findings = _privacy.scan(text)
        if _privacy.blocking(findings):
            raise ValueError("the real-data sample contains personal data or a credential:\n%s\n"
                             "Use the invented sample (omit --from-graph)." % _privacy.summarize(findings))
    else:
        sample = synthetic_sample(config)

    from ..reason import rules as _rules, questions as _questions
    shipped_rules = [dict(r, validated_by="") for r in _rules.load(project)]
    shipped_questions = {qid: dict(q, validated_by="") for qid, q in _questions.load(project).items()}
    os.makedirs(target, exist_ok=True)
    from ..actions import model as _actions
    sample_by_type = {}
    for n in sample.get("nodes") or []:
        sample_by_type.setdefault(n.get("type"), n.get("id"))
    graph_types = {}
    if os.path.exists(project.graph_path):
        with open(project.graph_path, encoding="utf-8") as f:
            graph_types = {n.get("id"): n.get("type") for n in (json.load(f).get("nodes") or [])}
    for rel, action, error in _actions.load(project):
        if error:
            continue
        action = dict(action)
        by = action.get("executed_by")
        if by and by not in {n.get("id") for n in sample.get("nodes") or []}:
            stand_in = sample_by_type.get(graph_types.get(by))     # the sample's node of the same class
            if stand_in:
                action["executed_by"] = stand_in
            else:
                action.pop("executed_by", None)
        os.makedirs(os.path.join(target, ACTIONS_NAME), exist_ok=True)
        with open(os.path.join(target, rel), "w", encoding="utf-8", newline="\n") as f:
            json.dump(action, f, indent=2, ensure_ascii=False)
            f.write("\n")
    if shipped_rules:
        with open(os.path.join(target, RULES_NAME), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"rules": shipped_rules}, f, indent=2, ensure_ascii=False)
            f.write("\n")
    if shipped_questions:
        _questions.save(types.SimpleNamespace(data=target), shipped_questions)
    for filename, payload in ((CONFIG_NAME, exported), (RATIONALE_NAME, rationale), (SAMPLE_NAME, sample)):
        with open(os.path.join(target, filename), "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
    with open(os.path.join(target, README_NAME), "w", encoding="utf-8", newline="\n") as f:
        f.write(_readme(name, exported, rationale, identity["name"], confirmed))
    from .. import __version__
    engine = ">=%s" % ".".join(str(x) for x in _manifest._version_tuple(__version__)[:2])
    # The terms the project declared itself keep the IRIs its own export gave them; what it took
    # from other ontologies is in the vocabulary's `namespaces` section and keeps theirs.
    # Exporting over an ontology that exists (--force) is its next release: the namespace it
    # published, its maintainer and its changelog are kept, and the release number rises.
    previous = _manifest.read(target) if os.path.exists(os.path.join(target, _manifest.MANIFEST_NAME)) else None
    release = int(previous.get("release") or 0) + 1 if previous and previous.get("_declared") else 1
    _manifest.write(target, {"name": name, "release": release, "summary": exported["_summary"],
                             "extends": list(previous.get("extends") or []) if previous else [],
                             "namespace": (previous or {}).get("namespace") or _namespaces.Terms(config, identity).project,
                             "engine": engine, "carries": _manifest.detect_carries(target),
                             "maintainer": (previous or {}).get("maintainer") or "",
                             "changelog": [{"release": release, "at": _today(),
                                            "note": "Exported from the project %s." % identity["name"]}]
                             + list((previous or {}).get("changelog") or [])})
    return target, self_check(target)


def _today():
    import datetime
    return datetime.date.today().isoformat()


# ---- composing ontologies ----

def merge(names):
    """Combine ontologies into one vocabulary. Returns (config, sample, readme, rationale, report).

    The union of classes and relations, first ontology winning a name clash. The report lists
    every clash so a person can see what was silently kept, and the totals, because two glued
    ontologies are the fastest way to the forty-class model nobody owns. Prune before accepting.
    """
    classes, properties, temporal, attributes, namespaces, schemes = {}, {}, {}, {}, {}, {}
    rationale = {"classes": {}, "properties": {}}
    merged_rules, merged_questions = {}, {}
    owner = {}
    report = {"ontologies": list(names), "class_clashes": [], "relation_clashes": []}
    summaries, readmes, titles = [], [], []

    lexicon_entries, interviews, guides, gold, merged_actions = [], [], [], [], {}
    sample_nodes, sample_edges, sample_keys = {}, [], set()
    for name in names:
        result = composed(name)
        config, readme, record = result["config"], result["readme"], result["rationale"]
        # the samples merge by node id, as composition merges them: a merged project starts
        # with the facts its parts ship, not an invented graph
        for node in (result["sample"] or {}).get("nodes") or []:
            sample_nodes.setdefault(node.get("id"), node)
        for edge in (result["sample"] or {}).get("edges") or []:
            key = (edge.get("from"), edge.get("rel"), edge.get("to"))
            if key not in sample_keys:
                sample_keys.add(key)
                sample_edges.append(edge)
        titles.append(config.get("name", name))
        about = (result["manifest"].get("summary") or config.get("_summary") or "").strip()
        if about:
            summaries.append(about)
        lexicon_entries += list((result["lexicon"] or {}).get("entries") or [])
        if result["interview"]:
            interviews.append(result["interview"].strip())
        if result["guide"]:
            guides.append("## From `%s`\n\n%s" % (name, result["guide"].strip()))
        gold += list(result["gold"])
        readmes.append((name, readme))
        for kind, description in (config.get("classes") or {}).items():
            if kind in classes and classes[kind] != description:
                report["class_clashes"].append((kind, owner[kind], name))
            classes.setdefault(kind, description)
            owner.setdefault(kind, name)
        for relation, spec in (config.get("properties") or {}).items():
            if relation in properties and [properties[relation].get(k) for k in ("domain", "range")] \
                    != [spec.get(k) for k in ("domain", "range")]:
                report["relation_clashes"].append((relation, owner[relation], name))
            properties.setdefault(relation, dict(spec))
            owner.setdefault(relation, name)
        for field, spec in (config.get("temporal") or {}).items():
            temporal.setdefault(field, spec)
        for kind, declared in (config.get("attributes") or {}).items():
            for attr, spec in (declared or {}).items():
                attributes.setdefault(kind, {}).setdefault(attr, dict(spec))
        _namespaces.inherit(namespaces, config.get(_namespaces.SECTION))
        for scheme_name, scheme in (config.get("schemes") or {}).items():
            schemes.setdefault(scheme_name, scheme)
        for rule in result["rules"]:
            merged_rules.setdefault(rule["id"], dict(rule))
        for qid, question in result["questions"].items():
            merged_questions.setdefault(qid, dict(question))
        for action in result.get("actions") or []:
            merged_actions.setdefault(action["id"], dict(action))
        for section in ("classes", "properties"):
            for key, entry in (record.get(section) or {}).items():
                rationale[section].setdefault(key, dict(entry))

    config = {"_about": "Merged from the ontologies %s. A FIRST DRAFT to prune, not a finished model."
                        % ", ".join(names),
              "_summary": " + ".join(summaries), "name": " + ".join(titles),
              "ontology_version": 1, "strict_domains": False,
              "classes": classes, "properties": properties, "temporal": temporal}
    if attributes:
        config["attributes"] = attributes
    if schemes:
        config["schemes"] = schemes
    if _namespaces.settled(namespaces):
        config[_namespaces.SECTION] = _namespaces.settled(namespaces)
    config["_rules"] = list(merged_rules.values())
    config["_questions"] = merged_questions
    config["_lexicon"] = {"entries": lexicon_entries} if lexicon_entries else None
    config["_interview"] = "\n\n".join(interviews) if interviews else None
    config["_guide"] = "\n\n".join(guides) if guides else None
    config["_actions"] = list(merged_actions.values())
    config["_gold"] = gold
    report["classes"] = len(classes)
    report["properties"] = len(properties)
    readme = ["# Merged starter vocabulary: %s" % ", ".join(names), "",
              "A first draft, not a finished model. **Edit it**, and prune it first: a merge keeps "
              "every class from every ontology, and a first ontology is almost always too big. Keep "
              "the classes a real question needs and write down which.", "",
              "%d classes and %d relations after the merge." % (len(classes), len(properties)), ""]
    for name, text in readmes:
        readme += ["", "---", "", "## From `%s`" % name, "", text.strip(), ""]
    sample = {"nodes": list(sample_nodes.values()), "edges": sample_edges} if sample_nodes else synthetic_sample(config)
    return config, sample, "\n".join(readme), rationale, report
