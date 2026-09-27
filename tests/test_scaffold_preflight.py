"""`oto init` creates a data-only project, and preflight blocks a bad build before it writes."""
import json
import os
import tempfile

import pytest

from oto.project import Project, ProjectError
from oto.scaffold import init
from oto.validate.preflight import preflight


def _project(root, slug="acme"):
    init(root, slug=slug, name="Acme")
    return Project.standard(root)


def test_init_writes_data_only():
    """A project must contain no engine code. That is the whole point of the package boundary."""
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        python_files = []
        for dirpath, _dirnames, filenames in os.walk(root):
            python_files += [f for f in filenames if f.endswith(".py")]
        assert python_files == [], "init copied engine code into the project: %s" % python_files


def test_init_creates_the_expected_layout():
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        for expected in ("project.config.json", "ontology.config.json", "graph.json",
                         "README.md", ".gitignore", "inbox", "archive", "build"):
            assert os.path.exists(os.path.join(root, expected)), expected


def test_init_derives_the_slug_from_the_name():
    from oto.scaffold import slug_from

    assert slug_from("Acme Claims") == "acme-claims"
    assert slug_from("  R&D / EU 2026 ") == "r-d-eu-2026"
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Acme Claims")
        with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        assert (cfg["slug"], cfg["name"], cfg["db_name"]) == ("acme-claims", "Acme Claims", "acme-claims.db")


def test_init_needs_a_name_or_a_slug():
    from oto.cli import main

    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(ValueError, match="needs a name"):
            init(root)
        assert main(["init", "--project", root]) == 1
        assert main(["init", "--project", root, "--name", "Only A Name"]) == 0


def test_init_is_idempotent():
    """Re-running init must never overwrite authored data."""
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        graph_path = os.path.join(root, "graph.json")
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "keep.me"}], "edges": []}, f)
        init(root, slug="acme", name="Acme")
        with open(graph_path, encoding="utf-8") as f:
            assert json.load(f)["nodes"][0]["id"] == "keep.me"


def test_preflight_reports_every_problem_at_once():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump({"classes": {"Claim": "A claim."},
                       "properties": {"filed_by": ["Claim", "Person", None, "Filer."]}}, f)
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "c.1", "type": "Claim", "label": "One"},
                                 {"id": "c.1", "type": "Claim", "label": "Duplicate"},
                                 {"id": "a.1", "type": "Adjuster", "label": "Undeclared"}],
                       "edges": [{"from": "c.1", "rel": "handled_by", "to": "missing"}]}, f)
        with pytest.raises(ProjectError) as exc:
            preflight(project)
        message = str(exc.value)
        assert "duplicate node ids" in message
        assert "Adjuster" in message
        assert "handled_by" in message
        assert "unknown node" in message


def test_preflight_accepts_a_valid_project():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump({"classes": {"Claim": "A claim.", "Person": "A person."},
                       "properties": {"filed_by": ["Claim", "Person", None, "Filer."]}}, f)
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "c.1", "type": "Claim", "label": "One"},
                                 {"id": "p.1", "type": "Person", "label": "Two"}],
                       "edges": [{"from": "c.1", "rel": "filed_by", "to": "p.1"}]}, f)
        summary = preflight(project)
        assert summary["name"] == "Acme"
        assert (summary["nodes"], summary["edges"]) == (2, 1)
        assert (summary["classes"], summary["properties"]) == (2, 1)
        # A conformant project with no accepted baseline has nothing to report.
        assert summary["warnings"] == []


def test_selftest_passes():
    """The greenfield self-test must pass on an invented domain."""
    from oto.validate.selftest import verify

    assert verify() is True


def test_preflight_explains_a_malformed_lexicon():
    from oto.validate.preflight import preflight

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump({"classes": {"Machine": "A machine."},
                       "properties": {"near": ["Machine", "Machine", None, "Close to."]}}, f)
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": [{"id": "machine.press", "type": "Machine", "label": "Press",
                                  "as_of": "2026-01-01", "valid_from": "2026-01-01",
                                  "source_doc": "h", "status": "current", "sources": ["h"]}],
                       "edges": []}, f)
        with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
            json.dump([{"phrase": "the press"}], f)
        with pytest.raises(ProjectError, match='"entries"'):
            preflight(project)
        with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"term": "PM", "targets": ["procedure.nowhere"]}]}, f)
        with pytest.raises(ProjectError, match="unknown node"):
            preflight(project)
        with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"term": "PM", "aka": ["preventive"], "targets": ["machine.press"]}]}, f)
        preflight(project)
