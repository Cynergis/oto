# -*- coding: utf-8 -*-
"""Feedback capture, and the guards on the path from a complaint to a gold question."""
import json
import os

import pytest

from oto.bench import feedback as fb


class _Project(object):
    """Only the two attributes the module reads."""

    def __init__(self, data):
        self.data = data


@pytest.fixture
def project(tmp_path):
    return _Project(str(tmp_path))


@pytest.fixture
def gold(tmp_path):
    path = tmp_path / "questions.jsonl"
    meta = {"authored_by": "external reviewers", "authored_by_kind": "independent-human",
            "audited_fraction": 1.0, "audited_by": "external reviewers"}
    lines = [json.dumps({"_meta": meta}, sort_keys=True)]
    for n in (1, 2, 3):
        lines.append(json.dumps({"id": "q%d" % n, "question": "question %d?" % n,
                                 "answer": "answer %d" % n}, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# ---- recording ----

def test_record_requires_author_and_date(project):
    with pytest.raises(ValueError) as exc:
        fb.record(project, "a question?", "wrong", by="", at="2026-08-25")
    assert "by" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        fb.record(project, "a question?", "wrong", by="someone", at="")
    assert "at" in str(exc.value)


def test_record_rejects_an_unknown_verdict(project):
    with pytest.raises(ValueError):
        fb.record(project, "a question?", "badly-worded", by="someone", at="2026-08-25")


def test_ids_are_sequential_and_the_log_is_append_only(project):
    first = fb.record(project, "one?", "wrong", by="a", at="2026-08-25", expected="x")
    second = fb.record(project, "two?", "right", by="b", at="2026-08-26")
    assert (first["id"], second["id"]) == ("fb-0001", "fb-0002")
    lines = open(fb.path(project), encoding="utf-8").read().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["question"] == "one?"


def test_the_log_never_lands_in_an_indexed_directory(project):
    """A complaint must not become a retrievable passage. It is about the corpus, not part of it."""
    fb.record(project, "one?", "wrong", by="a", at="2026-08-25")
    assert os.path.basename(os.path.dirname(fb.path(project))) != "notes"
    assert "notes" not in fb.path(project).split(os.sep)


def test_read_of_a_missing_log_is_empty_not_an_error(project):
    assert fb.read(project) == []


# ---- what can become a test ----

def test_a_complaint_with_no_expected_answer_is_blocked(project):
    fb.record(project, "who owns it?", "wrong", by="a", at="2026-08-25", given="nobody")
    ready, blocked = fb.pending(project)
    assert ready == []
    assert len(blocked) == 1
    assert "nothing to grade" in blocked[0][1]


def test_a_confirmation_is_recorded_but_never_promoted(project):
    fb.record(project, "is this right?", "right", by="a", at="2026-08-25", expected="yes")
    ready, blocked = fb.pending(project)
    assert (ready, blocked) == ([], [])
    assert len(fb.read(project)) == 1


# ---- promotion ----

def test_promotion_weakens_provenance_and_rescales_the_audit(project, gold):
    fb.record(project, "retention?", "wrong", by="teammate", at="2026-08-25",
              expected="ten years", sources=["documents/policy.md"])
    added, skipped, before, after, inherited = fb.promote(project, gold)
    assert len(added) == 1
    assert before["authored_by_kind"] == "independent-human"
    assert after["authored_by_kind"] == "mixed"
    assert after["audited_fraction"] == 0.75
    assert "teammate" in after["authored_by"]
    assert inherited == []


def test_a_promoted_question_carries_its_origin(project, gold):
    fb.record(project, "retention?", "wrong", by="teammate", at="2026-08-25", expected="ten years")
    added, _, _, _, _ = fb.promote(project, gold)
    entry, question = added[0]
    assert question["id"] == "from-%s" % entry["id"]
    assert question["answer"] == "ten years"
    assert "teammate" in question["provenance"]
    assert "2026-08-25" in question["provenance"]


def test_promotion_is_idempotent(project, gold):
    fb.record(project, "retention?", "wrong", by="teammate", at="2026-08-25", expected="ten years")
    fb.promote(project, gold)
    lines = len(open(gold, encoding="utf-8").read().strip().split("\n"))
    added, _, _, _, _ = fb.promote(project, gold)
    assert added == []
    assert len(open(gold, encoding="utf-8").read().strip().split("\n")) == lines


def test_promotion_can_be_limited_to_named_ids(project, gold):
    fb.record(project, "one?", "wrong", by="a", at="2026-08-25", expected="x")
    fb.record(project, "two?", "wrong", by="a", at="2026-08-25", expected="y")
    added, _, _, _, _ = fb.promote(project, gold, ids=["fb-0002"])
    assert [entry["id"] for entry, _ in added] == ["fb-0002"]
    assert fb.promoted_ids(project) == {"fb-0002"}
    ready, _ = fb.pending(project)
    assert [entry["id"] for entry in ready] == ["fb-0001"]


def test_a_set_that_was_already_broken_still_accepts_feedback(project, tmp_path):
    """A half-written set must not block the loop. Its problems are reported, not raised."""
    path = tmp_path / "half.jsonl"
    meta = {"authored_by": "a team", "authored_by_kind": "team-human", "audited_fraction": 0.5,
            "audited_by": "a reviewer"}
    path.write_text(json.dumps({"_meta": meta}, sort_keys=True) + "\n"
                    + json.dumps({"id": "q1", "question": ""}, sort_keys=True) + "\n",
                    encoding="utf-8")
    fb.record(project, "retention?", "wrong", by="a", at="2026-08-25", expected="ten years")
    added, _, _, _, inherited = fb.promote(project, str(path))
    assert len(added) == 1
    assert inherited, "the pre-existing problems must be reported"


def test_nothing_is_written_when_the_promotion_would_introduce_a_problem(project, gold, monkeypatch):
    fb.record(project, "retention?", "wrong", by="teammate", at="2026-08-25", expected="ten years")
    monkeypatch.setattr(fb, "as_question",
                        lambda entry, kind="factual": {"id": "from-%s" % entry["id"],
                                                       "question": ""})
    original = open(gold, encoding="utf-8").read()
    with pytest.raises(ValueError) as exc:
        fb.promote(project, gold)
    assert "nothing written" in str(exc.value)
    assert open(gold, encoding="utf-8").read() == original
    assert fb.promoted_ids(project) == set()
    assert not os.path.exists(gold + ".promoting")


def test_two_independent_sets_stay_independent():
    """weaken() is only reached when feedback is folded in, so it always moves down the list."""
    assert fb.weaken({"authored_by_kind": "independent-human", "authored_by": "x"},
                     ["a"])["authored_by_kind"] == "mixed"
    assert fb.weaken({"authored_by_kind": "model", "authored_by": "x"},
                     ["a"])["authored_by_kind"] == "model"
