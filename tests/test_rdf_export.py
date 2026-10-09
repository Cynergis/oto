"""The RDF export is RDF: instances typed with rdf:type, every term under the one IRI its ontology
declares in both `triples.nt` and the Turtle ontology, unions written as unions, values as typed
literals. Read back with rdflib, which is a test dependency only."""
import json
import os
import tempfile

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

from oto.builder import build
from oto.model import importer, namespaces, ontologies, ontology_manifest
from oto.project import Project, ProjectError
from oto.scaffold import init
from oto.validate.preflight import preflight

CORE = "https://cynergis.ai/ont/oto-core#"
META = "https://cynergis.ai/ont/meta#"
CLAIMS = "https://cynergis.ai/ont/auto-claims#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
STRUCTURAL = {RDF.type, RDFS.label, RDFS.comment, RDF.first, RDF.rest,
              URIRef(SKOS + "prefLabel"), URIRef(SKOS + "altLabel"), URIRef(SKOS + "hiddenLabel")}
STAMP = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "d", "status": "current", "sources": ["d"]}


def _read(root):
    """(project, vocabulary, compiled graph, terms, ontology as RDF, instances as RDF)."""
    project = Project.standard(root)
    build(project)
    slug = project.identity()["slug"]
    with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    with open(os.path.join(project.layout.graph, "knowledge-graph.json"), encoding="utf-8") as f:
        compiled = json.load(f)
    ontology = Graph().parse(os.path.join(project.layout.ontology, slug + ".ttl"), format="turtle")
    data = Graph().parse(os.path.join(project.layout.graph, "triples.nt"), format="nt")
    return project, config, compiled, namespaces.Terms(config, project.identity()), ontology, data


def _declared(ontology):
    classes = {s for s in ontology.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    properties = {s for kind in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property)
                  for s in ontology.subjects(RDF.type, kind)}
    return classes, properties


def _own(root, config, nodes, edges=()):
    """A project with its own vocabulary and graph, no ontology behind it."""
    init(root, name="KB")
    with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": list(edges)}, f)


def _node(nid, kind, label=None, summary="s", **attrs):
    return dict(id=nid, type=kind, label=label or nid, aliases=[], summary=summary, attributes=attrs, tags=[], **STAMP)


# ---- the ontology describes the graph ----

@pytest.mark.parametrize("name", ontologies.available())
def test_every_shipped_ontology_exports_a_graph_its_ontology_describes(name):
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Shipped", ontology=name)
        _project, config, compiled, terms, ontology, data = _read(root)
        classes, properties = _declared(ontology)

        assert set(data.objects(None, RDF.type)) <= classes, "an instance is typed with a class nobody declares"
        for kind in compiled["meta"]["node_types"]:
            counted = data.query("SELECT (COUNT(?s) AS ?n) WHERE { ?s a <%s> }" % terms.iri(kind))
            assert int(list(counted)[0][0]) == sum(n["type"] == kind for n in compiled["nodes"]), kind
        for edge in compiled["edges"]:
            assert (URIRef(terms.instance(edge["from"])), URIRef(terms.iri(edge["rel"])),
                    URIRef(terms.instance(edge["to"]))) in data

        # The only predicates the ontology does not declare are attributes the vocabulary leaves
        # undeclared on a class, which the build allows and `oto ontology check` reports.
        declared = config.get("attributes") or {}
        loose = {URIRef(terms.iri(key)) for n in compiled["nodes"]
                 for key, value in (n.get("attributes") or {}).items()
                 if value not in (None, "", [], {}) and key not in (declared.get(n["type"]) or {})}
        assert set(data.predicates()) - STRUCTURAL - properties == loose - properties

        for term in properties:
            assert len(list(ontology.objects(term, RDFS.domain))) <= 1, "several rdfs:domain values mean all of them"
            assert len(list(ontology.objects(term, RDFS.range))) <= 1


def test_a_union_domain_is_written_as_a_union():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Arch", ontology="software-architecture")
        _project, _config, _compiled, terms, ontology, _data = _read(root)
        domain = ontology.value(URIRef(terms.iri("part_of")), RDFS.domain)
        assert isinstance(domain, BNode) and (domain, RDF.type, OWL.Class) in ontology
        assert list(Collection(ontology, ontology.value(domain, OWL.unionOf))) == [
            URIRef(terms.iri(kind)) for kind in ("Feature", "JourneyStep", "Component", "Interface", "DataStore")]
        range_ = ontology.value(URIRef(terms.iri("part_of")), RDFS.range)
        assert list(Collection(ontology, ontology.value(range_, OWL.unionOf))) == [
            URIRef(terms.iri(kind)) for kind in ("Product", "Feature", "UserJourney", "System")]


# ---- one IRI per term ----

def test_a_term_keeps_the_iri_of_the_ontology_that_declared_it():
    exported = []
    for slug in ("first", "second"):
        with tempfile.TemporaryDirectory() as root:
            init(root, slug=slug, name=slug, ontology="auto-claims")
            with open(os.path.join(root, "ontology.config.json"), encoding="utf-8") as f:
                config = json.load(f)
            config["classes"]["Broker"] = {"definition": "An intermediary the project added itself."}
            with open(os.path.join(root, "ontology.config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f)
            _project, config, compiled, terms, ontology, data = _read(root)
            claim = next(n for n in compiled["nodes"] if n["type"] == "Claim")
            me = URIRef("https://%s.example/kg/id/%s" % (slug, claim["id"]))
            assert (me, RDF.type, URIRef(CLAIMS + "Claim")) in data
            assert data.value(me, URIRef(CORE + "asOf")) == Literal(claim["as_of"], datatype=XSD.date)
            assert (URIRef("https://%s.example/kg/ont/Broker" % slug), RDF.type, OWL.Class) in ontology
            exported.append({str(s) for s in _declared(ontology)[0] if "example" not in str(s)})
    assert exported[0] == exported[1] and CORE + "Document" in exported[0], "two projects share the ontology's IRIs"


def test_composition_records_which_ontology_brought_each_term():
    record = ontologies.composed("auto-claims")["config"]["namespaces"]
    assert record["oto-core"]["iri"] == CORE and record["oto-core"]["temporal"] is True
    assert "Document" in record["oto-core"]["terms"] and "Document" not in record["auto-claims"]["terms"]
    assert {"Claim", "Task", "state"} <= set(record["auto-claims"]["terms"])
    assert record["auto-claims"]["terms"].count("state") == 1, "an attribute two classes declare is one name"
    assert "temporal" not in record["auto-claims"]

    merged = ontologies.merge(["organization-process", "auto-claims"])[0]["namespaces"]
    assert list(merged) == ["oto-core", "organization-process", "auto-claims"]
    listed = [term for entry in merged.values() for term in entry["terms"]]
    assert len(listed) == len(set(listed)), "a term both ontologies declare belongs to the first"
    assert namespaces.problems({"namespaces": merged}) == []


def test_an_exported_ontology_keeps_the_iris_its_terms_already_had():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as catalog:
        init(root, slug="acme", name="Acme", ontology="auto-claims")
        target, problems = ontologies.export(Project.standard(root), "acme-claims", to=catalog)
        assert problems == []
        assert ontologies.manifest_dir(target)["namespace"] == "https://acme.example/kg/ont/"
        record = ontologies.composed(target)["config"]["namespaces"]
        assert "Claim" in record["auto-claims"]["terms"] and record["auto-claims"]["iri"] == CLAIMS
        assert record["oto-core"]["temporal"] is True


def test_a_vocabulary_with_no_namespaces_is_the_projects_own():
    with tempfile.TemporaryDirectory() as root:
        _own(root, {"classes": {"Claim": {"definition": "A claim."}}, "properties": {"follows": {"domain": "Claim", "range": "Claim", "definition": "After."}},
                    "temporal": {"asOf": {"type": "date", "definition": "When recorded."}, "status": {"type": "string", "definition": "State."},
                                 "validFrom": {"type": "date", "definition": "From."}, "sourceDoc": {"type": "string", "definition": "Source."}}},
             [_node("c.1", "Claim"), _node("c.2", "Claim")], [{"from": "c.2", "rel": "follows", "to": "c.1"}])
        _project, _config, _compiled, _terms, ontology, data = _read(root)
        base = "https://kb.example/kg/"
        assert (URIRef(base + "id/c.1"), RDF.type, URIRef(base + "ont/Claim")) in data
        assert (URIRef(base + "id/c.2"), URIRef(base + "ont/follows"), URIRef(base + "id/c.1")) in data
        assert set(data.predicates()) - STRUCTURAL <= _declared(ontology)[1]


def test_a_malformed_namespace_is_refused():
    assert namespaces.iri_problem("https://example.org/ont/claims#", "x") is None
    assert namespaces.iri_problem("https://example.org/ont/claims", "x") and namespaces.iri_problem("claims#", "x")
    assert any("listed under both" in p for p in namespaces.problems({"namespaces": {
        "a": {"iri": "https://a.example/#", "terms": ["Claim"]}, "b": {"iri": "https://b.example/#", "terms": ["Claim"]}}}))
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "claims"))
        with open(os.path.join(root, "claims", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "claims", "namespace": "claims"}, f)
        assert any("namespace" in p for p in ontology_manifest.problems(os.path.join(root, "claims")))
    with tempfile.TemporaryDirectory() as root:
        _own(root, {"classes": {"Claim": {"definition": "A claim."}}, "properties": {}, "temporal": {},
                    "namespaces": {"claims": {"iri": "not an iri", "terms": ["Claim"]}}}, [_node("c.1", "Claim")])
        with pytest.raises(ProjectError, match="namespaces.claims.iri"):
            preflight(Project.standard(root))


def test_every_shipped_ontology_declares_its_namespace():
    for name in ontologies.available():
        assert ontologies.manifest_for(name)["namespace"] == "https://cynergis.ai/ont/%s#" % name


# ---- values ----

VOCAB = {"classes": {"Claim": {"definition": 'A claim, or "file", as handlers say.\\ Kept for seven years.'}, "Task": {"definition": "Work to do."}},
         "properties": {"part_of": {"domain": "Task", "range": "Claim", "definition": "The claim a task serves."}},
         "attributes": {"Claim": {"claim_number": {"type": "string", "definition": "The identifier."},
                                  "state": {"type": "enum:open|closed", "definition": "Where the claim is."},
                                  "amount": {"type": "number", "definition": "Reserve."},
                                  "reviews": {"type": "integer", "definition": "Times reviewed."},
                                  "disputed": {"type": "boolean", "definition": "Contested by a party."},
                                  "opened_on": {"type": "date", "definition": "When it was opened."},
                                  "handlers": {"type": "list", "definition": "Who handled it, in order."}},
                        "Task": {"state": {"type": "enum:todo|done", "definition": "Where the task is."}}},
         "temporal": {}}


def test_attributes_and_summaries_are_exported_as_typed_values():
    with tempfile.TemporaryDirectory() as root:
        _own(root, VOCAB, [
            _node("c.1", "Claim", label='The "glass" claim', summary="Line one.\nLine two.", claim_number="C-1",
                  state="open", amount=12.5, reviews=3, disputed=False, opened_on="2026-03-14",
                  handlers=["ana", "raj", "ana"], extra={"b": 1, "a": [True]}, note="", gone=None),
            _node("t.1", "Task", state="todo")])
        project, _config, _compiled, terms, ontology, data = _read(root)
        me = URIRef(terms.instance("c.1"))
        value = lambda key: data.value(me, URIRef(terms.iri(key)))

        assert data.value(me, RDFS.label) == Literal('The "glass" claim')
        assert data.value(me, RDFS.comment) == Literal("Line one.\nLine two.", lang="en")
        assert value("claim_number") == Literal("C-1") and value("state") == Literal("open")
        assert value("amount") == Literal("12.5", datatype=XSD.decimal)
        assert value("reviews") == Literal("3", datatype=XSD.integer)
        assert value("disputed") == Literal("false", datatype=XSD.boolean)
        assert value("opened_on") == Literal("2026-03-14", datatype=XSD.date)
        assert [str(x) for x in Collection(data, value("handlers"))] == ["ana", "raj", "ana"], "a list keeps its order"
        assert value("extra") == Literal('{"a":[true],"b":1}', datatype=RDF.JSON)
        assert value("note") is None and value("gone") is None, "an empty value states nothing"

        handlers, state = URIRef(terms.iri("handlers")), URIRef(terms.iri("state"))
        assert (handlers, RDF.type, OWL.ObjectProperty) in ontology and ontology.value(handlers, RDFS.range) == RDF.List
        assert (state, RDF.type, OWL.DatatypeProperty) in ontology and ontology.value(state, RDFS.range) == XSD.string
        assert list(Collection(ontology, ontology.value(ontology.value(state, RDFS.domain), OWL.unionOf))) == [
            URIRef(terms.iri("Claim")), URIRef(terms.iri("Task"))]
        assert set(ontology.objects(state, RDFS.comment)) == {
            Literal("Claim: Where the claim is. (one of: open|closed)", lang="en"), Literal("Task: Where the task is. (one of: todo|done)", lang="en")}
        assert ontology.value(URIRef(terms.iri("Claim")), RDFS.comment) == Literal(VOCAB["classes"]["Claim"]["definition"], lang="en")

        # The Turtle still reads back into the vocabulary it was written from.
        classes, _properties, notes = importer.read(os.path.join(project.layout.ontology, "kb.ttl"))
        assert classes == VOCAB["classes"] and importer.read.attributes == VOCAB["attributes"] and notes == []

        first = open(os.path.join(project.layout.graph, "triples.nt"), encoding="utf-8").read()
        build(project)
        assert open(os.path.join(project.layout.graph, "triples.nt"), encoding="utf-8").read() == first


def test_the_jsonld_context_names_the_iris_the_turtle_declares():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Claims", ontology="auto-claims")
        project, config, _compiled, terms, ontology, _data = _read(root)
        with open(os.path.join(project.layout.ontology, "claims.context.jsonld"), encoding="utf-8") as f:
            context = json.load(f)["@context"]

        def expanded(term):
            target = context[term]["@id"]
            prefix, _, local = target.partition(":")
            return URIRef(context[prefix] + local if isinstance(context.get(prefix), str) else target)

        classes, properties = _declared(ontology)
        for kind in config["classes"]:
            assert expanded(kind) == URIRef(terms.iri(kind)) and expanded(kind) in classes
        for relation in set(config["properties"]) - set(config["temporal"]):
            assert expanded(relation) == URIRef(terms.iri(relation)) and expanded(relation) in properties
        # A node's own `supersedes` is the temporal one, whatever relation shares the name.
        assert expanded("supersedes") == URIRef(CORE + "supersedes") and expanded("asOf") == URIRef(CORE + "asOf")
        assert expanded("state") == URIRef(CLAIMS + "state")


# ---- what the terms are called ----

def test_terms_carry_their_labels_definitions_and_reasoning():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Arch", ontology="software-architecture")
        project, _config, _compiled, terms, ontology, data = _read(root)
        component, part_of = URIRef(terms.iri("Component")), URIRef(terms.iri("part_of"))
        pref = URIRef(SKOS + "prefLabel")
        assert ontology.value(component, pref) == Literal("component", lang="en")
        assert ontology.value(component, RDFS.label) == Literal("component", lang="en")
        assert ontology.value(component, URIRef(SKOS + "definition")) == ontology.value(component, RDFS.comment)
        assert ontology.value(component, URIRef(META + "question")) == Literal("What actually gets deployed, and what does it touch?")
        assert ontology.value(component, URIRef(META + "rationale")) and ontology.value(component, URIRef(META + "alternatives"))
        assert ontology.value(component, URIRef(META + "validatedBy")) is None, "nobody has confirmed it, so nothing says so"
        assert ontology.value(part_of, pref) == Literal("part of", lang="en")
        contains = URIRef(terms.iri("contains", beside="part_of"))
        assert (contains, RDF.type, OWL.ObjectProperty) in ontology and ontology.value(contains, OWL.inverseOf) == part_of
        assert ontology.value(contains, pref) == Literal("contains", lang="en"), "an inverse is a property with its own label"
        assert ontology.value(URIRef(terms.iri("url")), pref) == Literal("URL", lang="en")
        assert (URIRef(META + "rationale"), RDF.type, OWL.AnnotationProperty) in ontology

        # the instances: a preferred label, aliases as alternative labels, in Turtle and N-Triples alike
        api = URIRef(terms.instance("component.payment-api"))
        assert data.value(api, pref) == Literal("Payment API", lang="en")
        from rdflib.compare import isomorphic
        turtle = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        assert isomorphic(turtle, data), "graph.ttl says exactly what triples.nt says"
        assert "id:component.payment-api" in open(os.path.join(project.layout.graph, "graph.ttl"), encoding="utf-8").read()

        reference = open(os.path.join(project.layout.ontology, "ontology.md"), encoding="utf-8").read()
        assert "| Class | Label | A kind of | Definition | Why it exists | Confirmed by |" in reference
        assert "`contains` (contains)" in reference and "- `Asset`\n  - `System`" in reference

        # the hierarchy: a kind of, in the Turtle and read back into the vocabulary
        asset = URIRef(terms.iri("Asset"))
        assert ontology.value(component, RDFS.subClassOf) == asset and (asset, RDF.type, OWL.Class) in ontology
        classes, _properties, _notes = importer.read(os.path.join(project.layout.ontology, "arch.ttl"))
        assert classes["Component"]["subclass_of"] == ["Asset"] and "subclass_of" not in classes["Asset"]


def test_several_languages_round_trip_through_the_export():
    config = {"languages": ["en", "fr"],
              "classes": {"Machine": {"definition": {"en": "A machine.", "fr": "Une machine."}, "label": {"en": "machine", "fr": "machine"},
                                      "alt_labels": {"en": ["press"], "fr": ["presse"]}, "example": "the stamping press"},
                          "Site": {"definition": "A place.", "label": {"fr": "site"}}},
              "properties": {"installed_at": {"domain": "Machine", "range": "Site", "inverse": "hosts", "definition": "Where it runs.",
                                              "label": {"en": "installed at", "fr": "installée à"},
                                              "inverse_label": {"en": "hosts", "fr": "héberge"}, "scope_note": "Permanent installation only."}},
              "attributes": {"Machine": {"serial": {"type": "string", "definition": {"en": "The number.", "fr": "Le numéro."},
                                                    "label": "serial number"}}},
              "temporal": {}}
    with tempfile.TemporaryDirectory() as root:
        node = _node("m.1", "Machine", label="Press 01", serial="X-9")
        node.update(aliases=["Press One"], labels={"fr": "Presse 01"}, hidden_labels=["PRS-01"])
        _own(root, config, [node, _node("s.1", "Site")], [{"from": "m.1", "rel": "installed_at", "to": "s.1"}])
        with open(os.path.join(root, "lexicon.json"), "w", encoding="utf-8") as f:
            json.dump({"entries": [{"term": "the big press", "aka": ["BP"], "targets": ["m.1"], "status": "current", "note": ""}]}, f)
        project, _config, _compiled, terms, ontology, data = _read(root)
        machine, pref = URIRef(terms.iri("Machine")), URIRef(SKOS + "prefLabel")
        assert set(ontology.objects(machine, pref)) == {Literal("machine", lang="en"), Literal("machine", lang="fr")}
        assert set(ontology.objects(machine, URIRef(SKOS + "altLabel"))) == {Literal("press", lang="en"), Literal("presse", lang="fr")}
        assert set(ontology.objects(machine, URIRef(SKOS + "definition"))) == {Literal("A machine.", lang="en"), Literal("Une machine.", lang="fr")}
        assert ontology.value(machine, URIRef(SKOS + "example")) == Literal("the stamping press", lang="en")
        hosts = URIRef(terms.iri("hosts"))
        assert set(ontology.objects(hosts, pref)) == {Literal("hosts", lang="en"), Literal("héberge", lang="fr")}
        me = URIRef(terms.instance("m.1"))
        assert set(data.objects(me, pref)) == {Literal("Press 01", lang="en"), Literal("Presse 01", lang="fr")}
        assert set(data.objects(me, URIRef(SKOS + "altLabel"))) == {Literal("Press One", lang="en"), Literal("the big press", lang="en"), Literal("BP", lang="en")}
        assert data.value(me, URIRef(SKOS + "hiddenLabel")) == Literal("PRS-01")

        classes, properties, notes = importer.read(os.path.join(project.layout.ontology, "kb.ttl"))
        assert notes == [] and classes == config["classes"] and properties == config["properties"]
        assert importer.read.attributes == config["attributes"]


def test_controlled_values_are_concepts_in_the_export_and_come_back():
    with tempfile.TemporaryDirectory() as root:
        init(root, name="Claims", ontology="auto-claims")
        project, config, compiled, terms, ontology, data = _read(root)
        scheme, state = URIRef(terms.iri("ClaimState")), URIRef(terms.iri("state"))
        open_ = URIRef(terms.iri("ClaimState.open", beside="ClaimState"))
        reopened = URIRef(terms.iri("ClaimState.reopened", beside="ClaimState"))
        assert (scheme, RDF.type, URIRef(SKOS + "ConceptScheme")) in ontology and (scheme, URIRef(SKOS + "hasTopConcept"), open_) in ontology
        assert (open_, RDF.type, URIRef(SKOS + "Concept")) in ontology and ontology.value(open_, URIRef(SKOS + "inScheme")) == scheme
        assert ontology.value(open_, URIRef(SKOS + "prefLabel")) == Literal("Open", lang="en")
        assert ontology.value(reopened, URIRef(SKOS + "broader")) == open_ and (reopened, URIRef(SKOS + "topConceptOf"), scheme) not in ontology
        assert (state, RDF.type, OWL.ObjectProperty) in ontology, "a concept-valued attribute is an object property"
        claim = next(n for n in compiled["nodes"] if n["type"] == "Claim")
        assert data.value(URIRef(terms.instance(claim["id"])), state) == URIRef(terms.iri("ClaimState." + claim["attributes"]["state"], beside="ClaimState"))

        classes, _properties, notes = importer.read(os.path.join(project.layout.ontology, "claims.ttl"))
        assert notes == [] and importer.read.schemes == config["schemes"] and importer.read.attributes == config["attributes"]

