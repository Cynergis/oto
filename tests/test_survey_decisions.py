"""A person's decision on a survey candidate is recorded, attributed, and counted by the stage and the
fix that proposed it, so a stage whose suggestions people keep rejecting shows it."""
import json
import os

import pytest

from oto.cli import main
from oto.intake import decisions as _decisions, survey as sv
from oto.project import Project
from oto.scaffold import init

DOCS = {"a": "The Fraud Unit met Dana Reyes. Open a Work Order for PM-B. The error budget is spent.\n",
        "b": "The Fraud Unit closed two Work Orders. PM-B is due. Dana Reyes left. The error budget recovered.\n"}


@pytest.fixture
def project(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    corpus = os.path.join(root, "build", "documents")
    os.makedirs(corpus, exist_ok=True)
    for name, text in DOCS.items():
        with open(os.path.join(corpus, name + ".md"), "w", encoding="utf-8") as f:
            f.write(text)
    return Project.standard(root)


def _result(project):
    return sv.survey(project.layout.corpus)


def test_each_candidate_says_which_fix_brought_it(project):
    found = {c["term"]: c for c in _result(project)["candidates"]}
    assert found["PM-B"]["via"] == ["codes"]
    assert found["error budget"]["via"] == ["lowercase"]
    assert found["Work Order"]["via"] == ["plurals"]
    assert found["Fraud Unit"]["via"] == []


def test_a_decision_needs_a_person_and_a_candidate(project):
    result = _result(project)
    with pytest.raises(ValueError, match="--by"):
        _decisions.record(project, result, "Fraud Unit", "accepted", by="")
    with pytest.raises(ValueError, match="not a candidate"):
        _decisions.record(project, result, "Claims Manager", "accepted", by="Sam")
    entry = _decisions.record(project, result, "work orders", "accepted", by="Sam Lee", at="2026-10-23", as_="class")
    assert (entry["term"], entry["verdict"], entry["stage"], entry["kind"], entry["via"], entry["as"]) == \
        ("Work Order", "accepted", "counted", "phrase", ["plurals"], "class"), "a variant names its candidate"
    assert entry["by"] == "Sam Lee" and entry["at"] == "2026-10-23"


def test_the_latest_decision_wins_and_the_log_keeps_both(project):
    result = _result(project)
    _decisions.record(project, result, "Dana Reyes", "accepted", by="Sam", at="2026-10-23")
    _decisions.record(project, result, "Dana Reyes", "rejected", by="Dana Reyes", at="2026-10-24", note="a person, not a term")
    assert len(_decisions.read(project)) == 2
    assert _decisions.latest(project)["dana reyes"]["verdict"] == "rejected"


def test_a_rejected_candidate_leaves_the_review_list_and_an_accepted_one_is_marked(project):
    result = _result(project)
    _decisions.record(project, result, "Dana Reyes", "rejected", by="Sam")
    _decisions.record(project, result, "Fraud Unit", "accepted", by="Sam")
    shown = _decisions.apply(result, _decisions.latest(project))
    terms = {c["term"]: c for c in shown["candidates"]}
    assert "Dana Reyes" not in terms and [c["term"] for c in shown["rejected"]] == ["Dana Reyes"]
    assert terms["Fraud Unit"]["decision"]["verdict"] == "accepted"
    assert "Dana Reyes" in {c["term"] for c in result["candidates"]}, "the measured result is not changed by decisions"


def test_acceptance_is_counted_by_stage_and_by_fix(project):
    result = _result(project)
    for term, verdict in (("Fraud Unit", "accepted"), ("Work Order", "accepted"), ("PM-B", "accepted"),
                          ("error budget", "rejected"), ("Dana Reyes", "rejected")):
        _decisions.record(project, result, term, verdict, by="Sam")
    stats = _decisions.stats(_decisions.latest(project), result)
    assert stats["stage"]["counted"] == {"accepted": 3, "rejected": 2, "undecided": 0, "rate": pytest.approx(0.6)}
    assert stats["via"]["lowercase"]["rate"] == 0.0 and stats["via"]["codes"]["rate"] == 1.0
    assert stats["via"]["plurals"]["accepted"] == 1


def test_the_command_records_lists_and_hides(project, capsys):
    root = project.data
    assert main(["survey", "accept", "--project", root, "--term", "Fraud Unit"]) == 1, "no person, no decision"
    assert main(["survey", "accept", "--project", root, "--term", "Fraud Unit", "--by", "Sam Lee", "--as", "entity"]) == 0
    assert main(["survey", "reject", "--project", root, "--term", "Dana Reyes", "--by", "Sam Lee", "--note", "a person"]) == 0
    capsys.readouterr()
    assert main(["survey", "--project", root]) == 0
    out = capsys.readouterr().out
    assert "Fraud Unit  [accepted by Sam Lee]" in out and "Dana Reyes" not in out
    assert "1 candidate(s) rejected by a person are not listed" in out
    assert main(["survey", "decisions", "--project", root]) == 0
    out = capsys.readouterr().out
    assert "counted" in out and "accepted 1, rejected 1" in out and "Dana Reyes" in out
    with open(os.path.join(root, _decisions.NAME), encoding="utf-8") as f:
        assert [json.loads(line)["verdict"] for line in f] == ["accepted", "rejected"]
