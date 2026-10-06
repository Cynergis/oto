"""Competency questions that run: declared in questions.json in the pattern language of rules.json,
checked against the vocabulary before anything runs, executed over the graph with parameters bound,
gated so an empty answer means something, carried by the store so a reader asks them through
kg_ask and kg_questions without the project beside it."""
import json
import os
import subprocess
import sys
import tempfile

import pytest

from oto.builder import build
from oto.model.vocabulary import covers
from oto.project import Project, ProjectError
from oto.reason import questions as Q
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH = os.path.join(REPO, "oto", "ontologies", "software-architecture")

QUESTIONS = {
    "CQ1": {"who": "an on-call engineer",
            "question": "Which components make up $SYSTEM, and where does each run?",
            "why": "An incident starts from a system and needs its parts in front of the responder.",
            "validated_by": "",
            "params": {"SYSTEM": {"type": "System"}},
            "ask": {"when": [{"edge": ["c", "part_of", "$SYSTEM"]}, {"node": "c", "type": "Component"},
                             {"edge": ["c", "runs_in", "e"]}],
                    "select": ["c", "c.label", "e.label"]},
            "gate": "non_empty",
            "gaps": {"when": [{"not_edge": ["*", "part_of", "$SYSTEM"]}], "say": "no component is part of the system"},
            "terms": ["Environment"]},
    "CQ2": {"who": "an architect",
            "question": "Which data stores have no recorded decision behind them?",
            "why": "A store nobody decided on is a store nobody can retire.",
            "ask": {"when": [{"node": "d", "type": "DataStore"}, {"not_edge": ["d", "decided_by", "*"]}],
                    "select": ["d"]},
            "gate": "empty"},
    "CQ3": {"who": "a risk owner",
            "question": "Which risks threaten which assets, and what mitigates each?",
            "why": "The risk register must be readable from the graph alone.",
            "ask": {"when": [{"edge": ["r", "threatens", "a"]}, {"node": "a", "type": "Asset"},
                             {"edge": ["r", "mitigated_by", "m"]}],
                    "select": ["r.label", "a.label", "a.type", "m.label"]},
            "gate": "non_empty"},
}


def _vocabulary():
    with open(os.path.join(ARCH, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _sample():
    with open(os.path.join(ARCH, "sample.graph.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------- the model ----------------

def test_a_usable_question_set_has_no_problems_and_cites_its_terms():
    vocabulary = _vocabulary()
    assert Q.problems(QUESTIONS, vocabulary) == []
    cited = Q.terms_cited(QUESTIONS, vocabulary)
    assert cited["System"] == ["CQ1"] and cited["part_of"] == ["CQ1"] and cited["Environment"] == ["CQ1"]
    assert cited["DataStore"] == ["CQ2"] and cited["Asset"] == ["CQ3"] and "mitigated_by" in cited
    left = Q.uncovered(QUESTIONS, vocabulary)
    assert "Team" in left and "owned_by" in left and "Repository.url" in left
    assert "System" not in left and "Asset" not in left


def test_problems_name_what_cannot_run():
    vocabulary = _vocabulary()
    bad = {
        "Q1": {"question": "x", "why": "y", "ask": {"when": [{"node": "n", "type": "Nope"}], "select": ["n"]}},
        "Q2": {"question": "x", "why": "y", "ask": {"when": [{"edge": ["$P", "part_of", "s"]}], "select": ["s"]}},
        "Q3": {"question": "x", "why": "y", "ask": {"when": [{"node": "n", "type": "System"}], "select": ["m"]}},
        "Q4": {"question": "x", "why": "y", "gate": "maybe", "ask": {"when": [{"node": "n", "type": "System"}], "select": ["n"]}},
        "Q5": {"question": "x", "why": "y", "ask": {"when": [{"node": "n", "type": "Repository"}], "select": ["n.colour"]}},
        "Q6": {"question": "x", "why": "y", "params": {"S": {"type": "System"}},
               "ask": {"when": [{"edge": ["c", "part_of", "$S"]}], "select": ["c"]},
               "gaps": {"when": [{"not_edge": ["*", "part_of", "$S"]}]}},
        "Q7": {"question": "x", "ask": {"when": [{"node": "n", "type": "System"}], "select": ["n"]}, "terms": ["Gizmo"]},
        "Q8": {"question": "", "why": "y", "ask": {"when": [], "select": []}},
    }
    found = "\n".join(Q.problems(bad, vocabulary))
    assert "class 'Nope' is not declared" in found
    assert "$P is used in `ask` but not declared in `params`" in found
    assert "select 'm' names a variable `ask.when` does not bind" in found
    assert "gate must be one of non_empty, empty, any" in found
    assert "Repository declares no attribute 'colour'" in found
    assert "`gaps.say` must say, in words, why the answer is empty" in found
    assert "term 'Gizmo' is neither a class nor a relation" in found and "'Q7' has no `why`" in found
    assert "'Q8' has no `question`" in found and "`ask.when` must be a non-empty list" in found


def test_a_question_runs_with_its_parameter_bound_and_reads_labels_and_attributes():
    vocabulary, graph = _vocabulary(), _sample()
    result = Q.run("CQ1", QUESTIONS["CQ1"], {"SYSTEM": "system.payments"}, graph["nodes"], graph["edges"],
                   covers(vocabulary["classes"]))
    assert result["status"] == "answered" and result["params"] == {"SYSTEM": "system.payments"}
    assert result["question"] == "Which components make up Payments platform, and where does each run?"
    assert result["rows"] == [
        {"c": "component.payment-api", "c.label": "Payment API", "e.label": "Production"},
        {"c": "component.settlement-job", "c.label": "Settlement job", "e.label": "Production"}]
    assert result["gaps"] == []
    text = Q.result_text(result)
    assert text.startswith("CQ1 (an on-call engineer): Which components make up Payments platform")
    assert "status: answered" in text and "c=component.payment-api  c.label=Payment API  e.label=Production" in text


def test_an_empty_answer_is_explained_by_the_gaps_query_and_the_gate_decides_what_it_means():
    vocabulary, graph = _vocabulary(), _sample()
    cov = covers(vocabulary["classes"])
    lonely = dict(id="system.lonely", type="System", label="Lonely system", status="current", attributes={})
    nodes = graph["nodes"] + [lonely]
    result = Q.run("CQ1", QUESTIONS["CQ1"], {"SYSTEM": "system.lonely"}, nodes, graph["edges"], cov)
    assert result["status"] == "unanswered" and result["rows"] == []
    assert result["gaps"] == ["no component is part of the system"]
    assert "  gap: no component is part of the system" in Q.result_text(result)
    # an `empty` gate: nothing matching is the good outcome, a row is a violation
    clean = Q.run("CQ2", QUESTIONS["CQ2"], {}, graph["nodes"], graph["edges"], cov)
    assert clean["status"] == "clean" and clean["rows"] == []
    edges = [e for e in graph["edges"] if e["rel"] != "decided_by"]
    violated = Q.run("CQ2", QUESTIONS["CQ2"], {}, graph["nodes"], edges, cov)
    assert violated["status"] == "violated" and violated["rows"] == [{"d": "datastore.ledger"}]
    # a class pattern covers the kinds of it, so Asset finds the DataStore the risk threatens
    register = Q.run("CQ3", QUESTIONS["CQ3"], {}, graph["nodes"], graph["edges"], cov)
    assert register["rows"] == [{"r.label": "The ledger is a single point of failure", "a.label": "Ledger database",
                                 "a.type": "DataStore", "m.label": "Recovering a failed settlement run"}]


def test_the_survey_runs_every_question_over_the_whole_graph():
    vocabulary, graph = _vocabulary(), _sample()
    cov = covers(vocabulary["classes"])
    lonely = dict(id="system.lonely", type="System", label="Lonely system", status="current", attributes={})
    entries = Q.survey(QUESTIONS, graph["nodes"] + [lonely], graph["edges"], cov)
    by_id = {e["id"]: e for e in entries}
    assert by_id["CQ1"]["asked"] == 2 and by_id["CQ1"]["answered"] == 1 and by_id["CQ1"]["status"] == "unanswered"
    assert by_id["CQ1"]["unanswered"] == [{"node": "system.lonely", "label": "Lonely system", "status": "unanswered",
                                           "gaps": ["no component is part of the system"]}]
    assert by_id["CQ2"]["status"] == "clean" and by_id["CQ3"]["status"] == "answered"
    assert [e["id"] for e in Q.findings(QUESTIONS, graph["nodes"] + [lonely], graph["edges"], cov)] == ["CQ1"]
    assert Q.findings(QUESTIONS, graph["nodes"], graph["edges"], cov) == []
    text = Q.survey_text(entries)
    assert "CQ1    unanswered (1 of 2)" in text and "unanswered: Lonely system; no component is part of the system" in text
    assert "CQ2    clean" in text and text.endswith("3 question(s); 1 the graph cannot answer as required")
    # a parameter with nothing to bind to is reported, not silently answered
    no_systems = [n for n in graph["nodes"] if n["type"] != "System"]
    unasked = {e["id"]: e for e in Q.survey(QUESTIONS, no_systems, graph["edges"], cov)}["CQ1"]
    assert unasked["status"] == "unasked" and unasked["gaps"] == ["no System in the graph to ask about"]
    assert Q.survey_text([]) == "no competency questions declared (questions.json absent or empty)"


# ---------------- the project, the store, the server ----------------

def _project(root, questions=QUESTIONS, keep_shipped=False):
    init(root, slug="arch", name="Arch", ontology="software-architecture")
    project = Project.standard(root)
    Q.save(project, dict(Q.load(project), **questions) if keep_shipped else questions)
    return project


def _query(root, *args):
    r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", root] + list(args),
                       cwd=REPO, env=dict(os.environ, PYTHONPATH=REPO), capture_output=True, text=True)
    return r.stdout


def test_the_build_refuses_a_question_that_cannot_run():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, {"Q1": {"question": "x", "why": "y",
                                         "ask": {"when": [{"node": "n", "type": "Nope"}], "select": ["n"]}}})
        with pytest.raises(ProjectError) as exc:
            build(project)
        assert "class 'Nope' is not declared" in str(exc.value)


def test_the_store_carries_the_questions_and_the_server_runs_them():
    from oto.serve.store import SqliteStore
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        store = SqliteStore(project.layout.database)
        try:
            assert "questions" in store.features()
            assert list(store.questions()) == ["CQ1", "CQ2", "CQ3"] and store.questions()["CQ1"]["who"] == "an on-call engineer"
        finally:
            store.close()
        listed = _query(root, "questions")
        assert "CQ1    answered" in listed and "CQ2    clean" in listed and "CQ3    answered" in listed
        assert listed.rstrip().endswith("3 question(s); the graph answers every one it must")
        answer = _query(root, "ask", "CQ1", "SYSTEM=Payments platform")       # a parameter by label
        assert "Which components make up Payments platform" in answer and "status: answered" in answer
        assert "c=Payment API  c.label=Payment API  e.label=Production" in answer, "ids in the rows are shown by label"
        assert "Question CQ1 needs SYSTEM (a System). Pass it as params." in _query(root, "ask", "CQ1")
        assert "No entity matched 'nothing-xyz' for SYSTEM." in _query(root, "ask", "CQ1", "SYSTEM=nothing-xyz")
        assert "No question 'CQ9'; declared: CQ1, CQ2, CQ3" in _query(root, "ask", "CQ9")


def test_kg_ask_and_kg_questions_over_json_rpc_and_http():
    import importlib
    import urllib.request
    from oto.serve import http as _http
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        build(project)
        os.environ["OTO_DB"] = project.layout.database
        os.environ["OTO_PROJECT_CONFIG"] = project.config_path
        os.environ.pop("OTO_STORE", None)
        from oto.serve import engine
        importlib.reload(engine)
        names = [t["name"] for t in engine.TOOLS]
        assert "kg_ask" in names and "kg_questions" in names
        msg = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "kg_ask", "arguments": {"id": "CQ1", "params": {"SYSTEM": "system.payments"}}}})
        text = "".join(c["text"] for c in msg["result"]["content"])
        assert "status: answered" in text and "e.label=Production" in text
        msg = engine.respond({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "kg_questions", "arguments": {}}})
        assert "CQ3    answered" in "".join(c["text"] for c in msg["result"]["content"])

        server = _http.Server(engine, "127.0.0.1", 0, app_dir=None, project_root=root, identity=project.config()).start()
        try:
            with urllib.request.urlopen(server.url + "/api/ask?id=CQ1&SYSTEM=system.payments", timeout=10) as r:
                answer = json.loads(r.read())
            assert answer["tool"] == "kg_ask" and answer["data"]["status"] == "answered"
            assert answer["data"]["rows"][0]["c.label"] == "Payment API" and answer["data"]["labels"]["component.payment-api"] == "Payment API"
            with urllib.request.urlopen(server.url + "/api/questions", timeout=10) as r:
                answer = json.loads(r.read())
            assert [e["id"] for e in answer["data"]["rows"]] == ["CQ1", "CQ2", "CQ3"] and answer["data"]["rows"][1]["status"] == "clean"
        finally:
            server.stop()


def test_a_store_without_questions_says_so():
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="arch", name="Arch", ontology="software-architecture")
        os.remove(os.path.join(root, "questions.json"))              # the shipped ontology installs its questions
        build(Project.standard(root))
        assert _query(root, "questions").strip() == "no competency questions declared (questions.json absent or empty)"
        assert "No competency questions" in _query(root, "ask", "CQ1")


# ---------------- the ontology unit ----------------

def test_the_shipped_ontologies_ship_questions_that_cover_every_term_and_that_their_samples_answer():
    from oto.model import ontologies
    for name in ("oto-core", "software-architecture", "auto-claims", "organization-process", "professional-services"):
        result = ontologies.composed(name)
        assert result["questions"], name
        assert Q.uncovered(result["questions"], result["config"]) == [], name
        sample = result["sample"]
        assert Q.findings(result["questions"], sample["nodes"], sample["edges"], covers(result["config"]["classes"])) == [], name
        assert "questions" in ontologies.manifest_for(name)["carries"]
    # the core's questions compose into every extender, and a built-in installs them
    arch = ontologies.composed("software-architecture")["questions"]
    assert "CORE1" in arch and "SA1" in arch
    with tempfile.TemporaryDirectory() as root:
        init(root, slug="arch", name="Arch", ontology="software-architecture")
        installed = Q.load(Project.standard(root))
        assert set(installed) == set(arch)


def test_an_ontology_without_questions_for_every_term_is_not_usable(monkeypatch):
    from oto.model import ontologies
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, root)
        base = os.path.join(root, "thin")
        os.makedirs(base)
        config = {"name": "thin", "ontology_version": 1, "strict_domains": False, "_summary": "thin",
                  "classes": {"Thing": {"definition": "a thing"}, "Other": {"definition": "another"}},
                  "properties": {"near": {"domain": "Thing", "range": "Other", "definition": "near"}},
                  "temporal": {"as_of": {"type": "date", "definition": "when"}}}
        stamp = {"as_of": "2026-01-01", "valid_from": "2026-01-01", "source_doc": "d", "status": "current"}
        sample = {"nodes": [dict(id="thing.1", type="Thing", label="One", attributes={}, **stamp),
                            dict(id="other.1", type="Other", label="Two", attributes={}, **stamp)],
                  "edges": [{"from": "thing.1", "rel": "near", "to": "other.1"}]}
        rationale = {"classes": {k: {"question": "q", "why": "It answers a question the documents keep raising, and nothing else does.", "alternatives": "", "validated_by": ""}
                                 for k in config["classes"]}, "properties": {}}
        for filename, payload in (("ontology.config.json", config), ("sample.graph.json", sample),
                                  ("ontology.rationale.json", rationale),
                                  ("manifest.json", {"name": "thin", "namespace": "https://example.org/ont/thin#",
                                                     "carries": ["vocabulary", "rationale", "sample", "readme"]})):
            with open(os.path.join(base, filename), "w", encoding="utf-8") as f:
                json.dump(payload, f)
        with open(os.path.join(base, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Thin\n\nEdit it.\n")
        problems = ontologies.self_check("thin")
        assert "no question cites class Thing: what does it exist to answer? (questions.json)" in problems
        assert "no question cites relation near: what does it exist to answer? (questions.json)" in problems
        # one question that names both classes and the relation, and the sample answers it
        holder = type("H", (), {"data": base})()
        Q.save(holder, {"T1": {"who": "anyone", "question": "What is near what?", "why": "that is the point",
                               "ask": {"when": [{"edge": ["a", "near", "b"]}, {"node": "a", "type": "Thing"}, {"node": "b", "type": "Other"}],
                                       "select": ["a.label", "b.label"]}, "gate": "non_empty"}})
        manifest = json.load(open(os.path.join(base, "manifest.json"), encoding="utf-8"))
        manifest["carries"] = ["vocabulary", "rationale", "questions", "sample", "readme"]
        json.dump(manifest, open(os.path.join(base, "manifest.json"), "w", encoding="utf-8"))
        assert ontologies.self_check("thin") == []
        # the sample must answer what it must: an empty sample edge list is a problem, named
        json.dump(dict(sample, edges=[]), open(os.path.join(base, "sample.graph.json"), "w", encoding="utf-8"))
        problems = ontologies.self_check("thin")
        assert problems == ["the sample cannot answer T1 as required: (graph), unanswered"]


def test_two_ontologies_must_agree_on_a_shared_question_id(monkeypatch):
    from oto.model import ontologies, ontology_compose
    from test_ontology_contract import base_ontology, write_ontology, _node
    with tempfile.TemporaryDirectory() as root:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, root)
        base_ontology(root)
        base_questions = Q.load(type("H", (), {"data": os.path.join(root, "base")})())
        same = {"Q-Document": base_questions["Q-Document"]}
        write_ontology(root, "agree", {"Claim": {"definition": "a claim"}}, {}, {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                       manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme"]},
                       temporal=False, questions=dict(same, **{"Q-Claim": {"who": "anyone", "question": "Which claims?", "why": "w",
                                                                           "ask": {"when": [{"node": "c", "type": "Claim"}], "select": ["c.label"]}, "gate": "any"}}))
        composed = ontologies.composed("agree")
        assert ("Q-Document", "base", "agree") in composed["report"]["questions_shared"]
        assert "question Q-Document declared identically by base and agree" in ontology_compose.report_lines(composed["report"])
        different = dict(same["Q-Document"], gate="non_empty")
        write_ontology(root, "disagree", {"Claim": {"definition": "a claim"}}, {}, {"nodes": [_node("claim.1", "Claim", "One")], "edges": []},
                       manifest_body={"extends": ["base"], "carries": ["vocabulary", "rationale", "sample", "readme"]},
                       temporal=False, questions={"Q-Document": different})
        assert any("declares question 'Q-Document' differently from 'base'" in p for p in ontologies.self_check("disagree"))


def test_the_lock_carries_the_questions_and_check_diffs_them(capsys):
    from oto.cli import main
    from oto.model import vocabulary as _vocab
    with tempfile.TemporaryDirectory() as root:
        project = _project(root, keep_shipped=True)
        build(project)
        declared = Q.load(project)
        assert main(["ontology", "accept", "--project", root]) == 0
        assert "%d questions)" % len(declared) in capsys.readouterr().out
        assert Q.read_lock(project) == declared
        changed = json.loads(json.dumps(declared))
        changed["CQ1"]["why"] = "reworded reason"                        # cosmetic
        changed["CQ2"]["gate"] = "any"                                   # a different question
        changed["CQ4"] = {"who": "anyone", "question": "Which teams own nothing?", "why": "an idle team is a smell",
                          "ask": {"when": [{"node": "t", "type": "Team"}, {"not_edge": ["*", "owned_by", "t"]}], "select": ["t.label"]},
                          "gate": "any"}
        del changed["CQ3"]
        Q.save(project, changed)
        assert Q.diff(declared, changed) == (["CQ4"], ["CQ3"], ["CQ2"], ["CQ1"])
        assert main(["ontology", "check", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "questions: %d declared; the live graph answers %d as required" % (len(declared), len(declared)) in out
        assert "[breaking ] question removed   CQ3" in out and "[breaking ] question changed   CQ2" in out
        assert "[additive ] question added     CQ4" in out and "[cosmetic ] question reworded  CQ1" in out
        # a term no question cites is reported, and accept refuses it
        assert "no question cites" not in out
        vocabulary = json.load(open(project.ontology_config_path, encoding="utf-8"))
        vocabulary["classes"]["Vendor"] = {"definition": "An outside supplier."}
        json.dump(vocabulary, open(project.ontology_config_path, "w", encoding="utf-8"))
        assert main(["ontology", "check", "--project", root]) == 0
        assert "1 term(s) no question cites: Vendor" in capsys.readouterr().out
        assert main(["ontology", "check", "--project", root, "--strict"]) == 1
        capsys.readouterr()
        assert main(["ontology", "accept", "--project", root]) == 1
        out = capsys.readouterr().out
        assert "refusing to accept a vocabulary whose questions do not cover it" in out and "no question cites Vendor" in out
        # an unanswerable required question shows in the check and fails --strict
        del vocabulary["classes"]["Vendor"]
        json.dump(vocabulary, open(project.ontology_config_path, "w", encoding="utf-8"))
        graph = json.load(open(project.graph_path, encoding="utf-8"))
        graph["edges"] = [e for e in graph["edges"] if e["rel"] != "part_of"]
        json.dump(graph, open(project.graph_path, "w", encoding="utf-8"))
        assert main(["ontology", "check", "--project", root, "--strict"]) == 1
        out = capsys.readouterr().out
        # CQ1 and the shipped SA1 both need part_of
        assert "questions: %d declared; the live graph answers %d as required, 2 it cannot:" % (len(declared), len(declared) - 2) in out
        assert "CQ1    unanswered  Which components make up $SYSTEM, and where does each run?: Payments platform; no component is part of the system" in out


def test_export_ships_the_questions_unconfirmed_and_a_merge_keeps_them(monkeypatch, capsys):
    from oto.model import ontologies
    with tempfile.TemporaryDirectory() as home:
        monkeypatch.setenv(ontologies.USER_DIR_ENV, home)
        with tempfile.TemporaryDirectory() as root:
            project = _project(root, dict(QUESTIONS, CQ1=dict(QUESTIONS["CQ1"], validated_by="R. Plant")), keep_shipped=True)
            path, problems = ontologies.export(project, "my-arch", summary="mine")
            assert problems == [], problems
            shipped = json.load(open(os.path.join(path, "questions.json"), encoding="utf-8"))["questions"]
            assert {"CQ1", "CQ2", "CQ3", "SA1"} <= set(shipped) and shipped["CQ1"]["validated_by"] == "", \
                "confirmation in one project does not carry to another"
            assert "questions" in json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))["carries"]
        with tempfile.TemporaryDirectory() as root:
            init(root, slug="m", name="M", ontology="my-arch,organization-process")
            merged = Q.load(Project.standard(root))
            assert "CQ1" in merged and "OP1" in merged and "CORE1" in merged
