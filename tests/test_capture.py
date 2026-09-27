"""A conversation becomes a dated, attributed source document in the inbox."""
import os
import tempfile

import pytest

from oto import capture
from oto.cli import main
from oto.intake import pipeline
from oto.project import Project
from oto.scaffold import init


def test_the_note_has_one_shape():
    text = capture.note("Deductible change", ['The deductible went up in April, not "May".', "Handler approved it."],
                        by="R. Handler, claims lead", at="2026-04-01", about=["policy.p-1001"],
                        context="Asked while reviewing claim C-5001.")
    assert text.startswith("# Deductible change\n\n> **Captured:** 2026-04-01 · **By:** R. Handler, claims lead")
    assert "**About:** policy.p-1001" in text
    assert "It is a source document" in text
    assert "1. \"The deductible went up in April, not 'May'.\" — R. Handler, claims lead, 2026-04-01" in text
    assert "2. \"Handler approved it.\"" in text
    assert text.rstrip().endswith("Asked while reviewing claim C-5001.")


def test_a_missing_author_or_a_non_date_is_refused():
    with pytest.raises(ValueError, match="--by"):
        capture.note("t", ["s"], by="", at="2026-01-01")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        capture.note("t", ["s"], by="x", at="April 2026")
    with pytest.raises(ValueError, match="statement"):
        capture.note("t", ["", "  "], by="x", at="2026-01-01")


def test_capture_writes_into_the_inbox_and_ingest_takes_it(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="KB", ontology="auto-claims")
        project = Project.standard(root)
        capsys.readouterr()
        assert main(["capture", "--project", root, "--title", "Deductible change", "--by", "R. Handler",
                     "--at", "2026-04-01", "--statement", "The deductible went up in April.",
                     "--about", "policy.p-1001,no.such"]) == 0
        out = capsys.readouterr().out
        assert "captured inbox/2026-04-01-deductible-change.md" in out
        assert "about 'no.such': no such id" in out
        assert "oto ingest" in out, "a local project is told to ingest"
        # The same title and date twice, while the first still waits in the inbox, is refused.
        assert main(["capture", "--project", root, "--title", "Deductible change", "--by", "R. Handler",
                     "--at", "2026-04-01", "--statement", "Again."]) == 1
        assert "pass --force" in capsys.readouterr().err
        result = pipeline.ingest(project)
        assert result["written"] == ["2026-04-01-deductible-change"]
        corpus = open(os.path.join(project.layout.corpus, "2026-04-01-deductible-change.md"), encoding="utf-8").read()
        assert "R. Handler" in corpus and "went up in April" in corpus


def test_a_repository_project_is_told_to_push(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Repo", repo=True)
        capsys.readouterr()
        assert main(["capture", "--project", root, "--title", "Owner moved", "--by", "A. Person",
                     "--at", "2026-03-01", "--statement", "The owner changed in March."]) == 0
        out = capsys.readouterr().out
        assert "git push" in out and "opens the PR" in out


def test_statements_can_come_from_a_file(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="KB")
        path = os.path.join(root, "said.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("- First thing.\n2. Second thing.\n\n")
        capsys.readouterr()
        assert main(["capture", "--project", root, "--title", "Two things", "--by", "B", "--at", "2026-01-01",
                     "--statements-file", path]) == 0
        text = open(os.path.join(root, "inbox", "2026-01-01-two-things.md"), encoding="utf-8").read()
        assert '1. "First thing."' in text and '2. "Second thing."' in text


def test_the_capture_skill_keeps_the_rules():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill = open(os.path.join(root, "skills", "capture", "SKILL.md"), encoding="utf-8").read()
    for rule in ("oto capture", "Their words, not your summary", "Never default the date", "Never write to `graph.json`",
                 "Ask before pushing", "One conversation, one note"):
        assert rule in skill, rule
