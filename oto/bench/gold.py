# -*- coding: utf-8 -*-
"""The gold question set, and honesty about where it came from.

A gold set is the only thing standing between "it works great for me" and evidence. Its weakest point
is almost never the questions; it is who wrote them. Someone who built the graph writes questions the
graph can answer, without meaning to, and the resulting number is meaningless while looking rigorous.

So the file carries its own provenance, and every report prints it. A run cannot produce a number
without saying how the questions were authored and whether anyone independent checked them. That is
the difference between "0.87 F1" and "0.87 F1 on a model-authored set, 15% human-audited, from the
same team that built the graph".

Format: JSON Lines. The first object carries `_meta`; the rest are questions. Lines starting with //
are ignored, so a set can be annotated.
"""
import json
import os

AUTHOR_KINDS = ("independent-human", "team-human", "model", "mixed", "unknown")

REQUIRED = ("id", "question")
#: Question kinds. The temporal ones are separated because they test different things: whether the
#: system knows what is true NOW, what was true on a date, and whether something changed. A system can
#: pass the first and fail the other two, which is exactly the failure a time-blind baseline has.
QUESTION_TYPES = (
    "factual",           # a fact the corpus states
    "temporal",          # is the current status right?
    "temporal_asof",     # what was true on a given date?
    "temporal_change",   # did this change, and when?
    "citation",          # is the answer grounded in the right source?
    "paraphrase",        # worded differently from the source, which is where dense retrieval wins
    "aggregate",         # a count or a roll-up
    "negative",          # the corpus does NOT say this; the right answer is "absent"
    "multi-hop",         # needs more than one traversal
)


def _iter_lines(path):
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            yield number, line


def load(path):
    """Return (meta, questions). Raises ValueError on unparseable JSON, naming the line."""
    meta, questions = {}, []
    for number, line in _iter_lines(path):
        try:
            payload = json.loads(line)
        except ValueError as exc:
            raise ValueError("line %d is not valid JSON: %s" % (number, exc))
        if "_meta" in payload:
            meta = payload["_meta"]
            continue
        payload["_line"] = number
        questions.append(payload)
    return meta, questions


def validate(meta, questions):
    """Problems with a gold set. Empty means usable."""
    problems = []

    if not meta:
        problems.append("no `_meta` line: a set with no recorded provenance cannot support a claim")
    else:
        kind = meta.get("authored_by_kind")
        if kind not in AUTHOR_KINDS:
            problems.append("_meta.authored_by_kind must be one of %s (got %r)"
                            % (", ".join(AUTHOR_KINDS), kind))
        if not (meta.get("authored_by") or "").strip():
            problems.append("_meta.authored_by is empty: say who wrote the questions")
        if kind in ("model", "team-human", "mixed"):
            audited = meta.get("audited_fraction")
            if not isinstance(audited, (int, float)) or not 0 <= audited <= 1:
                problems.append("_meta.audited_fraction must be a number from 0 to 1 for a %r set: "
                                "how much of it did a human check?" % kind)
            elif audited > 0 and not (meta.get("audited_by") or "").strip():
                problems.append("_meta.audited_by is empty but audited_fraction is %s" % audited)

    if not questions:
        problems.append("no questions")

    seen = set()
    for question in questions:
        where = "line %s" % question.get("_line")
        for field in REQUIRED:
            if not question.get(field):
                problems.append("%s has no %s" % (where, field))
        qid = question.get("id")
        if qid in seen:
            problems.append("%s repeats id %r" % (where, qid))
        seen.add(qid)
        kind = question.get("type")
        if kind and kind not in QUESTION_TYPES:
            problems.append("%s has unknown type %r (expected one of %s)"
                            % (where, kind, ", ".join(QUESTION_TYPES)))
        if kind and kind.startswith("temporal") and not question.get("expected_status"):
            problems.append("%s is a %s question but declares no expected_status: there is nothing "
                            "to grade the time-awareness against" % (where, kind))
        if kind == "temporal_asof" and not question.get("as_of"):
            problems.append("%s asks about a point in time but gives no as_of date" % where)
        if not (question.get("supporting_sources") or question.get("expected_entities")
                or question.get("expected_status") or question.get("answer")):
            problems.append("%s has nothing to grade against: give it supporting_sources, "
                            "expected_entities, expected_status or an answer" % where)
    return problems


def describe(meta):
    """One honest paragraph about the set's provenance, for the top of every report."""
    if not meta:
        return ("PROVENANCE UNKNOWN. This set records nothing about who wrote it, so no number from "
                "it should be quoted.")
    kind = meta.get("authored_by_kind", "unknown")
    who = meta.get("authored_by", "unrecorded")
    audited = meta.get("audited_fraction")
    lines = ["Questions authored by: %s (%s)" % (who, kind)]
    if kind == "independent-human":
        lines.append("Independent of the team that built the graph.")
    elif kind == "model":
        lines.append("MODEL-AUTHORED. A model does not remove author-as-evaluator bias if the same "
                     "model family authored the graph; it removes human effort. Treat this as an "
                     "internal measurement, not a published claim.")
    elif kind == "team-human":
        lines.append("Written by the team that built the graph. Author-as-evaluator bias is the top "
                     "credibility risk here.")
    elif kind == "mixed":
        lines.append("MIXED provenance. Some questions came from a different source than the rest, "
                     "usually feedback promoted after someone read an answer. Those questions are "
                     "not independent of the system: they exist because the system got them wrong. "
                     "They are the right regression tests and the wrong basis for a headline score.")
    if isinstance(audited, (int, float)):
        if audited > 0:
            lines.append("Human-audited: %.0f%% by %s." % (audited * 100,
                                                           meta.get("audited_by") or "unrecorded"))
        else:
            lines.append("NOT human-audited.")
    if meta.get("notes"):
        lines.append(str(meta["notes"]))
    return "\n".join(lines)


STARTER = '''// Gold question set. JSON Lines. Lines starting with // are ignored.
// The first object records where the questions came from. Every report prints it, because a number
// without that context is not evidence.
{"_meta": {"authored_by": "", "authored_by_kind": "unknown", "audited_fraction": 0, "audited_by": "", "notes": ""}}
// One object per question. Give each something to grade against.
{"id": "q_example_factual", "type": "factual", "question": "", "expected_entities": [], "supporting_sources": []}
{"id": "q_example_temporal", "type": "temporal", "question": "", "expected_status": "current", "as_of": ""}
// A paraphrase question uses words the source does NOT use. Without these, a dense baseline looks
// artificially weak and the comparison is worthless.
{"id": "q_example_paraphrase", "type": "paraphrase", "question": "", "expected_entities": []}
'''


def append(path, questions, source_doc=None, kind="factual"):
    """Add questions to an existing set. Returns (added, problems); writes only when clean.

    Each question gets an id from the document it came from when it has none, and that document as
    its supporting source. Validation runs over the whole set, and only the problems the new
    questions introduce are reported, so an old problem does not block a new document.
    """
    meta, existing = load(path)
    before = set(validate(meta, existing))
    ids = {q.get("id") for q in existing}
    added = []
    for number, raw in enumerate(questions, 1):
        question = dict(raw)
        question.setdefault("type", kind)
        if source_doc:
            question.setdefault("source_doc", source_doc)
            question.setdefault("supporting_sources", [source_doc])
        if not question.get("id"):
            base = "%s-%d" % (source_doc or "q", number)
            candidate, n = base, 1
            while candidate in ids:
                n += 1
                candidate = "%s-%d" % (base, n)
            question["id"] = candidate
        ids.add(question["id"])
        added.append(question)
    combined = existing + [dict(q, _line="new %d" % (i + 1)) for i, q in enumerate(added)]
    problems = [p for p in validate(meta, combined) if p not in before]
    if problems:
        return added, problems
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for question in added:
            f.write(json.dumps(question, ensure_ascii=False, sort_keys=True) + "\n")
    return added, []


def write_starter(path):
    if os.path.exists(path):
        raise FileExistsError(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(STARTER)
    return path
