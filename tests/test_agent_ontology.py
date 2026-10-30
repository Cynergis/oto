"""The agent pattern: a part of a product that people give work to. Its rules refuse a design that
contradicts itself, warn about what is missing, and leave the sample clean."""
import copy

from oto.model import ontologies
from oto.model import vocabulary as _vocab
from oto.reason import engine, questions as _questions


def _composed():
    result = ontologies.composed("agent")
    return result, result["config"], result["sample"]


def _run(nodes, edges):
    result, config, _sample = _composed()
    classes = config.get("classes") or {}
    return engine.run(result["rules"], nodes, edges, covers=_vocab.covers(classes),
                      declared=_questions.declared_names(config))


def _sample():
    _result, _config, sample = _composed()
    return copy.deepcopy(sample["nodes"]), copy.deepcopy(sample["edges"])


def _node(nodes, node_id):
    return next(n for n in nodes if n["id"] == node_id)


def _findings(nodes, edges, severity):
    return {f["rule"] for f in _run(nodes, edges)["findings"] if f["severity"] == severity}


def test_agent_sits_on_software_architecture_and_checks_clean():
    raw = ontologies.load_raw("agent")
    assert raw["manifest"]["extends"] == ["software-architecture"]
    assert ontologies.self_check("agent") == []
    config, _sample, _readme = ontologies.load("agent")
    for kind in ("Agent", "Job", "Tool", "KnowledgeSource", "Guardrail", "Evaluation", "ConversationStyle"):
        assert kind in config["classes"], kind
    assert "Requirement" in config["classes"] and "Component" in config["classes"]


def test_the_sample_is_clean_and_the_agent_reaches_what_its_tools_reach():
    nodes, edges = _sample()
    outcome = _run(nodes, edges)
    assert not [f for f in outcome["findings"] if f["severity"] == "blocking"]
    reached = {e["to"] for e in outcome["edges"] if e["from"] == "agent.merchant-assistant" and e["rel"] == "reaches"}
    assert reached == {"interface.payments-v2", "datastore.ledger"}


def test_a_job_acting_alone_with_a_tool_that_needs_confirmation_is_refused():
    nodes, edges = _sample()
    edges.append({"from": "job.explain-settlement", "rel": "calls", "to": "tool.issue-refund"})
    assert "acts-alone-with-a-tool-needing-confirmation" in _findings(nodes, edges, "blocking")


def test_a_job_using_a_tool_the_agent_must_never_use_is_refused():
    nodes, edges = _sample()
    _node(nodes, "guardrail.own-payments")["attributes"]["kind"] = "never"
    assert "job-calls-a-forbidden-tool" in _findings(nodes, edges, "blocking")


def test_a_job_acting_alone_on_an_unguarded_change_is_refused_and_a_guardrail_settles_it():
    nodes, edges = _sample()
    email = copy.deepcopy(_node(nodes, "tool.issue-refund"))
    email.update({"id": "tool.email-customer", "label": "Email the customer"})
    email["attributes"] = {"effect": "sends", "reversible": False}
    nodes.append(email)
    edges.append({"from": "job.explain-settlement", "rel": "calls", "to": "tool.email-customer"})
    assert "acts-alone-on-an-unguarded-change" in _findings(nodes, edges, "blocking")
    edges.append({"from": "guardrail.own-payments", "rel": "protects", "to": "tool.email-customer"})
    assert "acts-alone-on-an-unguarded-change" not in _findings(nodes, edges, "blocking")


def test_a_ready_job_needs_a_requirement_and_a_passing_test():
    nodes, edges = _sample()
    _node(nodes, "job.refund-payment")["attributes"]["readiness"] = "ready"
    without_requirement = [e for e in edges if not (e["from"] == "job.refund-payment" and e["rel"] == "satisfies")]
    assert "ready-job-meets-a-requirement" in _findings(nodes, without_requirement, "blocking")
    without_test = [e for e in edges if not (e["rel"] == "proves" and e["to"] == "job.refund-payment")]
    assert "ready-job-is-proven" in _findings(nodes, without_test, "blocking")
    _node(nodes, "evaluation.short-day")["attributes"]["result"] = "fail"
    assert "ready-job-fails-a-test" in _findings(nodes, edges, "blocking")


def test_what_is_missing_is_a_warning_not_a_refusal():
    nodes, edges = _sample()
    without_who = [e for e in edges if not (e["from"] == "guardrail.confirm-refund" and e["rel"] == "confirmed_by")]
    assert "confirmation-names-who" in _findings(nodes, without_who, "warn")
    _node(nodes, "style.plain")["attributes"]["technical_details"] = "offered"
    _node(nodes, "job.refund-payment")["attributes"]["readiness"] = "ready"
    warnings = _findings(nodes, edges, "warn")
    assert {"technical-details-on-request", "ready-job-has-open-question"} <= warnings
    assert not _findings(nodes, edges, "blocking")


def test_agent_composes_on_the_architecture_widening_the_shared_relations():
    config, _sample, _readme, _rationale, report = ontologies.merge(["software-architecture", "agent"])
    assert report["class_clashes"] == []
    assert {"Agent", "Job", "Component", "System"} <= set(config["classes"])
    deployed = set(config["properties"]["deployed_as"]["domain"].split("|"))
    assert "Agent" in deployed
    part_of = set(config["properties"]["part_of"]["domain"].split("|"))
    assert {"Component", "Job"} <= part_of and ("part_of", "software-architecture", "agent") in report["relation_clashes"], "the pattern widens the estate's relation"
