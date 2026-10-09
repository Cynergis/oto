"""The SPARQL rendering of the questions says what the engine says: every shipped question, run by
the engine over the graph and by rdflib over graph.ttl, gives the same rows."""
import datetime
import decimal
import json
import os
import tempfile

import pytest

from oto.builder import build
from oto.compile import sparql as _sparql
from oto.model import rdf_import
from oto.model.namespaces import Terms
from oto.model.vocabulary import covers
from oto.project import Project
from oto.reason import questions as Q
from oto.scaffold import init

pytestmark = pytest.mark.skipif(not rdf_import.available(), reason="needs rdflib (the `rdf` extra)")


def _value(term, terms, schemes):
    """An rdflib term as the engine would return it: an id, a concept key, or a plain value."""
    from rdflib import URIRef, Literal, BNode
    if term is None:
        return None
    if isinstance(term, URIRef):
        text = str(term)
        if text.startswith(terms.instances):
            return text[len(terms.instances):]
        local = text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        for scheme in schemes:
            if local.startswith(scheme + "."):
                return local[len(scheme) + 1:]
        return local
    if isinstance(term, BNode):
        from rdflib.collection import Collection
        return [_value(x, terms, schemes) for x in Collection(_value.graph, term)]
    if isinstance(term, Literal):
        value = term.toPython()
        if isinstance(value, decimal.Decimal):
            value = float(value)
        if isinstance(value, datetime.date):
            value = value.isoformat()
        return value
    return str(term)


def _rows(graph, query, select, terms, schemes):
    _value.graph = graph
    out = []
    for binding in graph.query(query):
        row = {}
        for item, value in zip(select, binding):
            row[item] = _value(value, terms, schemes)
        out.append(row)
    return out


def _same(engine_rows, sparql_rows):
    def key(row):
        return json.dumps({k: (v if not isinstance(v, float) else round(v, 6)) for k, v in row.items()}, sort_keys=True, default=str)
    return sorted(key(r) for r in engine_rows) == sorted(key(r) for r in sparql_rows)


@pytest.mark.parametrize("ontology", ["auto-claims", "software-architecture", "organization-process", "professional-services"])
def test_every_shipped_question_answers_the_same_in_sparql(ontology):
    from rdflib import Graph
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="eq", name="Equivalence", ontology=ontology)
        project = Project.standard(root)
        build(project)
        config = json.load(open(project.ontology_config_path, encoding="utf-8"))
        graph = json.load(open(os.path.join(project.layout.graph, "knowledge-graph.json"), encoding="utf-8"))
        nodes, edges = graph["nodes"], graph["edges"]
        terms = Terms(config, project.identity())
        schemes = list(config.get("schemes") or {})
        data = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        yaml_text = open(os.path.join(project.layout.ontology, "questions.yaml"), encoding="utf-8").read()
        questions = Q.load(project)
        assert questions
        cover = covers(config["classes"])
        compared = 0
        for qid, q in questions.items():
            renderer = _sparql.Renderer(config, terms)
            query = renderer.render(q)
            assert "\n".join("      " + line for line in query.splitlines()) in yaml_text, qid
            select = q["ask"]["select"]
            declared = q.get("params") or {}
            if not declared:
                engine = Q.run(qid, q, {}, nodes, edges, cover)["rows"]
                sparql_rows = _rows(data, query, select, terms, schemes)
                assert _same(engine, sparql_rows), "%s\nengine: %s\nsparql: %s\n%s" % (qid, engine, sparql_rows, query)
                compared += 1
                continue
            first = next(iter(declared))
            kinds = set()
            for one in declared[first]["type"].split("|"):
                kinds |= set(cover.get(one.strip(), {one.strip()}))
            for node in nodes:
                if node.get("type") not in kinds or node.get("status", "current") != "current":
                    continue
                engine = Q.run(qid, q, {first: node["id"]}, nodes, edges, cover)["rows"]
                bound = query.replace("$" + first, "<%s>" % terms.instance(node["id"]))
                sparql_rows = _rows(data, bound, select, terms, schemes)
                assert _same(engine, sparql_rows), "%s on %s\nengine: %s\nsparql: %s\n%s" % (qid, node["id"], engine, sparql_rows, bound)
                compared += 1
        assert compared >= len(questions)


def test_the_rendering_covers_the_pattern_language_and_notes_what_it_cannot():
    config = {"classes": {"Claim": {"definition": "c"}, "Task": {"definition": "t"}, "Thing": {"definition": "x"},
                          "Big": {"definition": "b", "subclass_of": ["Thing"]}},
              "properties": {"has_task": {"domain": "Claim", "range": "Task", "definition": "h"},
                             "near": {"domain": "Thing", "range": "Thing", "definition": "n"},
                             "touches": {"domain": "Thing", "range": "Thing", "definition": "t", "subproperty_of": "near"}},
              "attributes": {"Claim": {"state": {"type": "scheme:State", "definition": "s"}, "tags": {"type": "list", "definition": "l"},
                                       "amount": {"type": "number", "definition": "a"}}},
              "schemes": {"State": {"definition": "s", "concepts": {"open": {}, "closed": {}}}},
              "temporal": {"asOf": {"type": "date", "definition": "when"}, "status": {"type": "string", "definition": "s"}}}
    terms = Terms(config, {"slug": "t", "name": "T", "prefix": "t", "namespace": "https://t.example/kg/"})
    r = _sparql.Renderer(config, terms)
    query = r.render({"params": {"CLAIM": {"type": "Claim"}},
                      "ask": {"when": [{"node": "$CLAIM", "where": {"state": "open", "amount": {">": 10}, "tags": {"contains": "x"},
                                                                   "as_of": {">=": "$today-30d"}}},
                                       {"edge": ["$CLAIM", "has_task", "t"]}, {"node": "t", "type": "Task", "where": {"label": "Intake"}},
                                       {"not_edge": ["t", "near|touches", "*"]}, {"node": "b", "type": "Thing"},
                                       {"not_node": "x", "type": "Big"}],
                              "select": ["t", "t.label", "t.type", "t.id", "b.as_of", "$CLAIM.amount"]}})
    assert "$CLAIM t:state t:State.open" not in query and "FILTER(?CLAIM_state = t:State.open)" in query, "a scheme value is its concept"
    assert "FILTER(?CLAIM_amount > 10)" in query
    assert "# contains on tags: not rendered" in query and any("list attribute tags" in n for n in r.notes)
    assert '"%s"^^xsd:date' % (datetime.date.today() - datetime.timedelta(days=30)).isoformat() in query
    assert any("rendered as the date of the rendering" in n for n in r.notes)
    assert "$CLAIM t:has_task ?t ." in query and "?t a t:Task ." in query and 'FILTER(?t_label = "Intake")' in query
    assert "FILTER NOT EXISTS { ?t ?_" in query and "VALUES ?_" in query and "t:near t:touches" in query, "a relation and the ones that specialise it"
    assert "?b a ?_" in query and "t:Big t:Thing" in query, "a class covers the kinds of it"
    assert "FILTER NOT EXISTS { ?_absent a t:Big ." in query
    assert "SELECT DISTINCT ?t ?t_label ?t_type ?t_id ?b_as_of ?CLAIM_amount WHERE" in query
    assert "OPTIONAL { ?t rdfs:label ?t_label }" in query and "?t a ?t_type ." in query
    assert 'BIND(STRAFTER(STR(?t), "id/") AS ?t_id)' in query and "OPTIONAL { ?b t:asOf ?b_as_of }" in query
    assert "OPTIONAL { $CLAIM t:amount ?CLAIM_amount }" in query
    assert 'FILTER NOT EXISTS { $CLAIM t:status ?CLAIM_status . FILTER(?CLAIM_status NOT IN ("current")) }' in query
    text = _sparql.questions_yaml({"Q1": {"who": "me", "question": "What?", "why": "because", "gate": "empty",
                                          "ask": {"when": [{"node": "c", "type": "Claim"}], "select": ["c"]},
                                          "gaps": {"when": [{"node": "c", "type": "Claim"}], "say": "none"}}}, config, terms, "T")
    assert text.startswith("# Competency questions of the T vocabulary") and "  Q1:\n    who: \"me\"" in text
    assert "    answer: |\n      PREFIX" in text and "    gaps: |" in text and '    gaps_say: "none"' in text


def test_optional_exists_and_references_render_and_answer_alike():
    from rdflib import Graph
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="eq", name="Equivalence", ontology="software-architecture")
        project = Project.standard(root)
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        graph["nodes"].append(dict(id="repo.bare", type="Repository", label="bare", aliases=[], summary="s", attributes={"name": "bare"},
                                   tags=[], as_of="2026-01-01", valid_from="2026-01-01", source_doc="d", status="current", sources=["d"]))
        graph["edges"] = [e for e in graph["edges"] if not (e["rel"] == "runs_in" and e["from"] == "component.settlement-job")]
        json.dump(graph, open(project.graph_path, "w", encoding="utf-8"))
        questions = {
            "O1": {"who": "x", "question": "Which components exist, and where does each run?", "why": "w",
                   "ask": {"when": [{"node": "c", "type": "Component"},
                                    {"optional": [{"edge": ["c", "runs_in", "e"]}, {"node": "e", "type": "Environment"}]}],
                           "select": ["c", "e.label"]}, "gate": "non_empty"},
            "O2": {"who": "x", "question": "Which repositories have no URL?", "why": "w",
                   "ask": {"when": [{"node": "r", "type": "Repository", "where": {"url": {"exists": False}}}], "select": ["r", "r.name"]}, "gate": "any"},
            "O3": {"who": "x", "question": "Which components are not part of $SYSTEM?", "why": "w", "params": {"SYSTEM": {"type": "System"}},
                   "ask": {"when": [{"node": "c", "type": "Component"}, {"edge": ["c", "part_of", "s"]},
                                    {"node": "s", "type": "System", "where": {"id": {"!=": "$SYSTEM"}}}], "select": ["c"]}, "gate": "any"},
        }
        Q.save(project, dict(Q.load(project), **questions))
        build(project)
        config = json.load(open(project.ontology_config_path, encoding="utf-8"))
        built = json.load(open(os.path.join(project.layout.graph, "knowledge-graph.json"), encoding="utf-8"))
        terms = Terms(config, project.identity())
        data = Graph().parse(os.path.join(project.layout.graph, "graph.ttl"), format="turtle")
        cover = covers(config["classes"])
        for qid, q in questions.items():
            query = _sparql.Renderer(config, terms).render(q)
            if qid == "O1":
                assert "OPTIONAL { ?c software-architecture:runs_in ?e . ?e a software-architecture:Environment . FILTER NOT EXISTS { ?e" in query
            if qid == "O2":
                assert "FILTER NOT EXISTS { ?r software-architecture:url ?r_url }" in query
            if qid == "O3":
                assert "FILTER(?s != $SYSTEM)" in query
            params = {"SYSTEM": "system.payments"} if q.get("params") else {}
            engine = Q.run(qid, q, params, built["nodes"], built["edges"], cover)["rows"]
            bound = query.replace("$SYSTEM", "<%s>" % terms.instance("system.payments"))
            sparql_rows = _rows(data, bound, q["ask"]["select"], terms, [])
            assert _same(engine, sparql_rows), "%s\nengine: %s\nsparql: %s\n%s" % (qid, engine, sparql_rows, bound)
        assert {r["c"] for r in Q.run("O1", questions["O1"], {}, built["nodes"], built["edges"], cover)["rows"]} == \
            {"component.payment-api", "component.settlement-job"}
