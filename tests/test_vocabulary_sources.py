"""Four ways to a vocabulary: ontologies merged, a file imported, the status that lists them,
and per-document gold questions appended."""
import json
import os
import tempfile

import pytest

from oto.bench import gold
from oto.builder import build
from oto.cli import main
from oto.model import importer, ontologies
from oto.project import Project
from oto.scaffold import init


def _config(root):
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- merging ontologies ----

def test_merge_unions_classes_and_reports_clashes():
    config, sample, readme, rationale, report = ontologies.merge(["organization-process", "auto-claims"])
    org, _s, _r = ontologies.load("organization-process")
    claims, _s, _r = ontologies.load("auto-claims")
    assert set(config["classes"]) == set(org["classes"]) | set(claims["classes"])
    assert report["classes"] == len(config["classes"])
    shared = set(org["classes"]) & set(claims["classes"])
    for kind, first, _second in report["class_clashes"]:
        assert kind in shared and first == "organization-process", "first ontology wins"
    assert {n["type"] for n in sample["nodes"]} == set(config["classes"])
    assert "prune" in readme.lower()
    assert set(rationale["classes"]) >= set(config["classes"])


def test_init_with_two_ontologies_builds(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Two", ontology="organization-process,auto-claims")
        assert "merged 2 ontologies" in capsys.readouterr().out
        project = Project.standard(root)
        build(project)
        assert os.path.exists(project.layout.database)
        assert _config(root)["name"] == "Two"


# ---- importing a file ----

def test_turtle_round_trips_through_the_build():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Src", ontology="auto-claims")
        project = Project.standard(root)
        build(project)
        ttl = os.path.join(project.layout.ontology, "src.ttl")
        classes, properties, notes = importer.read(ttl)
        assert notes == []
        original = _config(root)
        assert classes == original["classes"]
        for relation, spec in original["properties"].items():
            got = properties[relation]
            assert [got[0], got[1], got[2], got[3]] == [spec[0], spec[1], spec[2], spec[3]], relation
        assert importer.check(classes, properties) == []


def test_csv_import_writes_the_config_and_flags_missing_rationale(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Csv")
        path = os.path.join(root, "vocab.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("kind,name,description,domain,range,inverse\n"
                    "class,Machine,A physical machine.,,,\n"
                    "class,Site,A place where machines run.,,,\n"
                    "relation,installed_at,Where a machine runs.,Machine,Site,hosts\n"
                    "relation,hosts,The machines at a site.,Site,Machine,installed_at\n")
        capsys.readouterr()
        assert main(["ontology", "import", "--project", root, "--file", path]) == 0
        out = capsys.readouterr().out
        assert "wrote 2 class(es), 2 relation(s) and 0 attribute declaration(s)" in out and "recorded reason" in out
        config = _config(root)
        assert config["properties"]["installed_at"] == ["Machine", "Site", "hosts", "Where a machine runs."]
        assert config["temporal"], "the shared temporal vocabulary must survive an import"
        assert main(["ontology", "import", "--project", root, "--file", path]) == 1
        assert "already declares" in capsys.readouterr().err
        assert main(["ontology", "import", "--project", root, "--file", path, "--replace"]) == 0


def test_import_refuses_a_relation_naming_an_undeclared_class():
    classes = {"Machine": "A machine."}
    properties = {"at": ["Machine", "Site", None, "Where it is."]}
    problems = importer.check(classes, properties)
    assert any("undeclared class 'Site'" in p for p in problems)


def test_import_from_ontologies_carries_the_rationale(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="T")
        capsys.readouterr()
        assert main(["ontology", "import", "--project", root, "--from", "organization-process"]) == 0
        assert "rationale carried over" in capsys.readouterr().out
        assert _config(root)["classes"]
        assert main(["ontology", "rationale", "--project", root, "--strict"]) == 0
        assert main(["ontology", "import", "--project", root, "--from",
                     "organization-process,auto-claims", "--replace"]) == 0
        assert "merged 2 ontologies" in capsys.readouterr().out


def test_unsupported_vocabulary_file_is_refused():
    with pytest.raises(ValueError, match="unsupported"):
        importer.read("vocab.docx")


# ---- status lists the four ways ----

def test_status_lists_the_four_ways_when_nothing_is_declared(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Empty")
        capsys.readouterr()
        assert main(["status", "--project", root]) == 0
        out = capsys.readouterr().out
        for marker in ("from an ontology", "from the documents", "from a file you own", "by interview"):
            assert marker in out


# ---- per-document gold questions ----

def test_append_adds_questions_with_ids_and_sources_from_the_document():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "gold", "questions.jsonl")
        gold.write_starter(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"_meta": {"authored_by": "agent", "authored_by_kind": "model",
                                          "audited_fraction": 0, "audited_by": ""}}) + "\n")
        added, problems = gold.append(path, [
            {"question": "Who handles FNOL?", "expected_entities": ["role.adjuster"]},
            {"question": "Is the adjuster role current?", "type": "temporal", "expected_status": "current"},
        ], source_doc="handbook")
        assert problems == []
        assert [q["id"] for q in added] == ["handbook-1", "handbook-2"]
        assert added[0]["supporting_sources"] == ["handbook"] and added[0]["type"] == "factual"
        meta, questions = gold.load(path)
        assert len(questions) == 2 and gold.validate(meta, questions) == []
        added, _ = gold.append(path, [{"question": "Again?", "answer": "yes"}], source_doc="handbook")
        assert added[0]["id"] == "handbook-1-2", "ids never collide"


def test_append_refuses_a_question_with_nothing_to_grade():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "q.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"_meta": {"authored_by": "a", "authored_by_kind": "independent-human"}}) + "\n")
        added, problems = gold.append(path, [{"question": "Ungradeable?"}])
        assert problems and "nothing to grade" in problems[0]
        assert gold.load(path)[1] == [], "nothing written on a problem"


def test_cli_bench_add(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="G")
        path = os.path.join(root, "gold", "questions.jsonl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"_meta": {"authored_by": "agent", "authored_by_kind": "model",
                                          "audited_fraction": 0, "audited_by": ""}}) + "\n")
        source = os.path.join(root, "handbook.questions.json")
        with open(source, "w", encoding="utf-8") as f:
            json.dump({"source_doc": "handbook", "questions": [
                {"question": "Who handles FNOL?", "expected_entities": ["role.adjuster"]}]}, f)
        capsys.readouterr()
        assert main(["bench", "add", "--project", root, "--from", source]) == 0
        assert "added 1 question(s)" in capsys.readouterr().out
        assert main(["bench", "validate", "--project", root]) == 0
