"""The rdflib reader (the `rdf` extra): a real ontology comes in with every term, label, definition,
union, parent and scheme, each term keeping its IRI, and what cannot be held is reported. The
acceptance is the report ontology: three namespaces in two files, union domains, a class that is a
kind of an external one, names declared twice."""
import json
import os
import tempfile

from rdflib import BNode, Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from oto.builder import build
from oto.model import importer, ontologies, rdf_import
from oto.project import Project
from oto.scaffold import init

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "report-ontology")
FILES = [os.path.join(FIXTURE, "report.ttl"), os.path.join(FIXTURE, "ontology.ttl")]
RPT, FLOW, DT = "https://cynergis.ai/ont/report#", "https://cynergis.ai/ont/flow#", "https://cynergis.ai/ont/doctemplate#"


def _source():
    g = Graph()
    for path in FILES:
        g.parse(path, format="turtle")
    return g


def _members(g, node):
    if node is None:
        return set()
    union = g.value(node, OWL.unionOf) if isinstance(node, BNode) else None
    return set(Collection(g, union)) if union is not None else {node}


def test_every_term_of_the_report_ontology_comes_in_and_keeps_its_iri():
    classes, properties, notes = rdf_import.read(FILES)
    source = _source()
    declared = {s for s in source.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    assert len(classes) == len(declared), "every class, including the seven names two namespaces declare"
    assert classes["ReportType"]["label"] == "Report type"
    assert classes["ReportType"]["definition"].startswith("A family of documents sharing one purpose")
    assert classes["rpt_Field"]["definition"].startswith("A piece of information the report shows") and "Field" in classes
    assert properties["hasParameter"]["domain"] == "ReportType|TemplateRelease" and properties["hasParameter"]["range"] == "rpt_Parameter"
    assert properties["inSection"]["inverse"] == "rpt_hasField" and properties["ofReport"]["inverse"] == "releasedAs"
    assert classes["DeterministicStep"]["subclass_of"] == ["Step"], "a parent in the file is kept"
    assert "subclass_of" not in classes["Run"] and any("Run' is a kind of <http://www.w3.org/ns/prov#Activity>" in n for n in notes)
    assert rdf_import.read.attributes["Run"]["flowVersion"]["type"] == "string" and rdf_import.read.attributes["Schedule"]["cadence"]
    assert rdf_import.read.attributes["Rule"]["regulatory"]["type"] == "boolean" and rdf_import.read.attributes["TemplateRelease"]["frozen"]["type"] == "boolean"
    assert rdf_import.read.attributes["ApprovalPolicy"]["sampleMin"]["type"] == "integer"
    assert rdf_import.read.rationale["classes"]["Revision"]["why"].startswith("Without it a corrected meaning")
    spaces = rdf_import.read.namespaces
    assert {k: v["iri"] for k, v in spaces.items()} == {"rpt": RPT, "flow": FLOW, "dt": DT}
    assert spaces["rpt"]["renamed"]["rpt_Field"] == "Field" and "Field" in spaces["flow"]["terms"]
    assert any("declared in two namespaces" in n for n in notes) and any("xsd:dateTime, read as string" in n for n in notes)
    assert importer.check(classes, properties, rdf_import.read.attributes, rdf_import.read.schemes) == []


def test_the_report_ontology_exports_back_as_it_came():
    classes, properties, _notes = rdf_import.read(FILES)
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="reports", name="Reports")
        importer.apply(Project.standard(root), classes, properties, rationale=rdf_import.read.rationale, replace=True,
                       attributes=rdf_import.read.attributes, namespaces=rdf_import.read.namespaces, schemes=rdf_import.read.schemes)
        with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
            config = json.load(f)
        with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
            json.dump(ontologies.synthetic_sample(config), f)
        project = Project.standard(root)
        build(project)
        exported = Graph().parse(os.path.join(project.layout.ontology, "reports.ttl"), format="turtle")
    source = _source()

    for cls in (s for s in source.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)):
        assert (cls, RDF.type, OWL.Class) in exported, cls
        if source.value(cls, SKOS.definition) is not None:
            assert str(exported.value(cls, SKOS.definition)) == str(source.value(cls, SKOS.definition)), cls
        assert str(exported.value(cls, SKOS.prefLabel)) == str(source.value(cls, RDFS.label)), cls
        parents = {p for p in source.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef) and (p, RDF.type, OWL.Class) in source}
        assert set(exported.objects(cls, RDFS.subClassOf)) == parents, cls
    for prop in (s for s in source.subjects(RDF.type, OWL.ObjectProperty) if isinstance(s, URIRef)):
        assert (prop, RDF.type, OWL.ObjectProperty) in exported, prop
        for side in (RDFS.domain, RDFS.range):
            wanted = {m for m in _members(source, source.value(prop, side)) if (m, RDF.type, OWL.Class) in source}
            assert _members(exported, exported.value(prop, side)) == wanted, (prop, side)
        if source.value(prop, OWL.inverseOf) is not None:
            assert exported.value(prop, OWL.inverseOf) == source.value(prop, OWL.inverseOf), prop
    for prop in (s for s in source.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(s, URIRef)):
        assert (prop, RDF.type, OWL.DatatypeProperty) in exported, prop
        assert _members(exported, exported.value(prop, RDFS.domain)) == _members(source, source.value(prop, RDFS.domain)), prop
    assert exported.value(URIRef(RPT + "Revision"), URIRef("https://cynergis.ai/ont/meta#rationale")) is not None
