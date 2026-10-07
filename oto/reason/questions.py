# -*- coding: utf-8 -*-
"""Competency questions that run.

A question is what the ontology exists to answer, written once in the pattern language of
`rules.json` and executed over the graph, so "can this graph answer X" is measured rather than
hoped. Declared in `questions.json` beside the graph:

    {"CQ3": {"who": "claims handler",
             "question": "Which coverage is claim $CLAIM being paid under, and what limit applies?",
             "why": "A payment charged to the wrong coverage is the costliest error in handling.",
             "validated_by": "",
             "params": {"CLAIM": {"type": "Claim"}},
             "ask": {"when": [{"edge": ["$CLAIM", "paid_under", "c"]}, {"node": "c", "type": "Coverage"}],
                     "select": ["c", "c.limit"]},
             "gate": "non_empty",
             "gaps": {"when": [{"not_edge": ["$CLAIM", "paid_under", "*"]}], "say": "the claim names no coverage"},
             "terms": ["Coverage.deductible"]}}

`ask.when` is a rule's `when` (node, edge, not_edge, not_node, where), plus `optional`: a list of
patterns that extend a binding when they match and leave their variables unbound when they do
not, for what a question reports when it is there and does not require. A `where` may say
`{"exists": false}`, and its value may name a bound variable: `"$REPORT"` is that entity's id,
`"$FIELD.fieldId"` one of its attributes. `gaps` is one `{when, say}` or a list of them. `select` names bound
variables (a parameter as `$NAME`), or `var.<field>` for a node's own field (`label`, `type`, `id`,
`status`, `as_of`, `valid_from`, `valid_to`, `source_doc`) or `var.<attribute>` for a declared one.
A `$NAME` is a parameter, bound to an entity before the patterns run; its `type` may be a union
`A|B`. The gate says what an empty answer means:
`non_empty` (the graph must answer), `empty` (nothing must match; the shape of a policy), `any`
(informational), `no_gaps` (the answer may be empty, but a gap makes it unanswered: "which fields
must this artifact have" is answered by none when it is not JSON, unanswered when it is JSON and
names none). `gaps` runs when the answer is empty, or always under `no_gaps`, and says why, in words. `terms` lists the
vocabulary this question covers beyond what its patterns name, so every term can be required to
be cited by a question that runs.
"""
import json
import os
import re

from .match import Graph, matches, BELIEVED, BUILTIN_FIELDS

NAME = "questions.json"
GATES = ("non_empty", "empty", "any", "no_gaps")
#: The status a run ends in, by gate and whether rows came back. `no_gaps` may answer with no rows;
#: its gaps run whether or not rows came back, and any gap makes it unanswered.
STATUSES = {("non_empty", True): "answered", ("non_empty", False): "unanswered",
            ("empty", True): "violated", ("empty", False): "clean",
            ("any", True): "answered", ("any", False): "empty",
            ("no_gaps", True): "answered", ("no_gaps", False): "answered"}
#: What a status means for a gate: a question with one of these statuses is a finding.
FINDING_STATUSES = ("unanswered", "violated")
PARAM = re.compile(r"\$([A-Za-z][A-Za-z0-9_]*)")
#: What `select` may name on a variable beside a declared attribute: the node's own fields.
SELECT_FIELDS = BUILTIN_FIELDS


def path_for(project):
    return os.path.join(project.data, NAME)


def load(project):
    """The questions on record, {id: question} in file order, or {} when the project declares none."""
    path = path_for(project)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    questions = payload.get("questions") if isinstance(payload, dict) and "questions" in payload else payload
    return dict(questions or {}) if isinstance(questions, dict) else {}


def save(project, questions):
    with open(path_for(project), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_about": "What this ontology exists to answer. Each question runs over the graph in the "
                             "pattern language of rules.json; `gate` says what an empty answer means; `gaps` "
                             "says why it is empty; `terms` names the vocabulary the question covers. "
                             "Reasoned about in `why`, confirmed in `validated_by`.",
                   "questions": questions}, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ============================ the lock ============================

#: What changes a question's answers: a different pattern, selection, parameter or gate. The
#: wording, the reason, the asker, the gaps and the terms list are the same question, reworded.
ANSWER_KEYS = ("ask", "params", "gate")


def read_lock(project):
    """The questions as last accepted, or None when the project has never accepted a vocabulary."""
    from ..model.vocabulary import lock_path
    path = lock_path(project)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f).get("questions") or {})


def diff(old, new):
    """(added, removed, changed, reworded) question ids. A changed question answers differently
    (breaking: what the graph was asked to answer is no longer the same question); a reworded one
    keeps its ask (cosmetic)."""
    old, new = dict(old or {}), dict(new or {})
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed, reworded = [], []
    for qid in sorted(set(old) & set(new)):
        before, after = old[qid], new[qid]
        if any(json.dumps(before.get(k), sort_keys=True) != json.dumps(after.get(k), sort_keys=True) for k in ANSWER_KEYS):
            changed.append(qid)
        elif json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            reworded.append(qid)
    return added, removed, changed, reworded


# ============================ checking ============================

def _params_in(when, references=False):
    """Every $NAME a list of patterns uses as a variable; with `references`, every one a `where`
    value names instead (`$REPORT`, `$FIELD.fieldId`), which may also be a pattern variable."""
    out = set()
    for pattern in when or []:
        if not isinstance(pattern, dict):
            continue
        if not references:
            for key in ("edge", "not_edge"):
                spec = pattern.get(key)
                if isinstance(spec, list):
                    for item in spec:
                        if isinstance(item, str) and item.startswith("$"):
                            out.add(item[1:])
            if isinstance(pattern.get("node"), str) and pattern["node"].startswith("$"):
                out.add(pattern["node"][1:])
        else:
            for condition in (pattern.get("where") or {}).values():
                for expected in (condition.values() if isinstance(condition, dict) else [condition]):
                    if isinstance(expected, str):
                        from .match import REFERENCE, TODAY_REF
                        out |= {m.group(1) for m in REFERENCE.finditer(expected) if not TODAY_REF.match(expected)}
        if isinstance(pattern.get("optional"), list):
            out |= _params_in(pattern["optional"], references)
    return out


def _bound_in(when):
    """Variables the patterns bind (positive patterns, optional blocks included), without the parameters."""
    out = set()
    for pattern in when or []:
        if not isinstance(pattern, dict):
            continue
        if isinstance(pattern.get("node"), str):
            out.add(pattern["node"])
        spec = pattern.get("edge")
        if isinstance(spec, list) and len(spec) == 3:
            out.update(v for v in (spec[0], spec[2]) if isinstance(v, str) and v != "*")
        if isinstance(pattern.get("optional"), list):
            out |= _bound_in(pattern["optional"])
    return {v[1:] if v.startswith("$") else v for v in out}


def _substituted(when, params):
    """The patterns with `$NAME` replaced by the variable NAME, so the matcher sees plain variables.
    A `$NAME` inside a `where` value stays: the matcher reads it as a reference to the binding."""
    out = []
    for pattern in when:
        new = dict(pattern)
        if isinstance(new.get("node"), str) and new["node"].startswith("$"):
            new["node"] = new["node"][1:]
        for key in ("edge", "not_edge"):
            if isinstance(new.get(key), list):
                new[key] = [v[1:] if isinstance(v, str) and v.startswith("$") else v for v in new[key]]
        if isinstance(new.get("optional"), list):
            new["optional"] = _substituted(new["optional"], params)
        out.append(new)
    return out


def _gap_bodies(question):
    """`gaps` is one {when, say} or a list of them."""
    gaps = question.get("gaps")
    if gaps is None:
        return []
    return list(gaps) if isinstance(gaps, list) else [gaps]


def _kinds(spec):
    return [x.strip() for x in str(spec or "").split("|") if x.strip()]


def problems(questions, vocabulary):
    """What is wrong with a question set, before anything runs. Empty means usable."""
    from . import rules as _rules
    from ..model.vocabulary import declared_attributes
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    out = []
    if not isinstance(questions, dict):
        return ["questions must be an object of id -> question"]
    for qid, q in questions.items():
        label = "question %r" % qid
        if not isinstance(q, dict):
            out.append("%s must be an object" % label)
            continue
        if not (q.get("question") or "").strip():
            out.append("%s has no `question`: the sentence a person would ask" % label)
        if not (q.get("why") or "").strip():
            out.append("%s has no `why`: a question with no recorded reason cannot be reviewed" % label)
        if q.get("gate", "non_empty") not in GATES:
            out.append("%s: gate must be one of %s" % (label, ", ".join(GATES)))
        params = q.get("params") or {}
        if not isinstance(params, dict):
            out.append("%s: `params` must be an object of NAME -> {type}" % label)
            params = {}
        for name, spec in params.items():
            if not PARAM.fullmatch("$" + name):
                out.append("%s: parameter %r must be a word" % (label, name))
            kind = (spec or {}).get("type") if isinstance(spec, dict) else None
            if not kind:
                out.append("%s: parameter %r declares no `type`" % (label, name))
            for one in _kinds(kind):
                if one not in classes:
                    out.append("%s: parameter %r has class %r, which is not declared" % (label, name, one))
        ask = q.get("ask")
        if not isinstance(ask, dict) or not isinstance(ask.get("when"), list) or not ask["when"]:
            out.append("%s: `ask.when` must be a non-empty list of patterns" % label)
            continue
        bound_params = {name: _kinds((spec or {}).get("type")) for name, spec in params.items() if isinstance(spec, dict)}
        bodies = [("ask", ask)] + [("gaps", body) for body in _gap_bodies(q)]
        if q.get("gaps") is not None and not isinstance(q["gaps"], (dict, list)):
            out.append("%s: `gaps` must be {when, say} or a list of them" % label)
            bodies = [("ask", ask)]
        for key, body in bodies:
            if not isinstance(body, dict) or not isinstance(body.get("when"), list) or not body["when"]:
                out.append("%s: `%s.when` must be a non-empty list of patterns" % (label, key))
                continue
            found, var_types = _rules.pattern_problems("%s %s" % (label, key), _substituted(body["when"], params),
                                                       vocabulary, negation_ok=True)
            out += found
            for name in _params_in(body["when"]):
                if name not in params:
                    out.append("%s: $%s is used in `%s` but not declared in `params`" % (label, name, key))
            for name in _params_in(body["when"], references=True):
                if name not in params and name not in _bound_in(body["when"]):
                    out.append("%s: `where` refers to $%s, which `%s` neither declares nor binds" % (label, name, key))
            if key == "gaps" and not (body.get("say") or "").strip():
                out.append("%s: `gaps.say` must say, in words, why the answer is empty" % label)
            if key == "ask":
                bound = _bound_in(body["when"]) | set(params)
                var_types = dict(bound_params, **var_types)
                select = body.get("select")
                if not isinstance(select, list) or not select or not all(isinstance(s, str) for s in select):
                    out.append("%s: `ask.select` must be a non-empty list of variables" % label)
                    continue
                for item in select:
                    var, _dot, field = item.lstrip("$").partition(".")
                    if var not in bound:
                        out.append("%s: select %r names a variable `ask.when` does not bind" % (label, item))
                    elif field and field not in SELECT_FIELDS:
                        declared = {}
                        for kind_name in var_types.get(var, []):
                            declared.update(declared_attributes(vocabulary, kind_name))
                        if var_types.get(var) and declared and field not in declared:
                            out.append("%s: select %r: %s declares no attribute %r" % (label, item, "|".join(var_types[var]), field))
        for term in q.get("terms") or []:
            owner, _dot, attr = str(term).partition(".")
            if attr:
                if owner not in classes:
                    out.append("%s: term %r names a class that is not declared" % (label, term))
                elif attr not in declared_attributes(vocabulary, owner):
                    out.append("%s: term %r: %s declares no attribute %r" % (label, term, owner, attr))
            elif term not in classes and term not in properties:
                out.append("%s: term %r is neither a class nor a relation" % (label, term))
    return out


def terms_cited(questions, vocabulary):
    """{term: [question ids]} for every class, relation and attribute a question's patterns, parameters
    or `terms` list name. The terms nothing cites are what `oto ontology check` reports."""
    from ..model.vocabulary import declared_attributes
    out = {}

    def cite(term, qid):
        out.setdefault(term, [])
        if qid not in out[term]:
            out[term].append(qid)

    for qid, q in (questions or {}).items():
        if not isinstance(q, dict):
            continue
        var_types = {}
        for name, spec in (q.get("params") or {}).items():
            if isinstance(spec, dict) and spec.get("type"):
                for one in _kinds(spec["type"]):
                    cite(one, qid)
                var_types[name] = _kinds(spec["type"])
        def walk(patterns):
            for pattern in patterns:
                if isinstance(pattern, dict):
                    yield pattern
                    if isinstance(pattern.get("optional"), list):
                        yield from walk(pattern["optional"])

        for body in [q.get("ask")] + _gap_bodies(q):
            for pattern in walk((body or {}).get("when") or []):
                for kind_name in str(pattern.get("type") or "").split("|"):
                    if kind_name.strip():
                        cite(kind_name.strip(), qid)
                        if isinstance(pattern.get("node"), str):
                            var_types.setdefault(pattern["node"].lstrip("$"), []).append(kind_name.strip())
                for key in ("edge", "not_edge"):
                    spec = pattern.get(key)
                    if isinstance(spec, list) and len(spec) == 3:
                        for relation in str(spec[1] or "").split("|"):
                            if relation.strip() and relation.strip() != "*":
                                cite(relation.strip(), qid)
                for name in (pattern.get("where") or {}):
                    for kind_name in var_types.get(str(pattern.get("node") or "").lstrip("$"), []):
                        if name not in BUILTIN_FIELDS or name in declared_attributes(vocabulary, kind_name):
                            cite("%s.%s" % (kind_name, name), qid)
        for item in ((q.get("ask") or {}).get("select") or []):
            var, _dot, field = str(item).lstrip("$").partition(".")
            if field:
                for kind_name in var_types.get(var, []):
                    if field not in SELECT_FIELDS or field in declared_attributes(vocabulary, kind_name):
                        cite("%s.%s" % (kind_name, field), qid)
        for term in q.get("terms") or []:
            cite(str(term), qid)
    return out


def uncovered(questions, vocabulary):
    """The declared classes, relations and attributes no question cites, in declaration order."""
    cited = terms_cited(questions, vocabulary)
    out = [name for name in (vocabulary.get("classes") or {}) if name not in cited]
    out += [name for name in (vocabulary.get("properties") or {}) if name not in cited]
    for owner, declared in (vocabulary.get("attributes") or {}).items():
        out += ["%s.%s" % (owner, attr) for attr in (declared or {}) if "%s.%s" % (owner, attr) not in cited]
    return out


# ============================ running ============================

def _value(graph, nid, field):
    if field == "id":
        return nid
    return graph.attribute(nid, field)


def _rows(graph, found, select):
    """The selected values of every binding, each row once, in a stable order."""
    rows, seen = [], set()
    for bindings, _used in found:
        row = {}
        for item in select:
            var, _dot, field = item.lstrip("$").partition(".")
            nid = bindings.get(var)
            row[item] = None if nid is None else (_value(graph, nid, field) if field else nid)
        key = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
        if key not in seen:
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False, default=str))
    return rows


def _wording(text, graph, bindings):
    """The question with each $NAME replaced by the label of the entity bound to it."""
    def label(m):
        nid = bindings.get(m.group(1))
        if nid is None:
            return m.group(0)
        node = graph.nodes.get(nid) or {}
        return node.get("label") or nid
    return PARAM.sub(label, text or "")


def run(qid, question, params, nodes, edges, covers=None, derived_attributes=None, declared=None):
    """Run one question with its parameters bound: {id, question, who, status, gate, params, rows,
    gaps}. `params` maps NAME -> node id (every declared parameter must be bound; `survey` handles
    the free ones). `status` is answered | unanswered | violated | clean | empty. `declared` maps a
    class to the attribute names it declares (`declared_names`), so a declared `label` is the term."""
    graph = Graph(nodes, edges, derived_attributes, statuses=BELIEVED, covers=covers, declared=declared)
    bindings = dict(params or {})
    declared = question.get("params") or {}
    gate = question.get("gate", "non_empty")
    ask = question.get("ask") or {}
    found = matches(graph, _substituted(ask.get("when") or [], declared), bindings)
    rows = _rows(graph, found, ask.get("select") or [])
    status = STATUSES[(gate, bool(rows))]
    gaps = []
    if not rows or gate == "no_gaps":
        for body in _gap_bodies(question):
            hits = matches(graph, _substituted(body.get("when") or [], declared), bindings)
            if not hits:
                continue
            # one line per distinct binding, so a gap on a specific thing names it
            subjects = sorted({b.get(next(iter(b), None)) for b, _u in hits if b} - {None})
            say = _wording(body.get("say") or "", graph, bindings)
            gaps.append(say + (" (%s)" % ", ".join(graph.nodes[s].get("label") or s for s in subjects[:5] if s in graph.nodes)
                               if subjects and not declared else ""))
    if gate == "no_gaps" and gaps:
        status = "unanswered"
    return {"id": qid, "question": _wording(question.get("question"), graph, bindings),
            "who": question.get("who") or "", "status": status, "gate": gate,
            "params": {k: v for k, v in bindings.items() if k in declared}, "rows": rows, "gaps": gaps}


def declared_names(vocabulary):
    """{class: the attribute names it declares, inherited ones included}, for the matcher."""
    from ..model.vocabulary import declared_attributes
    return {kind: set(declared_attributes(vocabulary, kind)) for kind in (vocabulary.get("classes") or {})}


def survey(questions, nodes, edges, covers=None, derived_attributes=None, declared=None):
    """Every question over the whole graph: a parameterless question runs once; one with parameters
    runs for every entity of its first parameter's class (the others stay free) and reports how
    many of those it answers. Returns [{id, question, who, gate, status, answered, asked, gaps,
    unanswered}] in file order, where `status` summarises: answered when every run answered,
    unanswered when any required run did not, violated when an `empty` gate found rows, clean,
    empty, or `unasked` when a parameter has nothing to bind to."""
    graph = Graph(nodes, edges, derived_attributes, statuses=BELIEVED, covers=covers, declared=declared)
    out = []
    for qid, q in (questions or {}).items():
        if not isinstance(q, dict):
            continue
        declared = q.get("params") or {}
        gate = q.get("gate", "non_empty")
        entry = {"id": qid, "question": q.get("question") or "", "who": q.get("who") or "", "gate": gate,
                 "asked": 0, "answered": 0, "unanswered": [], "gaps": []}
        if not declared:
            result = run(qid, q, {}, nodes, edges, covers, derived_attributes, declared)
            entry["asked"] = 1
            entry["answered"] = 1 if (result["rows"] or (gate == "no_gaps" and result["status"] == "answered")) else 0
            entry["status"] = result["status"]
            entry["gaps"] = result["gaps"]
            out.append(entry)
            continue
        first = next(iter(declared))
        kinds = set()
        for one in _kinds(declared[first].get("type")):
            kinds |= set(graph.covers.get(one, {one}))
        subjects = [nid for nid in sorted(graph.nodes) if graph.nodes[nid].get("type") in kinds]
        if not subjects:
            entry["status"] = "unasked"
            entry["gaps"] = ["no %s in the graph to ask about" % (declared[first].get("type") or "").replace("|", " or ")]
            out.append(entry)
            continue
        statuses = []
        for nid in subjects:
            result = run(qid, q, {first: nid}, nodes, edges, covers, derived_attributes, declared)
            entry["asked"] += 1
            statuses.append(result["status"])
            if result["rows"]:
                entry["answered"] += 1
            if result["status"] in FINDING_STATUSES:
                entry["unanswered"].append({"node": nid, "label": graph.nodes[nid].get("label") or nid,
                                            "status": result["status"], "gaps": result["gaps"]})
        if any(s in FINDING_STATUSES for s in statuses):
            entry["status"] = "violated" if gate == "empty" else "unanswered"
        else:
            entry["status"] = STATUSES[(gate, entry["answered"] > 0)]
            if gate == "no_gaps":
                entry["answered"] = entry["asked"]
        out.append(entry)
    return out


def findings(questions, nodes, edges, covers=None, derived_attributes=None, declared=None):
    """The survey entries that are findings: required questions the graph cannot answer, and
    `empty` gates with rows. What `oto curate check` and `oto ontology check` report."""
    return [e for e in survey(questions, nodes, edges, covers, derived_attributes, declared) if e["status"] in FINDING_STATUSES]


# ============================ reading ============================

def _cell(value):
    if value is None:
        return "—"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def result_text(result, labels=None):
    """One answered question as text: the wording, the status, the rows, the gaps. `labels` maps a
    node id to a label, for ids in the rows."""
    labels = labels or {}
    lines = ["%s (%s): %s" % (result["id"], result["who"] or "anyone", result["question"]),
             "status: %s" % result["status"]]
    for row in result["rows"]:
        cells = []
        for key, value in row.items():
            shown = labels.get(value, value) if isinstance(value, str) and "." not in key else value
            cells.append("%s=%s" % (key, _cell(shown)) if len(row) > 1 else _cell(shown))
        lines.append("  " + "  ".join(cells))
    for gap in result["gaps"]:
        lines.append("  gap: %s" % gap)
    if not result["rows"] and not result["gaps"]:
        lines.append("  (no rows)")
    return "\n".join(lines)


def survey_text(entries):
    """The questions and whether the graph answers them, one line each, findings first by file order kept."""
    if not entries:
        return "no competency questions declared (questions.json absent or empty)"
    lines = []
    for e in entries:
        if e["gate"] == "empty":
            state = e["status"]
        elif e["asked"] > 1:
            state = "%s (%d of %d)" % (e["status"], e["answered"], e["asked"])
        else:
            state = e["status"]
        lines.append("%-6s %-22s %s  [%s]" % (e["id"], state, e["question"], e["who"] or "anyone"))
        for gap in e.get("gaps") or []:
            lines.append("         gap: %s" % gap)
        for item in (e.get("unanswered") or [])[:5]:
            lines.append("         %s: %s%s" % (item["status"], item["label"], ("; " + "; ".join(item["gaps"])) if item["gaps"] else ""))
        if len(e.get("unanswered") or []) > 5:
            lines.append("         ... %d more" % (len(e["unanswered"]) - 5))
    total = len(entries)
    bad = sum(1 for e in entries if e["status"] in FINDING_STATUSES)
    lines.append("%d question(s); %d the graph cannot answer as required" % (total, bad) if bad
                 else "%d question(s); the graph answers every one it must" % total)
    return "\n".join(lines)
