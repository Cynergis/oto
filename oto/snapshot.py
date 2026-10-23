# -*- coding: utf-8 -*-
"""The project snapshot: everything the workbench shows about where a project is, in one object.

The workbench is read-only. It never reads a project's files itself: the engine writes this object,
and every surface renders it, so they cannot disagree. It is served live in `/api/status` (key
`snapshot`), printed by `oto status --snapshot`, and its `token` moves whenever anything in it does,
so an open page knows when to reload. Nothing in it comes from a model or the clock: the same
project gives the same snapshot.

    snapshot    the contract's version (SNAPSHOT); a reader refuses a version it does not know
    token       a short hash of the rest
    project     {name, slug}
    overview    {facts, documents, conversations, questions: {declared, answered}}
    stations    [{id, title, state, line}], in the order work moves; state is one of STATES
    sources     {inbox, processing, errors: [{file, reason, run}], documents: [{slug, title}], open_runs}
    survey      {accepted, rejected, latest: [{term, verdict, as, by, at, note}]}
    vocabulary  {accepted, version, classes: [{name, definition, things, why, validated_by}],
                 relations, attributes, questions: [{id, who, question, answered}], parts: [{name, release, origin}]}
    curate      {candidate, assertions, reattest,
                 changes: [{at, by, note, sources, added, retired: [{id, superseded_by, valid_to, change_note}]}]}
    build       {built, stale, facts, current, superseded, links}
    rules       {rules: [{id, kind, severity, why, validated_by}], findings: [{rule, node, label, severity, message}]}
    test        {gold: {questions, authored_by, audited_fraction}, bench: {at, systems} or None,
                 feedback: [{id, verdict, question, by, at, expected}]}
    deploy      {backend, targets, site}
    open        [{station, what, detail}]: what waits on a person, in plain words

Words in `line`, `what` and `detail` are for a reader, not an operator: no commands, no file names
beyond a document's own.
"""
import hashlib
import json
import os

SNAPSHOT = 1
STATES = ("done", "attention", "not_started")
STATIONS = (("sources", "Sources"), ("survey", "Survey"), ("vocabulary", "Vocabulary"), ("curate", "Curate"),
            ("build", "Build"), ("rules", "Rules"), ("test", "Test"), ("deploy", "Deploy"))
CHANGES_SHOWN = 20
BENCH_FILE = os.path.join("bench", "latest.json")


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _files(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(n for n in os.listdir(directory) if not n.startswith(".") and os.path.isfile(os.path.join(directory, n)))


def _title(path, fallback):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return fallback


def _sources(project):
    from .intake import pipeline as _pipeline
    layout = project.layout
    errors = []
    if os.path.isdir(layout.errors):
        for run in sorted(os.listdir(layout.errors)):
            for name in _files(os.path.join(layout.errors, run)):
                if name.endswith(_pipeline.ERROR_SUFFIX):
                    record = _read_json(os.path.join(layout.errors, run, name), {}) or {}
                    errors.append({"file": record.get("file") or name[:-len(_pipeline.ERROR_SUFFIX)],
                                   "reason": record.get("reason") or record.get("outcome"), "run": run})
    # A run is open while one of its files still waits in processing/. The pipeline's own list also
    # keeps a run whose files a later run re-extracted and archived; that one waits on nothing.
    waiting = set(_files(layout.processing))
    open_runs = [m["run_id"] for m in _pipeline.open_runs(project)
                 if any(e.get("file") in waiting for e in m.get("files") or [] if e.get("outcome") == _pipeline.EXTRACTED)]
    documents = [{"slug": n[:-3], "title": _title(os.path.join(layout.corpus, n), n[:-3])}
                 for n in _files(layout.corpus) if n.endswith(".md")]
    return {"inbox": _files(layout.inbox), "processing": _files(layout.processing), "errors": errors,
            "documents": documents, "open_runs": open_runs}


def _survey(project):
    from .intake import decisions as _decisions
    latest = _decisions.latest(project)
    verdicts = [e["verdict"] for e in latest.values()]
    shown = sorted(latest.values(), key=lambda e: (e.get("at") or "", e.get("term") or ""), reverse=True)
    return {"accepted": verdicts.count("accepted"), "rejected": verdicts.count("rejected"),
            "latest": [{k: e.get(k) for k in ("term", "verdict", "as", "by", "at", "note")} for e in shown[:CHANGES_SHOWN]]}


def _vocabulary(project, vocabulary, graph, answered):
    from .model import rationale as _rationale
    from .reason import questions as _questions
    rationale = _rationale.load(project) if os.path.exists(_rationale.path_for(project)) else {}
    reasons = (rationale or {}).get("classes") or {}
    things = {}
    for node in graph.get("nodes") or []:
        if node.get("status", "current") == "current":
            things[node.get("type")] = things.get(node.get("type"), 0) + 1
    classes = [{"name": name, "definition": (spec or {}).get("definition"), "things": things.get(name, 0),
                "why": (reasons.get(name) or {}).get("why"), "validated_by": (reasons.get(name) or {}).get("validated_by") or None}
               for name, spec in sorted((vocabulary.get("classes") or {}).items())]
    declared = _questions.load(project) or {}
    questions = [{"id": qid, "who": q.get("who"), "question": q.get("question"), "answered": qid in answered}
                 for qid, q in sorted(declared.items())]
    lock = _read_json(os.path.join(project.data, "ontology.lock.json"))
    parts = [{"name": name, "release": None, "origin": "imported"} for name in sorted((vocabulary.get("namespaces") or {}))]
    record = (project.config().get("ontology") or project.config().get("template"))
    if isinstance(record, dict) and record.get("name") and record["name"] not in [p["name"] for p in parts]:
        parts.insert(0, {"name": record["name"], "release": record.get("release"), "origin": record.get("origin")})
    if not parts:
        parts = [{"name": project.config().get("slug"), "release": None, "origin": "the project's own"}]
    return {"accepted": lock is not None, "version": (lock or {}).get("ontology_version") or vocabulary.get("ontology_version"),
            "classes": classes, "relations": len(vocabulary.get("properties") or {}),
            "attributes": sum(len(v or {}) for v in (vocabulary.get("attributes") or {}).values()),
            "questions": questions, "parts": parts}


def _curate(project, graph):
    from .curate import assertions as _assertions, ledger as _ledger, reattest as _reattest, session as _session
    changes = [{"at": e.get("at"), "by": e.get("by"), "note": e.get("note"), "sources": e.get("sources") or [],
                "added": (e.get("nodes") or {}).get("added", 0),
                "retired": [{k: r.get(k) for k in ("id", "superseded_by", "valid_to", "change_note")}
                            for r in e.get("retired") or [] if isinstance(r, dict)]}
               for e in reversed(_ledger.read(project))]
    return {"candidate": _session.exists(project), "assertions": len(_assertions.read(project)),
            "reattest": len(_reattest.pending(project, graph)), "changes": changes[:CHANGES_SHOWN]}


def _rules(project, vocabulary, graph):
    from .model.vocabulary import covers as _covers
    from .reason import engine as _engine, rules as _rules_mod
    from .reason.questions import declared_names
    rules = _rules_mod.load(project) or []
    listed = [{"id": r.get("id"), "kind": r.get("kind"), "severity": r.get("severity"), "why": r.get("why"),
               "validated_by": r.get("validated_by") or None} for r in rules if isinstance(r, dict)]
    findings = []
    if rules and not _rules_mod.problems(rules, vocabulary):
        try:
            outcome = _engine.run(rules, graph.get("nodes") or [], graph.get("edges") or [],
                                  covers=_covers(vocabulary.get("classes") or {}), declared=declared_names(vocabulary))
        except _engine.DoesNotConverge:
            outcome = {"findings": []}
        labels = {n.get("id"): n.get("label") for n in graph.get("nodes") or []}
        findings = [{"rule": f["rule"], "node": f.get("node"), "label": labels.get(f.get("node")),
                     "severity": f["severity"], "message": f["message"]} for f in outcome["findings"]]
    return {"rules": listed, "findings": findings}


def _test(project):
    from .bench import feedback as _feedback, gold as _gold
    gold = None
    path = os.path.join(project.data, "gold", "questions.jsonl")
    if os.path.exists(path):
        try:
            meta, questions = _gold.load(path)
            gold = {"questions": len(questions), "authored_by": meta.get("authored_by"),
                    "audited_fraction": meta.get("audited_fraction")}
        except ValueError:
            gold = {"questions": 0, "authored_by": None, "audited_fraction": None}
    try:
        entries = _feedback.read(project)
    except ValueError:
        entries = []
    promoted = set(_feedback.promoted_ids(project))
    feedback = [{"id": e.get("id"), "verdict": e.get("verdict"), "question": e.get("question"), "by": e.get("by"),
                 "at": e.get("at"), "expected": e.get("expected"), "promoted": e.get("id") in promoted} for e in entries]
    bench = _read_json(os.path.join(project.src, BENCH_FILE))
    return {"gold": gold, "bench": {"at": bench.get("at"), "systems": bench.get("systems")} if bench else None,
            "feedback": feedback}


def _questions_answered(project, vocabulary, graph):
    from .model.vocabulary import covers as _covers
    from .reason import questions as _questions
    declared = _questions.load(project) or {}
    if not declared or _questions.problems(declared, vocabulary):
        return set()
    entries = _questions.survey(declared, graph.get("nodes") or [], graph.get("edges") or [],
                                _covers(vocabulary.get("classes") or {}), declared=_questions.declared_names(vocabulary))
    return {e["id"] for e in entries if e["status"] not in _questions.FINDING_STATUSES}


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _stations(s):
    src, voc, cur, bld, rul, tst, dep = (s["sources"], s["vocabulary"], s["curate"], s["build"], s["rules"], s["test"], s["deploy"])
    confirmed = len([c for c in voc["classes"] if c["validated_by"]])
    waiting = len(src["errors"]) + len(src["inbox"])
    out = {
        "sources": ("attention" if waiting else "done" if src["documents"] else "not_started",
                    "%s%s" % (_plural(len(src["documents"]), "document"), " · %d waiting" % waiting if waiting else "")),
        "survey": ("done" if s["survey"]["accepted"] + s["survey"]["rejected"] else "not_started",
                   "%d accepted · %d rejected" % (s["survey"]["accepted"], s["survey"]["rejected"])),
        "vocabulary": ("not_started" if not voc["classes"] else "attention" if not voc["accepted"] or confirmed < len(voc["classes"]) else "done",
                       ("v%s · " % voc["version"] if voc["accepted"] else "not accepted · ")
                       + "%d of %d confirmed" % (confirmed, len(voc["classes"]))),
        "curate": ("attention" if cur["candidate"] or cur["reattest"] else "done" if cur["changes"] else "not_started",
                   "a change is open" if cur["candidate"] else _plural(len(cur["changes"]), "change") + " applied"),
        "build": ("not_started" if not bld["built"] else "attention" if bld["stale"] else "done",
                  "%s · %s" % (_plural(bld["current"], "fact"), _plural(bld["links"], "link")) if bld["built"] else "not built"),
        "rules": ("not_started" if not rul["rules"] else "attention" if rul["findings"] or any(not r["validated_by"] for r in rul["rules"]) else "done",
                  "%s · %s" % (_plural(len(rul["rules"]), "rule"), _plural(len(rul["findings"]), "warning")) if rul["rules"] else "no rules"),
        "test": ("not_started" if not tst["gold"] else "attention" if not tst["bench"] or any(f["verdict"] != "right" and not f["promoted"] and not f["expected"] for f in tst["feedback"]) else "done",
                 ("%s" % _plural(tst["gold"]["questions"], "gold question")) if tst["gold"] else "no gold set"),
        "deploy": ("done" if dep["site"] else "not_started", "site built" if dep["site"] else "site not built"),
    }
    return [{"id": sid, "title": title, "state": out[sid][0], "line": out[sid][1]} for sid, title in STATIONS]


def _open(s):
    out = []
    for e in s["sources"]["errors"]:
        out.append({"station": "sources", "what": "%s could not be read" % e["file"], "detail": e["reason"]})
    if s["sources"]["inbox"]:
        out.append({"station": "sources", "what": "%s waiting in the inbox" % _plural(len(s["sources"]["inbox"]), "document"), "detail": None})
    voc = s["vocabulary"]
    if voc["classes"] and not voc["accepted"]:
        out.append({"station": "vocabulary", "what": "The vocabulary is not accepted yet", "detail": None})
    unconfirmed = [c["name"] for c in voc["classes"] if not c["validated_by"]]
    if unconfirmed:
        out.append({"station": "vocabulary", "what": "%d of %d kinds of thing are unconfirmed" % (len(unconfirmed), len(voc["classes"])),
                    "detail": "Waiting for someone who knows the domain."})
    unanswered = [q["id"] for q in voc["questions"] if not q["answered"]]
    if unanswered:
        out.append({"station": "vocabulary", "what": "%s not answered yet" % _plural(len(unanswered), "question"), "detail": ", ".join(unanswered)})
    if s["curate"]["candidate"]:
        out.append({"station": "curate", "what": "A change is open and not applied", "detail": None})
    if s["curate"]["reattest"]:
        out.append({"station": "curate", "what": "%s cite an old version of a document" % _plural(s["curate"]["reattest"], "fact"), "detail": None})
    if s["build"]["stale"]:
        out.append({"station": "build", "what": "The build is older than the graph", "detail": None})
    unvalidated = [r["id"] for r in s["rules"]["rules"] if not r["validated_by"]]
    if unvalidated:
        out.append({"station": "rules", "what": "%s nobody has confirmed" % _plural(len(unvalidated), "rule"), "detail": None})
    for f in s["test"]["feedback"]:
        if f["verdict"] != "right" and not f["promoted"] and not f["expected"]:
            out.append({"station": "test", "what": f["question"], "detail": "%s said the answer was %s; the right answer is not known yet." % (f["by"], f["verdict"])})
    gold = s["test"]["gold"]
    if gold and not gold.get("audited_fraction"):
        out.append({"station": "test", "what": "Nobody has audited the gold questions", "detail": "Written by %s." % (gold.get("authored_by") or "an unknown author")})
    return out


def build(project):
    """The snapshot of a project, as a dict."""
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    graph = _read_json(project.graph_path, {"nodes": [], "edges": []}) or {"nodes": [], "edges": []}
    nodes = graph.get("nodes") or []
    current = [n for n in nodes if n.get("status", "current") == "current"]
    database = project.layout.database
    corpus_files = [os.path.join(project.layout.corpus, n) for n in _files(project.layout.corpus)]
    newest_input = max([os.path.getmtime(p) for p in [project.graph_path, project.ontology_config_path] + corpus_files
                        if os.path.exists(p)] or [0])
    built = os.path.exists(database)
    answered = _questions_answered(project, vocabulary, graph)
    cfg = project.config()

    s = {"snapshot": SNAPSHOT, "project": {"name": cfg.get("name"), "slug": cfg.get("slug")}}
    s["sources"] = _sources(project)
    s["survey"] = _survey(project)
    s["vocabulary"] = _vocabulary(project, vocabulary, graph, answered)
    s["curate"] = _curate(project, graph)
    s["build"] = {"built": built, "stale": bool(built and os.path.getmtime(database) < newest_input),
                  "facts": len(nodes), "current": len(current), "superseded": len(nodes) - len(current),
                  "links": len(graph.get("edges") or [])}
    s["rules"] = _rules(project, vocabulary, graph)
    s["test"] = _test(project)
    s["deploy"] = {"backend": ((cfg.get("serve") or {}).get("backend") or "sqlite"), "targets": cfg.get("targets") or [],
                   "site": os.path.exists(os.path.join(project.src, "site", "index.html"))}
    captured = len([d for d in s["sources"]["documents"] if _captured(project, d["slug"])])
    s["overview"] = {"facts": len(current), "documents": len(s["sources"]["documents"]) - captured,
                     "conversations": captured + s["curate"]["assertions"],
                     "questions": {"declared": len(s["vocabulary"]["questions"]), "answered": len(answered)}}
    s["stations"] = _stations(s)
    s["open"] = _open(s)
    s["token"] = token(s)
    return s


def _captured(project, slug):
    from .intake.survey import PROVENANCE_LINE
    try:
        with open(os.path.join(project.layout.corpus, slug + ".md"), encoding="utf-8", errors="replace") as f:
            return any(PROVENANCE_LINE.match(line) and "Captured" in line for line in f.read(2000).splitlines())
    except OSError:
        return False


def token(s):
    body = json.dumps({k: v for k, v in s.items() if k != "token"}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def for_root(root):
    """The snapshot of the project at `root`, or None when there is none."""
    from .project import Project
    if not root or not os.path.exists(os.path.join(root, "ontology.config.json")):
        return None
    return build(Project.standard(root))
