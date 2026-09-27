"""Declared, typed attributes per class: checked at the gates, exported as datatype properties."""
import json
import os
import tempfile

import pytest

from oto.builder import build
from oto.cli import main
from oto.curate import diff
from oto.model import importer, ontologies, vocabulary as vocab
from oto.project import Project
from oto.scaffold import init
from oto.validate.preflight import preflight

VOCAB = {"classes": {"Claim": "A claim.", "Party": "A party."},
         "properties": {"filed_by": ["Claim", "Party", None, "Who filed it."]},
         "attributes": {"Claim": {"claim_number": ["string", "The identifier."],
                                  "state": ["enum:open|closed", "Where it is."],
                                  "amount": ["number", "Reserve."],
                                  "opened_on": ["date", "When it was opened."]}},
         "temporal": {}}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "d", "status": "current", "sources": ["d"]}


def _node(nid, kind="Claim", **attrs):
    return dict(id=nid, type=kind, label=nid, aliases=[], summary="s", attributes=attrs, tags=[], **STAMP)


def _project(root, nodes, config=VOCAB):
    init(root, name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": []}, f)
    return Project.standard(root)


# ---- the types ----

def test_values_are_checked_against_their_declared_type():
    assert vocab.check_value("string", "C-1") is None
    assert vocab.check_value("string", 5) == "expected a string"
    assert vocab.check_value("enum:open|closed", "open") is None
    assert vocab.check_value("enum:open|closed", "lost") == "expected one of open|closed"
    assert vocab.check_value("number", 12.5) is None and vocab.check_value("number", True)
    assert vocab.check_value("integer", 3) is None and vocab.check_value("integer", 3.5)
    assert vocab.check_value("boolean", False) is None and vocab.check_value("boolean", "no")
    assert vocab.check_value("date", "2026-03-14") is None and vocab.check_value("date", "March 14")
    assert vocab.check_value("list", ["a"]) is None and vocab.check_value("list", "a")
    assert vocab.check_value("date", None) is None and vocab.check_value("date", "") is None, "absent always fits"
    with pytest.raises(ValueError):
        vocab.check_value("money", 1)


def test_a_bad_declaration_is_reported_before_anything_is_checked():
    problems = vocab.declaration_problems({"Claim": "c"}, {"Ghost": {"x": ["string", ""]},
                                                          "Claim": {"y": ["money", ""], "z": "string"}})
    assert any("undeclared class 'Ghost'" in p for p in problems)
    assert any("Claim.y" in p and "unknown attribute type" in p for p in problems)
    assert any("Claim.z must be [type, description]" in p for p in problems)


def test_conformance_checks_declared_classes_only():
    v = vocab.Vocabulary.from_config(VOCAB)
    nodes = [_node("c.1", claim_number="C-1", state="open", amount=100, opened_on="2026-01-02"),
             _node("c.2", state="lost", colour="red"),
             _node("p.1", "Party", anything="goes")]
    report = vocab.attribute_conformance(v, nodes)
    assert report["checked"] == 5
    assert report["mistyped"] == [("c.2", "state", "expected one of open|closed", "lost")]
    assert report["undeclared"] == [(("Claim", "colour"), 1)], "Party declares nothing, so it is unconstrained"


# ---- the gates ----

def test_preflight_blocks_a_mistyped_value_and_advises_on_an_undeclared_key():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, [_node("c.1", state="lost")])
        with pytest.raises(Exception, match="expected one of open|closed"):
            preflight(project)
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, [_node("c.1", state="open", colour="red")])
        summary = preflight(project)
        assert any("not these" in w for w in summary["warnings"])
    with tempfile.TemporaryDirectory() as root:
        strict = dict(VOCAB, strict_attributes=True)
        project = _project(root, [_node("c.1", colour="red")], config=strict)
        with pytest.raises(Exception, match="strict_attributes"):
            preflight(project)


def test_curate_check_blocks_a_mistyped_value_and_reports_an_undeclared_key():
    live = {"nodes": [], "edges": []}
    candidate = {"nodes": [_node("c.1", state="lost", colour="red", evidence=[{"doc": "d"}])], "edges": []}
    findings = diff.check(live, candidate, VOCAB)
    assert any(f.severity == diff.Finding.BLOCKING and "expected one of" in f.detail for f in findings)
    assert any(f.severity == diff.Finding.GAP and f.subject == "Claim.colour" for f in findings)


def test_ontology_check_reports_attributes_and_fails_on_a_mistype(capsys):
    with tempfile.TemporaryDirectory() as root:
        _project(root, [_node("c.1", state="open", amount=5)])
        capsys.readouterr()
        assert main(["ontology", "check", "--project", root]) == 0
        assert "attributes: 4 declared across 1 class(es); 2 value(s) checked, 0 mistyped" in capsys.readouterr().out
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump({"nodes": [_node("c.1", amount="five")], "edges": []}, f)
        assert main(["ontology", "check", "--project", root]) == 1
        assert "MISTYPED" in capsys.readouterr().out


# ---- versioning ----

def test_attribute_changes_are_diffed_and_their_impact_counted():
    old = vocab.Vocabulary.from_config(VOCAB)
    changed = json.loads(json.dumps(VOCAB))
    changed["attributes"]["Claim"].pop("amount")
    changed["attributes"]["Claim"]["state"] = ["string", "Where it is."]
    changed["attributes"]["Claim"]["priority"] = ["integer", "Urgency."]
    changes = vocab.impact(vocab.diff(old, vocab.Vocabulary.from_config(changed)),
                           [_node("c.1", amount=1), _node("c.2", amount=2, state="open")], [])
    by_kind = {c.kind: c for c in changes}
    assert by_kind["attribute removed"].severity == vocab.Change.BREAKING and by_kind["attribute removed"].affected == 2
    assert by_kind["attribute type changed"].affected == 1
    assert by_kind["attribute added"].severity == vocab.Change.ADDITIVE


# ---- export and import ----

def test_attributes_are_exported_as_datatype_properties_and_round_trip():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, [_node("c.1", claim_number="C-1", state="open")])
        build(project)
        ttl = open(os.path.join(project.layout.ontology, "kb.ttl"), encoding="utf-8").read()
        assert 'kb:claim_number a owl:DatatypeProperty ; rdfs:label "claim_number" ; rdfs:domain kb:Claim ; rdfs:range xsd:string' in ttl
        assert 'rdfs:comment "Where it is. (one of: open|closed)"' in ttl
        assert "rdfs:range xsd:date" in ttl and "rdfs:range xsd:decimal" in ttl
        md = open(os.path.join(project.layout.ontology, "ontology.md"), encoding="utf-8").read()
        assert "## Attributes" in md and "| `kb:Claim` | `state` | enum:open|closed |" in md
        ctx = json.load(open(os.path.join(project.layout.ontology, "kb.context.jsonld"), encoding="utf-8"))
        assert ctx["attributes"] == {"Claim": ["claim_number", "state", "amount", "opened_on"]}
        assert ctx["@context"]["opened_on"]["@type"].endswith("#date")

        classes, properties, notes = importer.read(os.path.join(project.layout.ontology, "kb.ttl"))
        assert importer.read.attributes == VOCAB["attributes"]
        assert importer.check(classes, properties, importer.read.attributes) == []


def test_csv_import_carries_attribute_rows(capsys):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Csv")
        path = os.path.join(root, "v.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("kind,name,description,domain,range,inverse\n"
                    "class,Machine,A machine.,,,\n"
                    "relation,near,Close to.,Machine,Machine,\n"
                    "attribute,serial,The serial number.,Machine,string,\n"
                    "attribute,installed_on,Install date.,Machine,date,\n")
        capsys.readouterr()
        assert main(["ontology", "import", "--project", root, "--file", path]) == 0
        assert "2 attribute declaration(s)" in capsys.readouterr().out
        config = json.load(open(os.path.join(root, "ontology.config.json"), encoding="utf-8"))
        assert config["attributes"] == {"Machine": {"serial": ["string", "The serial number."],
                                                    "installed_on": ["date", "Install date."]}}


# ---- ontologies ----

def test_the_claims_ontology_declares_attributes_and_its_sample_conforms():
    config, sample, _ = ontologies.load("auto-claims")
    assert config["attributes"]["Claim"]["state"][0].startswith("enum:")
    assert ontologies.self_check("auto-claims") == []
    report = vocab.attribute_conformance(vocab.Vocabulary.from_config(config), sample["nodes"])
    assert report["mistyped"] == [] and report["undeclared"] == [] and report["checked"] > 0


def test_a_ontology_with_a_bad_attribute_declaration_fails_its_self_check(tmp_path, monkeypatch):
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path))
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Src", ontology="auto-claims")
        project = Project.standard(root)
        ontologies.export(project, "bad")
        path = os.path.join(str(tmp_path), "bad", "ontology.config.json")
        config = json.load(open(path, encoding="utf-8"))
        config["attributes"]["Claim"]["state"] = ["money", "x"]
        json.dump(config, open(path, "w", encoding="utf-8"))
        assert any("unknown attribute type" in p for p in ontologies.self_check("bad"))


def test_an_exported_ontology_keeps_attributes_and_its_invented_sample_fits_them(tmp_path, monkeypatch):
    monkeypatch.setenv(ontologies.USER_DIR_ENV, str(tmp_path))
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Src", ontology="auto-claims")
        _path, problems = ontologies.export(Project.standard(root), "kept")
        assert problems == []
        config, sample, _ = ontologies.load("kept")
        assert config["attributes"]["Claim"]["state"][0].startswith("enum:")
        claim = next(n for n in sample["nodes"] if n["type"] == "Claim")
        assert claim["attributes"]["state"] == "open"


def test_merged_ontologies_union_their_attributes():
    config, _s, _r, _rat, _rep = ontologies.merge(["auto-claims", "organization-process"])
    assert "Claim" in config["attributes"]
