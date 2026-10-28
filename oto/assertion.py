# -*- coding: utf-8 -*-
"""A named person's assertion, written through the gates: the engine's one path for a change a
command makes on someone's word (`oto decide`, `oto work set`, a graph describing itself).

`commit` records the text as an assertion (curate/assertions.py), lets the caller append what cites
it to a candidate, holds the candidate to the same gates as any change (the diff's checks, the
vocabulary's shapes, the ontology's blocking policies, and the composed packs' write hooks before
anything is written) and applies it; nothing refused is written, and both outcomes go to the audit
log keyed to the nodes touched. `identity` is who speaks when the person does not say: the git
`user.name <user.email>` in the project. `gates` is what `oto curate check` would find blocking.
This was the work pack's machinery until ADR-0006 step 5 named it the engine's.
"""
import os

from . import audit as _audit
from .curate import assertions as _assertions, diff as _diff, ledger as _ledger, session as _session
from .model.vocabulary import covers as _covers
from .project import ProjectError
from .reason import engine as _engine, rules as _rules, shapes as _shapes
from .reason.questions import declared_names


class WriteError(ProjectError):
    """A refusal, in words the person can act on."""


def _load_vocabulary(project):
    import json
    with open(project.ontology_config_path, encoding="utf-8") as f:
        return json.load(f)


def identity(project):
    """Who is speaking, from git when the person does not say: `user.name <user.email>`."""
    from . import gitx
    root = os.path.dirname(project.src)
    try:
        name = gitx.run(["config", "user.name"], cwd=root).strip()
        email = gitx.run(["config", "user.email"], cwd=root).strip()
    except ProjectError:
        return None
    if not (name or email):
        return None
    return ("%s <%s>" % (name, email)) if name and email else (name or email)


def no_candidate(project):
    if _session.exists(project):
        raise WriteError("a curate candidate is open (%s): apply or abort it first, so this change is not mixed into it"
                        % os.path.basename(_session.candidate_path(project)))


def commit(project, text, by, at, about, edit, action="work"):
    """Record `text` as an assertion by `by`, let `edit(candidate, source)` append what cites it,
    hold the candidate to the gates and apply it. Returns what `edit` returned. Nothing refused is
    written: a refusal aborts the candidate, and the assertion stands as what was said. Both
    outcomes go to the audit log (audit.py), keyed to the nodes touched."""
    no_candidate(project)
    from . import extensions as _extensions
    try:
        under = _extensions.before_write(project, action, by)        # the composed packs' write hooks: the policy snapshot re-checked (roadmap E6)
    except ProjectError as exc:
        raise WriteError(str(exc))
    vocabulary = _load_vocabulary(project)
    live = _session.live(project)
    entry = _assertions.record(project, text=text, by=by.strip(), at=at, about=about)
    candidate_path = _session.start(project)
    try:
        candidate = _session.candidate(project)
        done = edit(candidate, {"source_type": _assertions.HUMAN_ASSERTION, "sources": [_assertions.reference(entry["id"])],
                                "source_doc": _assertions.reference(entry["id"]), "as_of": at, "valid_from": at,
                                "status": "current", "aliases": [], "tags": []})
        problems = gates(project, live, candidate, vocabulary)
        if problems:
            refusal = WriteError("refused by the gates:\n  - " + "\n  - ".join("%s: %s" % (f.subject, f.detail) for f in problems[:10]))
            _audit.append(project, action, by, about, "refused", detail=str(refusal).splitlines()[1].strip(" -") if "\n" in str(refusal) else str(refusal))
            raise refusal
        _session._write(candidate_path, candidate)
    except Exception:
        _session.abort(project)
        raise
    summary = _diff.summarize(live, candidate)
    record = _ledger.entry(summary, _ledger.retirements(live, candidate), by=by.strip(), note="oto %s: %s" % (action, text),
                           sources=_ledger.new_sources(live, candidate))
    _session.apply(project)
    _ledger.append(project, record)
    done["assertion"] = entry["id"]
    touched = list(about) + list(summary.get("nodes_added") or []) + [nid for nid, _f in summary.get("nodes_changed") or []]
    _audit.append(project, action, by, touched, "applied", detail=text + ((" [%s]" % under) if under else ""))
    return done


def gates(project, live, candidate, vocabulary):
    """The blocking findings the candidate would meet at `oto curate check`: the diff's checks, the
    declared shapes, the ontology's blocking policies."""
    findings = [f for f in _diff.check(live, candidate, vocabulary, known_assertions=_assertions.known_ids(project))
                if f.severity == _diff.Finding.BLOCKING]
    nodes, edges = candidate.get("nodes") or [], candidate.get("edges") or []
    for item in _shapes.findings(vocabulary, nodes, edges):
        findings.append(_diff.Finding(_diff.Finding.BLOCKING, item["node"], "shape %s: %s" % (item["kind"], item["message"])))
    rules = _rules.load(project)
    if rules and not _rules.problems(rules, vocabulary):
        try:
            outcome = _engine.run(rules, nodes, edges, covers=_covers(vocabulary.get("classes") or {}), declared=declared_names(vocabulary))
        except _engine.DoesNotConverge as exc:
            findings.append(_diff.Finding(_diff.Finding.BLOCKING, "rules", str(exc)))
        else:
            findings += [_diff.Finding(_diff.Finding.BLOCKING, f.get("node") or "(graph)", "policy %s: %s" % (f["rule"], f["message"]))
                         for f in outcome["findings"] if f["severity"] == "blocking"]
    return findings
