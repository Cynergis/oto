"""Recorded reasoning: required for classes, honest about validation, and checkable."""
import json
import os
import tempfile

import pytest

from oto.model import rationale, ontologies
from oto.project import Project
from oto.scaffold import init

CONFIG = {"classes": {"Claim": {"definition": "a request for payment"}, "Party": {"definition": "a person or organization"}},
          "properties": {"filed_by": {"domain": "Claim", "range": "Party", "inverse": "filed", "definition": "who made the claim"}}}


def _entry(question="Which policy applies?", why="Cover is decided against a policy at a moment in time.",
           validated_by=""):
    return {"question": question, "why": why, "alternatives": "", "validated_by": validated_by}


def test_a_missing_class_rationale_is_reported():
    report = rationale.report(CONFIG, {"classes": {"Claim": _entry()}, "properties": {}})
    assert report["classes_missing"] == ["Party"]
    assert report["classes_with_rationale"] == 1


def test_a_rationale_that_repeats_the_description_is_rejected():
    """Copying the description looks like the review happened. That is worse than leaving it blank."""
    entry = _entry(why="a request for payment")
    report = rationale.report(CONFIG, {"classes": {"Claim": entry, "Party": _entry()},
                                       "properties": {}})
    assert any("repeats its definition" in p for p in report["problems"])


def test_a_rationale_too_short_to_say_anything_is_rejected():
    report = rationale.report(CONFIG, {"classes": {"Claim": _entry(why="because"),
                                                   "Party": _entry()}, "properties": {}})
    assert any("too short" in p for p in report["problems"])


def test_a_missing_question_is_reported():
    """The question is the discipline: a class with none behind it should not exist."""
    report = rationale.report(CONFIG, {"classes": {"Claim": _entry(question=""),
                                                   "Party": _entry()}, "properties": {}})
    assert any("no `question`" in p for p in report["problems"])


def test_a_rationale_for_an_undeclared_class_is_stale():
    report = rationale.report(CONFIG, {"classes": {"Claim": _entry(), "Party": _entry(),
                                                   "Gone": _entry()}, "properties": {}})
    assert any("no longer declared" in p for p in report["problems"])


def test_validation_is_counted_not_assumed():
    """The whole point: 'looks reasonable' is not 'confirmed by someone who knows'."""
    record = {"classes": {"Claim": _entry(validated_by="A. Adjuster, 2026-03-01"),
                          "Party": _entry()}, "properties": {}}
    report = rationale.report(CONFIG, record)
    assert report["classes_validated"] == ["Claim"]
    assert len(report["classes_validated"]) < report["classes"]


def test_a_complete_record_has_no_problems():
    record = {"classes": {"Claim": _entry(), "Party": _entry()}, "properties": {}}
    report = rationale.report(CONFIG, record)
    assert report["problems"] == []
    assert report["classes_missing"] == []


def test_round_trip_through_a_project():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        project = Project.standard(root)
        assert rationale.load(project) == {"classes": {}, "properties": {}}
        record = {"classes": {"Claim": _entry()}, "properties": {}}
        rationale.save(project, record)
        back = rationale.load(project)
        assert back["classes"]["Claim"]["question"] == _entry()["question"]


# ---- what ships ----

@pytest.mark.parametrize("name", ontologies.available())
def test_every_ontology_class_has_a_recorded_reason(name):
    """An ontology is the exemplar. Shipping one without reasoning teaches that reasoning is optional."""
    config, _sample, _readme = ontologies.load(name)
    report = rationale.report(config, ontologies.rationale_for(name))
    assert report["classes_missing"] == []
    assert report["problems"] == []


@pytest.mark.parametrize("name", ontologies.available())
def test_no_ontology_claims_to_be_validated(name):
    """Nobody has reviewed these. Claiming otherwise would be the worst possible default."""
    report = rationale.report(*(lambda c: (c, ontologies.rationale_for(name)))(
        ontologies.load(name)[0]))
    assert report["classes_validated"] == [], "an ontology must not assert its own validation"


def test_init_with_a_ontology_installs_the_rationale():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Acme Claims", ontology="auto-claims")
        project = Project.standard(root)
        record = rationale.load(project)
        assert record["classes"], "the rationale was not installed"
        with open(project.ontology_config_path, encoding="utf-8") as f:
            config = json.load(f)
        report = rationale.report(config, record)
        assert report["classes_missing"] == []
        assert report["classes_validated"] == []


def test_the_interview_skill_exists_and_leads_with_questions():
    """The skill's whole discipline is questions before nouns. If that is missing, it is just advice."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "skills", "ontology-interview", "SKILL.md")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "questions before nouns" in text.lower()
    assert "validated_by" in text
    assert "Never fill `validated_by` yourself" in text
