"""A project's vocabulary becomes an ontology, and an ontology can come from anywhere."""
import json
import os
import tempfile

import pytest

from oto.builder import build
from oto.cli import main
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init


@pytest.fixture
def user_ontologies(tmp_path, monkeypatch):
    path = tmp_path / "user-ontologies"
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(path))
    return path


def _claims_project(root):
    init(root, slug="claims", name="Acme Claims", ontology="auto-claims")
    return Project.standard(root)


def test_export_writes_a_usable_ontology_that_builds(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        path, problems = ontologies.export(project, "my-claims", summary="Claims, as Acme does them.")
        assert problems == []
        assert path == str(user_ontologies / "my-claims")
        assert "my-claims" in ontologies.available()
        assert ontologies.origin("my-claims") == ontologies.USER
        assert ontologies.summary("my-claims")["about"] == "Claims, as Acme does them."
    with tempfile.TemporaryDirectory() as other:
        init(other, slug="ins", name="Insurer", ontology="my-claims")
        project = Project.standard(other)
        build(project)
        assert os.path.exists(project.layout.database)


def test_the_invented_sample_covers_every_class_and_relation(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        ontologies.export(project, "t")
        config, sample, readme = ontologies.load("t")
        assert {n["type"] for n in sample["nodes"]} == set(config["classes"])
        assert {e["rel"] for e in sample["edges"]} == set(config["properties"])
        assert all(n["source_doc"] == "sample" for n in sample["nodes"])
        assert "first draft" in readme.lower()


def test_export_resets_version_and_blanks_validation(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        with open(project.ontology_config_path, encoding="utf-8") as f:
            config = json.load(f)
        config["ontology_version"] = 7
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        from oto.model import rationale as _rationale
        record = _rationale.load(project)
        first = next(iter(record["classes"]))
        record["classes"][first]["validated_by"] = "A. Expert, 2026-05-01"
        _rationale.save(project, record)

        ontologies.export(project, "t")
        exported, _sample, readme = ontologies.load("t")
        assert exported["ontology_version"] == 1
        assert exported["_exported_from_version"] == 7
        assert exported["name"] == "Acme Claims"
        shipped = ontologies.rationale_for("t")
        assert all(e["validated_by"] == "" for e in shipped["classes"].values())
        assert "1 of" in readme and "does not carry over" in readme


def test_export_refuses_a_vocabulary_with_no_recorded_reasoning(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="kb", name="KB")
        project = Project.standard(root)
        with open(project.ontology_config_path, encoding="utf-8") as f:
            config = json.load(f)
        config["classes"] = {"Machine": {"definition": "A machine."}}
        config["properties"] = {"at": {"domain": "Machine", "range": "Machine", "definition": "Where it is."}}
        with open(project.ontology_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)
        with pytest.raises(ValueError, match="no recorded reason"):
            ontologies.export(project, "t")
        assert "t" not in ontologies.available()


def test_export_refuses_to_overwrite_without_force(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        ontologies.export(project, "t")
        with pytest.raises(FileExistsError):
            ontologies.export(project, "t")
        ontologies.export(project, "t", force=True)


def test_a_real_data_sample_is_privacy_scanned(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["nodes"][0]["summary"] = "Policyholder SIN 046 454 286."
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        with pytest.raises(ValueError, match="personal data"):
            ontologies.export(project, "t", from_graph=50)      # every node, so the tainted one is in
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["nodes"][0]["summary"] = "A policy."
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        _path, problems = ontologies.export(project, "t", from_graph=5)
        _config, sample, _readme = ontologies.load("t")
        assert 0 < len(sample["nodes"]) <= 5
        assert len({n["type"] for n in sample["nodes"]}) == len(sample["nodes"]), "round-robin across classes"
        assert any("the sample cannot answer AC1" in p for p in problems), \
            "a slice of real data that cannot answer the ontology's questions is reported, not shipped quietly"
        _path, problems = ontologies.export(project, "t-whole", from_graph=50)
        assert problems == [], problems


def test_a_user_ontology_shadows_a_shipped_one_of_the_same_name(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        ontologies.export(project, "auto-claims", summary="Our edited version.")
        assert ontologies.origin("auto-claims") == ontologies.USER
        assert ontologies.summary("auto-claims")["about"] == "Our edited version."
        assert ontologies.available().count("auto-claims") == 1


def test_init_accepts_a_ontology_directory_path(user_ontologies):
    with tempfile.TemporaryDirectory() as root:
        project = _claims_project(root)
        path, _ = ontologies.export(project, "t", to=os.path.join(root, "exported"))
        assert ontologies.origin(path) == ontologies.PATH
        with tempfile.TemporaryDirectory() as other:
            init(other, slug="p", name="P", ontology=path)
            with open(os.path.join(other, "ontology.config.json"), encoding="utf-8") as f:
                assert json.load(f)["classes"]


def test_cli_export_and_list(user_ontologies, capsys):
    with tempfile.TemporaryDirectory() as root:
        _claims_project(root)
        capsys.readouterr()
        assert main(["ontology", "export", "--project", root, "--name", "cli-t"]) == 0
        assert "self-check clean" in capsys.readouterr().out
        assert main(["ontology", "list"]) == 0
        out = capsys.readouterr().out
        assert "cli-t" in out and "(yours)" in out
        assert main(["ontology", "export", "--project", root, "--name", "cli-t"]) == 1
        assert "already exists" in capsys.readouterr().err
