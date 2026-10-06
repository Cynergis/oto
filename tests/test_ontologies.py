"""Starter vocabularies: self-consistent, self-conformant, and they install."""
import json
import os
import tempfile

import pytest

from oto.model import ontologies, vocabulary as vocab
from oto.project import Project
from oto.scaffold import init

NAMES = ontologies.available()


def test_ontologies_exist():
    """Shipping none defeats the purpose: an empty config is why teams give up."""
    assert NAMES, "no starter vocabularies found"
    assert "auto-claims" in NAMES


@pytest.mark.parametrize("name", NAMES)
def test_ontology_self_check_is_clean(name):
    assert ontologies.self_check(name) == []


@pytest.mark.parametrize("name", NAMES)
def test_ontology_declares_every_class_it_references(name):
    """A domain or range naming an undeclared class fails the build on the team's first try."""
    config, _sample, _readme = ontologies.load(name)
    classes = set(config["classes"])
    for relation, spec in config["properties"].items():
        for position in ("domain", "range"):
            for kind in [x.strip() for x in (spec.get(position) or "").split("|") if x.strip()]:
                assert kind in classes, "%s: %s names undeclared %s" % (name, relation, kind)


@pytest.mark.parametrize("name", NAMES)
def test_ontology_is_self_conformant(name):
    """A team's first `oto ontology check` must be quiet, or the report loses its meaning."""
    config, sample, _readme = ontologies.load(name)
    report = vocab.conformance(vocab.Vocabulary.from_config(config),
                              sample.get("nodes") or [], sample.get("edges") or [])
    assert report["domain_violations"] == 0, report["domain_patterns"][:3]
    assert report["range_violations"] == 0, report["range_patterns"][:3]


@pytest.mark.parametrize("name", NAMES)
def test_ontology_is_versioned(name):
    config, _sample, _readme = ontologies.load(name)
    assert config.get("ontology_version"), "%s has no ontology_version" % name


@pytest.mark.parametrize("name", NAMES)
def test_ontology_ships_a_temporal_vocabulary(name):
    """Without the temporal fields, nothing can be superseded, which is the whole point."""
    config, _sample, _readme = ontologies.load(name)
    temporal = config.get("temporal") or {}
    for field in ("asOf", "validFrom", "status", "sourceDoc"):
        assert field in temporal, "%s is missing %s" % (name, field)


@pytest.mark.parametrize("name", NAMES)
def test_ontology_readme_warns_about_editing(name):
    """An ontology adopted unchanged is a worse outcome than no ontology."""
    _config, _sample, readme = ontologies.load(name)
    assert readme.strip()
    assert "first draft" in readme.lower() or "edit it" in readme.lower()


def test_init_with_a_ontology_installs_a_buildable_project():
    from oto.builder import build

    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Claims KB", ontology="auto-claims")
        project = Project.standard(root)
        with open(project.ontology_config_path, encoding="utf-8") as f:
            assert json.load(f)["classes"], "the vocabulary was not installed"
        with open(project.graph_path, encoding="utf-8") as f:
            assert json.load(f)["nodes"], "the sample graph was not installed"
        assert os.path.exists(os.path.join(root, "ONTOLOGY-NOTES.md")), "the rationale was not kept"
        build(project)                                    # must not raise
        assert os.path.exists(project.layout.database)


def test_init_names_the_project_not_the_ontology():
    """The ontology's own title must not leak into the project's identity."""
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="claims", name="Acme Claims", ontology="auto-claims")
        project = Project.standard(root)
        with open(project.ontology_config_path, encoding="utf-8") as f:
            assert json.load(f)["name"] == "Acme Claims"


def test_unknown_ontology_is_rejected_with_the_options():
    with tempfile.TemporaryDirectory() as root:
        with pytest.raises(ValueError) as exc:
            init(root, slug="x", name="X", ontology="no-such-ontology")
        assert "auto-claims" in str(exc.value), "the error should list what is available"


def test_the_drafting_reference_states_the_rules_a_drafter_must_keep():
    """Every parallel drafter reads the same file; if it drifts, every proposal drifts."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skill = open(os.path.join(root, "skills", "build-knowledge-base", "SKILL.md"), encoding="utf-8").read()
    assert "references/draft-proposal.md" in skill and "in series" in skill
    reference = open(os.path.join(root, "skills", "build-knowledge-base", "references", "draft-proposal.md"),
                     encoding="utf-8").read()
    for rule in ("--dry-run", "evidence", "Never edit `graph.json`", "source_type", "supersedes",
                 "Needs the vocabulary", "Not asserted"):
        assert rule in reference, rule
    assert "references/pipeline-run.md" in skill
    pipeline = open(os.path.join(root, "skills", "build-knowledge-base", "references", "pipeline-run.md"),
                    encoding="utf-8").read()
    for rule in ("runs/<run-id>.report.md", "BLOCKED:", "do not commit, do not push", "Never apply with `--force`",
                 "Never mark the gold set audited", "needs the vocabulary"):
        assert rule in pipeline, rule
