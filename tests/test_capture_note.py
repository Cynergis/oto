"""A captured note is checked where it is cheapest to fix, before anything is drafted from it: a statement
that dates itself by "today" or "last week" cannot be quoted for a date, and an `--about` that names a
retired fact, a label or a lexicon word instead of the current id points the drafter at the wrong
entity. Both are warnings: the note keeps the speaker's words and the ids it was given."""
import json
import os

import pytest

from oto import capture
from oto.project import Project
from oto.scaffold import init


def _node(nid, label, **extra):
    return dict({"id": nid, "type": "Thing", "label": label, "aliases": [], "status": "current"}, **extra)


GRAPH = {"nodes": [_node("garage.central", "Central Garage", aliases=["the depot", "the garage"]),
                   _node("garage.east", "East Garage", aliases=["the garage"]),
                   _node("pm.pm-b", "PM-B interval", status="superseded", superseded_by="pm.pm-b-2025-09"),
                   _node("pm.pm-b-2025-09", "PM-B interval", supersedes="pm.pm-b"),
                   _node("garage.east-annex", "East Garage annex")],
         "edges": []}


@pytest.fixture
def project(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(GRAPH, f)
    with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
        json.dump({"entries": [{"term": "the yard", "aka": [], "targets": ["garage.east"], "status": "current"}]}, f)
    return Project.standard(root)


def _write(project, statements, about=None, at="2025-10-02"):
    return capture.write(project, "Work order", statements, "Dana, supervisor", at, about=about)[1]


def test_a_statement_dated_by_today_or_yesterday_is_named_with_the_date_it_would_mean(project):
    warnings = _write(project, ["I opened WO-2304 today.", "The bus came in yesterday."])
    assert len(warnings) == 2
    assert "statement 1" in warnings[0] and "'today'" in warnings[0] and "2025-10-02" in warnings[0]
    assert "statement 2" in warnings[1] and "'yesterday'" in warnings[1] and "2025-10-01" in warnings[1]


def test_other_relative_dates_are_named_without_a_date(project):
    warnings = _write(project, ["The interval changed last week.", "We fixed it two days ago.",
                                "It was replaced the same day."])
    assert [w.split(" ")[1] for w in warnings] == ["1", "2", "3"]
    assert "'last week'" in warnings[0] and "'two days ago'" in warnings[1] and "'the same day'" in warnings[2]


def test_a_dated_statement_raises_nothing_and_the_note_keeps_the_speakers_words(project):
    assert _write(project, ["I opened WO-2304 on 2 October 2025."]) == []
    path = os.path.join(project.layout.inbox, capture.filename("Work order", "2025-10-02"))
    os.remove(path)
    _write(project, ["I opened WO-2304 today."])
    with open(path, encoding="utf-8") as f:
        assert "I opened WO-2304 today." in f.read(), "capture never rewrites a statement"


def test_a_current_id_is_quiet_and_a_retired_one_names_its_current_version(project):
    assert _write(project, ["Done on 2 October."], about=["garage.central"]) == []
    os.remove(os.path.join(project.layout.inbox, capture.filename("Work order", "2025-10-02")))
    warnings = _write(project, ["Done on 2 October."], about=["pm.pm-b"])
    assert len(warnings) == 1 and "superseded" in warnings[0] and "pm.pm-b-2025-09" in warnings[0]


@pytest.mark.parametrize("about, grade, target", [("Central Garage", "label", "garage.central"),
                                                  ("PM-B interval", "label", "pm.pm-b-2025-09"),
                                                  ("the depot", "alias", "garage.central"),
                                                  ("the yard", "lexicon", "garage.east")])
def test_a_name_instead_of_an_id_is_matched_and_its_id_named(project, about, grade, target):
    warnings = _write(project, ["Done on 2 October."], about=[about])
    assert len(warnings) == 1 and "is not an id" in warnings[0]
    assert "%s (%s)" % (target, grade) in warnings[0]


def test_a_name_of_two_current_entities_is_ambiguous_and_a_near_name_is_not_a_match(project):
    warnings = _write(project, ["Done on 2 October."], about=["the garage", "east"])
    assert "names 2 entities" in warnings[0] and "garage.central" in warnings[0] and "garage.east" in warnings[0]
    assert "closest by name, not a match" in warnings[1]
    assert "garage.east" in warnings[1] and "garage.east-annex" in warnings[1]


def test_a_name_nothing_resembles_is_said_plainly(project):
    warnings = _write(project, ["Done on 2 October."], about=["warehouse.north"])
    assert len(warnings) == 1 and "no such id or name in the graph" in warnings[0]
