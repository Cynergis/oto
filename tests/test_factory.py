"""Contracts, the spec projection and the planner (roadmap Epic I, I3 to I5).

A `Contract` is a version of an interface the estate declares (an event schema, an API), with a
`status` that is a decision: `draft` until a named person freezes it (`oto decide`), `frozen` when
nobody may change it without a new version, `retired` when superseded. `oto factory spec
<component>` projects a component's spec from the graph as schema-checked JSON (the context it
carries, what it exposes and consumes with each contract's version and status, its requirements
with budgets, decisions, controls, connections, modules), hashed so a spec edited by hand is
refused. `oto factory plan` derives the execution plan from contract dependencies: a consumer of a
frozen contract builds in parallel with its provider; a consumer of a draft one waits; the invoice
example's plan is three parallel builds."""
import contextlib
import hashlib
import io
import json
import os

import pytest

from oto.packs import factory
from oto.cli import main
from oto.model import ontologies
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def domain(tmp_path):
    """A ddd project: the architecture sample's invoice platform with contracts, and the ddd sample's context on it."""
    root = str(tmp_path / "domain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="domain", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


# ---- I4: contracts as versioned nodes ----

def test_a_contract_is_a_version_of_an_interface_and_frozen_is_a_decision():
    manifest = ontologies.manifest_for("architecture")
    assert manifest["release"] >= 3 and any("Contract" in entry["note"] and entry["release"] == 3 for entry in manifest["changelog"])
    assert ontologies.self_check("architecture") == [], ontologies.self_check("architecture")
    with open(os.path.join(ROOT, "oto", "ontologies", "architecture", "ontology.config.json"), encoding="utf-8") as f:
        own = json.load(f)
    assert "Contract" in own["classes"]
    contract = own["attributes"]["Contract"]
    assert contract["version"]["required"] is True and contract["version"]["type"] == "string"
    assert contract["status"]["type"] == "enum:draft|frozen|retired" and contract["status"]["default"] == "draft" and contract["status"].get("decision") is True
    assert contract["kind"]["type"].startswith("enum:") and "event" in contract["kind"]["type"] and "api" in contract["kind"]["type"]
    assert contract["schema_url"]["type"] == "string"
    assert own["properties"]["contract_of"] == dict(own["properties"]["contract_of"], domain="Contract", range="Interface", min=1, max=1)
    assert "Contract" in own["properties"]["supersedes"]["domain"].split("|") and "Contract" in own["properties"]["supersedes"]["range"].split("|"), "a new version supersedes the old, the engine's way"
    questions = ontologies.questions_for("architecture")
    assert "AR10" in questions and "contract" in questions["AR10"]["question"].lower() and "NODE" in questions["AR10"]["params"]
    _config, sample, _readme = ontologies.load("architecture")
    own_nodes = {n["id"]: n for n in sample["nodes"] if n.get("source_doc") == "invoice-architecture"}
    contracts = {k: v for k, v in own_nodes.items() if v["type"] == "Contract"}
    assert {"contract.invoice-events-v1", "contract.invoice-api-v1", "contract.scheduling-api-v1"} <= set(contracts)
    assert all(c["attributes"]["status"] == "frozen" and c["attributes"]["version"] == "1" for c in contracts.values()), "the invoice platform builds contract-first"
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert ("contract.invoice-events-v1", "contract_of", "interface.invoice-events") in edges
    assert ("component.payment-scheduler", "exposes", "interface.scheduling-api") in edges and ("component.approval-policy", "consumes", "interface.scheduling-api") in edges
    assert ("relationship.policy-schedules", "via", "interface.scheduling-api") in edges


def test_a_project_answers_which_contracts_a_node_exposes_and_consumes(domain):
    code, out = _cli("query", "--project", domain, "ask", "AR10", "NODE=component.approval-policy")
    assert code == 0 and "status: answered" in out and "scheduling-api" in out and "frozen" in out and "invoice-events" in out, out
    code, out = _cli("decide", "contract.invoice-events-v1", "status=draft", "--by", "Sam Lee", "--at", "2026-10-27", "--project", domain)
    assert code == 0 and "draft" in out, "frozen is a decision: a named person moves it"
    code, out = _cli("decide", "contract.invoice-events-v1", "version=2", "--by", "Sam Lee", "--at", "2026-10-27", "--project", domain)
    assert code == 1 and "decision" in out, "a version is a fact: a new version is a new contract that supersedes the old"


# ---- I3: the spec as a projection ----

def test_the_spec_is_projected_from_the_graph_schema_checked_and_hashed(domain):
    code, out = _cli("factory", "spec", "component.invoice-intake", "--project", domain)
    assert code == 0, out
    spec = json.loads(out)
    assert factory.check_spec(spec) == [], factory.check_spec(spec)
    assert spec["schema_version"] == 1 and spec["component"] == {"id": "component.invoice-intake", "label": "Invoice intake", "external_id": "invoice-intake", "external_type": "service",
                                                                "summary": "Accepts a submitted invoice, stores it and emits InvoiceSubmitted."}
    assert spec["context"]["id"] == "bc.invoice-approval" and spec["context"]["readiness"] == "draft" and spec["context"]["label"] == "Invoice approval"
    assert [u["label"] for u in spec["use_cases"]] == ["Submit an invoice for approval"]
    exposes = {e["interface"]: e for e in spec["exposes"]}
    assert set(exposes) == {"interface.invoice-api", "interface.invoice-events"}
    assert exposes["interface.invoice-events"]["contracts"] == [{"id": "contract.invoice-events-v1", "version": "1", "status": "frozen", "kind": "event", "schema_url": "https://invoice.example/contracts/invoice-events/v1.json"}]
    assert spec["consumes"] == []
    assert spec["requirements"] == [{"id": "nfr.req-042", "label": "REQ-042: invoice submission under one second", "metric": "p95 latency of invoice submission", "budget": "900 ms",
                                     "measured": {"value": "870 ms", "observed_on": "2026-10-20"}}]
    assert spec["decisions"] == [] and [c["id"] for c in spec["controls"]] == ["control.pii-at-rest"] and spec["controls"][0]["on"] == "relationship.intake-stores"
    assert [c["to"] for c in spec["connections"] if c["direction"] == "out"] == ["datastore.invoice-db", "component.approval-policy"]
    assert spec["modules"] == [{"id": "codemodule.src-intake", "path": "src/intake", "language": "python", "last_commit": {"sha": "9f3c2a1", "committed_on": "2026-10-18", "author": "Sam Lee"}}]
    assert spec["open_change_proposals"] == []
    assert spec["generated"]["by"] == "oto factory spec" and len(spec["generated"]["hash"]) == 64
    body = dict(spec); body["generated"] = {k: v for k, v in spec["generated"].items() if k != "hash"}
    assert spec["generated"]["hash"] == hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    out_path = os.path.join(domain, "specs", "invoice-intake.spec.json")
    code, out = _cli("factory", "spec", "component.invoice-intake", "--out", out_path, "--project", domain)
    assert code == 0 and os.path.exists(out_path), out
    code, out = _cli("factory", "spec", "--check", out_path, "--project", domain)
    assert code == 0 and "holds" in out, out
    with open(out_path, encoding="utf-8") as f:
        edited = json.load(f)
    edited["requirements"][0]["budget"] = "9000 ms"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(edited, f)
    code, out = _cli("factory", "spec", "--check", out_path, "--project", domain)
    assert code == 1 and "edited" in out and "oto factory spec" in out, "nobody edits a spec by hand"
    del edited["requirements"]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(edited, f)
    code, out = _cli("factory", "spec", "--check", out_path, "--project", domain)
    assert code == 1 and "requirements" in out
    code, out = _cli("factory", "spec", "component.nope", "--project", domain)
    assert code == 1 and "component.nope" in out
    code, out = _cli("factory", "spec", "datastore.invoice-db", "--project", domain)
    assert code == 1 and "Component" in out
    code, out = _cli("factory", "spec", "component.payment-scheduler", "--project", domain)
    assert code == 0, out
    scheduler = json.loads(out)
    assert scheduler["context"] is None and [d["id"] for d in scheduler["decisions"]] == ["decision.adr-007"] and scheduler["open_change_proposals"] == [{"id": "changeproposal.cp-001", "label": "CP-001: scheduler reads through the intake API"}]
    assert {c["interface"] for c in scheduler["consumes"]} == set() and {e["interface"] for e in scheduler["exposes"]} == {"interface.scheduling-api"}


# ---- I5: the planner ----

def test_the_plan_is_three_parallel_builds_when_the_contracts_are_frozen(domain):
    code, out = _cli("factory", "plan", "--all", "--project", domain)
    assert code == 0, out
    assert "3 build(s) in 1 group(s)" in out and "group 1 (parallel): Approval policy, Invoice intake, Payment scheduler" in out, out
    assert "approval-policy -> invoice-intake via interface.invoice-events (contract.invoice-events-v1 frozen): parallel" in out
    assert "approval-policy -> payment-scheduler via interface.scheduling-api (contract.scheduling-api-v1 frozen): parallel" in out
    code, out = _cli("factory", "plan", "--all", "--json", "--project", domain)
    assert code == 0, out
    plan = json.loads(out)
    assert plan["groups"] == [["component.approval-policy", "component.invoice-intake", "component.payment-scheduler"]]
    assert all(e["parallel"] for e in plan["edges"]) and plan["unplanned"] == []
    code, out = _cli("decide", "contract.invoice-events-v1", "status=draft", "--by", "Sam Lee", "--at", "2026-10-27", "--project", domain)
    assert code == 0, out
    code, out = _cli("build", "--project", domain)
    assert code == 0, out
    code, out = _cli("factory", "plan", "--all", "--json", "--project", domain)
    assert code == 0, out
    plan = json.loads(out)
    assert plan["groups"] == [["component.invoice-intake", "component.payment-scheduler"], ["component.approval-policy"]], "a draft contract: the consumer waits for its provider"
    edge = next(e for e in plan["edges"] if e["consumer"] == "component.approval-policy" and e["provider"] == "component.invoice-intake")
    assert edge["parallel"] is False and edge["contract"] == "contract.invoice-events-v1" and edge["status"] == "draft"
    code, out = _cli("factory", "plan", "--all", "--project", domain)
    assert "2 group(s)" in out and "then group 2" in out and "waits" in out, out


def test_the_plan_follows_the_contexts_a_person_signed_off(domain, tmp_path):
    bare = str(tmp_path / "bare")
    with contextlib.redirect_stdout(io.StringIO()):
        init(bare, slug="bare", name="Bare", ontology="ddd", empty=True)
    code, out = _cli("factory", "plan", "--project", bare)
    assert code == 0 and "no context is ready" in out and "oto decide" in out, "nothing signed off: nothing to build, said with the command"
    code, out = _cli("factory", "plan", "--json", "--project", domain)
    assert code == 0, out
    plan = json.loads(out)
    assert plan["contexts"] == ["bc.checkout"] and plan["groups"] == [["component.payment-api"]], "the ddd sample's checkout context is signed off already"
    code, out = _cli("decide", "bc.invoice-approval", "readiness=ready", "--by", "Ana Lyst", "--at", "2026-10-27", "--project", domain)
    assert code == 0, out
    code, out = _cli("build", "--project", domain)
    assert code == 0, out
    code, out = _cli("factory", "plan", "--json", "--project", domain)
    assert code == 0, out
    plan = json.loads(out)
    assert plan["groups"] == [["component.invoice-intake", "component.payment-api"]] and plan["contexts"] == ["bc.checkout", "bc.invoice-approval"]
    code, out = _cli("factory", "plan", "--context", "bc.invoice-approval", "--json", "--project", domain)
    assert code == 0 and json.loads(out)["groups"] == [["component.invoice-intake"]]
    code, out = _cli("factory", "plan", "--context", "bc.nope", "--project", domain)
    assert code == 1 and "bc.nope" in out
    code, out = _cli("factory", "plan", "--context", "bc.checkout", "--json", "--project", domain)
    assert code == 0, out
    plan = json.loads(out)
    assert plan["groups"] == [["component.payment-api"]] or plan["groups"] == [] , out
    code, out = _cli("factory", "plan", "--out", os.path.join(domain, "plan.json"), "--json", "--project", domain)
    assert code == 0 and os.path.exists(os.path.join(domain, "plan.json"))


def test_a_cycle_of_draft_contracts_is_named_not_looped():
    graph = {"nodes": [
        {"id": "component.a", "type": "Component", "label": "A", "attributes": {"external_id": "a"}, "status": "current"},
        {"id": "component.b", "type": "Component", "label": "B", "attributes": {"external_id": "b"}, "status": "current"},
        {"id": "interface.ia", "type": "Interface", "label": "IA", "attributes": {}, "status": "current"},
        {"id": "interface.ib", "type": "Interface", "label": "IB", "attributes": {}, "status": "current"}],
        "edges": [{"from": "component.a", "rel": "exposes", "to": "interface.ia"}, {"from": "component.b", "rel": "consumes", "to": "interface.ia"},
                  {"from": "component.b", "rel": "exposes", "to": "interface.ib"}, {"from": "component.a", "rel": "consumes", "to": "interface.ib"}]}
    plan = factory.plan(graph, ["component.a", "component.b"])
    assert plan["groups"] == [] and len(plan["unplanned"]) == 2 and "cycle" in plan["unplanned"][0]["why"], "two draft contracts each waiting on the other: said, not looped"
    assert all(e["parallel"] is False and e["contract"] is None for e in plan["edges"]), "an interface with no contract is a draft dependency"


def test_the_docs_name_the_factory_commands():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto factory spec" in text and "oto factory plan" in text and "Contract" in text
    with open(os.path.join(ROOT, "oto", "ontologies", "architecture", "README.md"), encoding="utf-8") as f:
        assert "Contract" in f.read()
