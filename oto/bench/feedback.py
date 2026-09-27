# -*- coding: utf-8 -*-
"""Feedback on answers, and the narrow path from a complaint to a gold question.

Someone reads an answer and says it is wrong. Without this module that judgement is lost, and the
same wrong answer comes back next week. With it, the complaint becomes a question the benchmark
runs forever, so the fix is verified and the regression is caught.

Two rules keep this from corrupting the thing it feeds.

A complaint is a claim, not a fact. The person may be wrong about the corpus, or right about the
world and wrong about what the documents say. So recording is cheap and promotion is deliberate:
`record` accepts anything, `promote` accepts only a complaint that states what the right answer was.
A complaint with no expected answer is a useful signal and an impossible test. It is refused.

Promotion damages provenance. A gold set written by independent people, plus one question promoted
from a team member's complaint, is a mixed set. Pretending otherwise inflates every number the set
produces afterwards. `promote` therefore rewrites `_meta` to the weaker of the two provenances and
records who was folded in. It never keeps the stronger label.
"""
import json
import os

#: What someone can say about an answer. "right" is recorded too: a confirmation is evidence, and a
#: question nobody ever complains about is the cheapest kind of passing test.
VERDICTS = ("wrong", "incomplete", "unsupported", "right")

#: Verdicts that can become a gold question. A confirmed-good answer needs no new test.
PROMOTABLE = ("wrong", "incomplete", "unsupported")

#: Provenance strength, weakest last. Promotion moves a set down this list, never up.
_STRENGTH = ("independent-human", "team-human", "mixed", "model", "unknown")

FEEDBACK_FILE = "feedback.jsonl"
PROMOTED_FILE = "feedback.promoted.json"


def path(project):
    """Next to the graph, never inside an indexed directory.

    `notes/` would be the obvious home and is the wrong one: it is indexed, so a complaint saying
    "the answer claimed X, the truth is Y" would become a retrievable passage and could be cited as
    a source. Feedback is about the corpus. It is not part of it.
    """
    return os.path.join(project.data, FEEDBACK_FILE)


def _promoted_path(project):
    return os.path.join(project.data, PROMOTED_FILE)


def record(project, question, verdict, by, at, given=None, expected=None,
           sources=None, note=None):
    """Append one piece of feedback. Returns the entry.

    `by` and `at` are required for the same reason they are on an assertion: feedback with no author
    cannot be weighed, and feedback with no date cannot be aged out.
    """
    if verdict not in VERDICTS:
        raise ValueError("verdict must be one of %s (got %r)" % (", ".join(VERDICTS), verdict))
    if not (question or "").strip():
        raise ValueError("no question: there is nothing to attach the feedback to")
    if not (by or "").strip():
        raise ValueError("no `by`: feedback with no author cannot be weighed against other feedback")
    if not (at or "").strip():
        raise ValueError("no `at`: feedback with no date cannot be aged out when the corpus moves on")

    entry = {
        "id": _next_id(project),
        "at": at,
        "by": by.strip(),
        "question": question.strip(),
        "verdict": verdict,
    }
    for key, value in (("given", given), ("expected", expected), ("note", note)):
        if (value or "").strip():
            entry[key] = value.strip()
    if sources:
        entry["sources"] = sorted(set(sources))

    with open(path(project), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def read(project):
    """Every entry, oldest first. Missing file means no feedback yet, not an error."""
    target = path(project)
    if not os.path.exists(target):
        return []
    entries = []
    with open(target, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                entry = json.loads(line)
            except ValueError as exc:
                raise ValueError("%s line %d is not valid JSON: %s" % (FEEDBACK_FILE, number, exc))
            entry["_line"] = number
            entries.append(entry)
    return entries


def _next_id(project):
    existing = read(project)
    return "fb-%04d" % (len(existing) + 1)


def promoted_ids(project):
    """Feedback ids already folded into a gold set."""
    target = _promoted_path(project)
    if not os.path.exists(target):
        return set()
    with open(target, encoding="utf-8") as f:
        return set(json.load(f).get("promoted", []))


def pending(project):
    """Promotable feedback that is not yet a gold question, and why each one cannot be."""
    done = promoted_ids(project)
    ready, blocked = [], []
    for entry in read(project):
        if entry["id"] in done or entry.get("verdict") not in PROMOTABLE:
            continue
        reason = _blocker(entry)
        (blocked if reason else ready).append((entry, reason) if reason else entry)
    return ready, blocked


def _blocker(entry):
    """Why this complaint cannot become a test, or None."""
    if not (entry.get("expected") or "").strip():
        return ("says the answer was %s but not what the right answer is; there is nothing to grade "
                "a fix against" % entry.get("verdict"))
    return None


def as_question(entry, kind="factual"):
    """One gold question from one complaint. Caller must have checked `_blocker` first."""
    question = {
        "id": "from-%s" % entry["id"],
        "question": entry["question"],
        "type": kind,
        "answer": entry["expected"],
        "provenance": "promoted from feedback %s by %s on %s"
                      % (entry["id"], entry["by"], entry["at"]),
    }
    if entry.get("sources"):
        question["supporting_sources"] = entry["sources"]
    return question


def weaken(meta, folded_in):
    """`_meta` after folding in questions from `folded_in` people.

    Two independent sets stay independent. Anything mixed with team feedback becomes mixed, and the
    audited fraction falls, because the promoted questions are unaudited by definition.
    """
    updated = dict(meta)
    was = updated.get("authored_by_kind", "unknown")
    now = "mixed" if was == "independent-human" else was
    if was in ("unknown",):
        now = "mixed"
    updated["authored_by_kind"] = now
    who = updated.get("authored_by", "").strip()
    added = ", ".join(sorted(set(folded_in)))
    updated["authored_by"] = ("%s + feedback from %s" % (who, added)) if who else added
    return updated


def rescale_audit(meta, kept, added):
    """The audited fraction after `added` unaudited questions join `kept` existing ones."""
    fraction = meta.get("audited_fraction")
    if not isinstance(fraction, (int, float)) or kept + added == 0:
        return meta
    updated = dict(meta)
    updated["audited_fraction"] = round((fraction * kept) / float(kept + added), 4)
    return updated


def promote(project, gold_path, ids=None, kind="factual"):
    """Fold ready feedback into a gold set.

    Returns (added, skipped, meta_before, meta_after, inherited_problems). `added` is a list of
    (feedback entry, gold question) pairs. `inherited_problems` are problems the set already had;
    they are reported, not treated as failures, because a half-written set must still be able to
    accept feedback. The write is a rename over a temporary file: a crash half-way leaves the old
    set intact.
    """
    from . import gold as _gold

    meta, questions = _gold.load(gold_path)
    ready, _ = pending(project)
    if ids is not None:
        wanted = set(ids)
        ready = [e for e in ready if e["id"] in wanted]

    taken = set(q.get("id") for q in questions)
    added, skipped = [], []
    for entry in ready:
        question = as_question(entry, kind=kind)
        if question["id"] in taken:
            skipped.append((entry, "gold set already has a question with id %r" % question["id"]))
            continue
        taken.add(question["id"])
        added.append((entry, question))

    if not added:
        return [], skipped, meta, meta, sorted(_gold.validate(meta, questions))

    updated = weaken(meta, [entry["by"] for entry, _ in added])
    updated = rescale_audit(updated, len(questions), len(added))

    fresh = [question for _, question in added]
    #: Only problems this promotion *introduces* may block it. A set can already have gaps someone
    #: is still filling in, and refusing to accept feedback until an unrelated line is fixed would
    #: make the whole loop unusable. Pre-existing problems are returned to the caller to report,
    #: not raised. Existing questions keep their line numbers because new ones are appended, so
    #: comparing the two problem lists is sound.
    was = set(_gold.validate(meta, questions))
    introduced = [p for p in _gold.validate(updated, questions + fresh) if p not in was]
    if introduced:
        raise ValueError("promotion would introduce %d problem(s), nothing written:\n  - "
                         % len(introduced) + "\n  - ".join(introduced))
    inherited = sorted(was)

    temporary = gold_path + ".promoting"
    with open(temporary, "w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": updated}, ensure_ascii=False, sort_keys=True) + "\n")
        for question in questions + fresh:
            payload = dict(question)
            payload.pop("_line", None)
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, gold_path)

    done = promoted_ids(project) | set(entry["id"] for entry, _ in added)
    with open(_promoted_path(project), "w", encoding="utf-8") as f:
        json.dump({"promoted": sorted(done)}, f, indent=2, sort_keys=True)
        f.write("\n")
    return added, skipped, meta, updated, inherited
