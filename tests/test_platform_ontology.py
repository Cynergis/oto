"""The platform binding: where a product's parts run and what they are built with, and who decides
each choice. Its briefs stop an implementing agent by name on any missing detail; its rules refuse a
builder's pick outside its limits, a choice left to the builder with no limits, and a decision
accepted with nobody named."""
import copy

from oto.model import ontologies
from oto.model import vocabulary as _vocab
from oto.reason import briefs as _briefs, engine, questions as _questions


def _composed():
    return ontologies.composed("platform")


def _sample():
    sample = _composed()["sample"]
    return copy.deepcopy(sample["nodes"]), copy.deepcopy(sample["edges"])


def _node(nodes, node_id):
    return next(n for n in nodes if n["id"] == node_id)


def _outcome(nodes, edges):
    result = _composed()
    config = result["config"]
    return engine.run(result["rules"], nodes, edges, covers=_vocab.covers(config.get("classes") or {}),
                      declared=_questions.declared_names(config))


def _findings(nodes, edges, severity):
    return {f["rule"] for f in _outcome(nodes, edges)["findings"] if f["severity"] == severity}


def _brief(task, params, nodes, edges):
    result = _composed()
    config = result["config"]
    outcome = _outcome(nodes, edges)
    derived_edges = [{"from": e["from"], "rel": e["rel"], "to": e["to"]} for e in outcome["edges"]]
    derived = {}
    for a in outcome["attributes"]:
        derived.setdefault(a["node"], {})[a["name"]] = a["value"]
    return _briefs.run(task, result["briefs"][task], params, result["questions"], nodes, edges + derived_edges,
                       _vocab.covers(config.get("classes") or {}), derived, _questions.declared_names(config))


def _blocking(result):
    return {b["id"] for b in result["blocking"]}


def test_platform_sits_on_software_architecture_and_checks_clean():
    raw = ontologies.load_raw("platform")
    assert raw["manifest"]["extends"] == ["software-architecture"]
    assert ontologies.self_check("platform") == []
    config, _sample_graph, _readme = ontologies.load("platform")
    for kind in ("Platform", "Account", "PlatformService", "Technology", "Choice", "SecretRef", "Pipeline"):
        assert kind in config["classes"], kind
    assert {"purpose", "region", "console_url", "logs_url"} <= set(config["attributes"]["Environment"])
    assert {"status", "option", "alternatives", "consequences", "rationale"} <= set(config["attributes"]["Decision"])


def test_the_sample_is_bound_and_every_brief_is_ready():
    nodes, edges = _sample()
    assert not _findings(nodes, edges, "blocking")
    for component in ("component.payment-api", "component.settlement-job"):
        for task in ("implement-component", "deploy-component"):
            result = _brief(task, {"COMPONENT": component}, nodes, edges)
            assert result["status"] == "READY", (task, component, result["blocking"])
    assert _brief("test-end-to-end", {"ENVIRONMENT": "environment.production"}, nodes, edges)["status"] == "READY"


def test_a_missing_detail_blocks_the_agent_by_name():
    nodes, edges = _sample()
    no_pipeline = [e for e in edges if not (e["rel"] == "deploys" and e["to"] == "component.payment-api")]
    result = _brief("deploy-component", {"COMPONENT": "component.payment-api"}, nodes, no_pipeline)
    assert result["status"] == "BLOCKED" and "PL6" in _blocking(result)
    assert "no pipeline deploys it" in str(result["blocking"])
    assert "PL11" in _blocking(_brief("test-end-to-end", {"ENVIRONMENT": "environment.production"}, nodes, no_pipeline)), \
        "a component that cannot be deployed stops the end-to-end test"
    del _node(nodes, "environment.production")["attributes"]["region"]
    result = _brief("test-end-to-end", {"ENVIRONMENT": "environment.production"}, nodes, edges)
    assert "PL2" in _blocking(result) and "nobody has said which region it is in" in str(result["blocking"])
    nodes, edges = _sample()
    del _node(nodes, "technology.fastapi")["attributes"]["version"]
    assert "PL7" in _blocking(_brief("implement-component", {"COMPONENT": "component.payment-api"}, nodes, edges))
    nodes, edges = _sample()
    edges = [e for e in edges if not (e["from"] == "secret.acquirer-key" and e["rel"] == "kept_in")]
    assert "PL5" in _blocking(_brief("deploy-component", {"COMPONENT": "component.payment-api"}, nodes, edges))
    assert "PL12" in _blocking(_brief("test-end-to-end", {"ENVIRONMENT": "environment.production"}, nodes, edges))
    assert "secret-has-a-place" in _findings(nodes, edges, "warn")


def test_an_unsettled_choice_stops_the_build_until_a_person_accepts_it():
    nodes, edges = _sample()
    _node(nodes, "decision.d-framework")["attributes"]["status"] = "proposed"
    result = _brief("implement-component", {"COMPONENT": "component.payment-api"}, nodes, edges)
    assert result["status"] == "BLOCKED" and "PL8" in _blocking(result), "the builder's pick is only proposed"
    _node(nodes, "decision.d-region")["attributes"]["status"] = "proposed"
    assert "PL13" in _blocking(_brief("test-end-to-end", {"ENVIRONMENT": "environment.production"}, nodes, edges))


def test_who_decides_what_is_enforced():
    nodes, edges = _sample()
    _node(nodes, "decision.d-framework")["attributes"]["option"] = "Express"
    assert "builder-pick-outside-its-limits" in _findings(nodes, edges, "blocking")
    nodes, edges = _sample()
    del _node(nodes, "choice.api-framework")["attributes"]["allowed"]
    unbounded = [e for e in edges if not (e["from"] == "choice.api-framework" and e["rel"] == "bounded_by")]
    assert "delegated-choice-without-limits" in _findings(nodes, unbounded, "blocking")
    assert "delegated-choice-without-limits" not in _findings(nodes, edges, "blocking"), "an earlier decision bounds it"
    nodes, edges = _sample()
    nobody = [e for e in edges if not (e["from"] == "decision.d-framework" and e["rel"] == "decided_by")]
    assert "accepted-decision-names-who" in _findings(nodes, nobody, "blocking")
    del _node(nodes, "decision.d-cloud")["attributes"]["alternatives"]
    assert "decision-records-alternatives" in _findings(nodes, edges, "warn")


def test_platform_composes_with_the_patterns():
    config, _sample_graph, _readme, _rationale, report = ontologies.merge(["software-architecture", "ddd", "agent", "platform"])
    assert report["class_clashes"] == []
    about = set(config["properties"]["about"]["range"].split("|"))
    assert {"Environment", "Choice", "Job", "BoundedContext"} <= about
