"""Acceptance criteria from the graph, deviations as change proposals, measured requirements as
promoted facts (roadmap I6, I7, H5, H6).

`oto factory criteria` writes `criteria.md`, `criteria.json` and a pytest skeleton for a bounded
context from what the graph says: each scenario of its use cases (given, when, then), each
business rule constraining its elements, each policy that applies to it, each budget of the
component it runs as, each control on that component; every criterion traces to the nodes it came
from, and a person reviews the skeleton before anything builds on it. `oto factory deviate` turns
what a runner or an evaluator found impossible as specified into a `ChangeProposal` in the main
graph, prompted by the evidence of what was observed, about the node it would change, with the
siblings reached through contract edges named before the build continues; the run's build is
failed until a person decides. `oto arch measure` turns a test report, a coverage report or a load
test summary into `Evidence` that measures a requirement, cited to a document, so the measured
value is a promoted fact next to the budget."""
import contextlib
import io
import json
import os

import pytest

from oto import arch as _arch
from oto.packs import factory
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="intake" tests="12" failures="1" errors="0" skipped="1" time="2.5">
<testcase classname="t" name="a" time="0.1"/><testcase classname="t" name="b"><failure message="boom"/></testcase></testsuite></testsuites>
"""
COVERAGE = """<?xml version="1.0" ?>
<coverage version="7.4" timestamp="1" lines-valid="200" lines-covered="174" line-rate="0.87" branches-covered="0" branches-valid="0" branch-rate="0" complexity="0">
<sources><source>src</source></sources><packages/></coverage>
"""
K6 = {"metrics": {"http_req_duration": {"type": "trend", "contains": "time", "values": {"avg": 412.3, "p(90)": 801.2, "p(95)": 870.4, "p(99)": 1203.0}},
                  "http_reqs": {"values": {"count": 5000}}}}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _gates(root, proposal, note):
    for step in (("curate", "start"), ("curate", "add", "--from", proposal), ("curate", "check"),
                 ("curate", "apply", "--by", "Sam Lee", "--note", note)):
        code, out = _cli(*step, "--project", root)
        assert code == 0 and "not in the document" not in out and "blocking" not in out.split("gap (")[0], (step, out)
    code, out = _cli("build", "--project", root)
    assert code == 0, out


@pytest.fixture
def domain(tmp_path):
    root = str(tmp_path / "domain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="domain", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


# ---- I6: criteria from the graph ----

def test_criteria_are_drawn_from_scenarios_rules_policies_budgets_and_controls(domain, tmp_path):
    out_dir = str(tmp_path / "criteria")
    code, out = _cli("factory", "criteria", "--context", "bc.checkout", "--out", out_dir, "--project", domain)
    assert code == 0, out
    assert "criteria.md" in out and "test_criteria_checkout.py" in out and "criterion" in out.lower(), out
    text = open(os.path.join(out_dir, "criteria.md"), encoding="utf-8").read()
    assert text.startswith("# Acceptance criteria of Checkout") and "`oto factory criteria`" in text and "review" in text.lower()
    assert "Given one captured payment, when the settlement batch runs, then the payment appears in that day's settlement with its ledger entry." in text
    assert "scenario.s-one-payment" in text and "uc.take-payment" in text, "a scenario traces to the use case it exercises"
    assert "A payment is captured at most once" in text and "rule.capture-once" in text and "invariant" in text
    with open(os.path.join(out_dir, "criteria.json"), encoding="utf-8") as f:
        criteria = json.load(f)
    assert criteria["context"] == "bc.checkout" and criteria["generated"]["by"] == "oto factory criteria"
    kinds = {c["kind"] for c in criteria["criteria"]}
    assert {"scenario", "rule"} <= kinds
    scenario = next(c for c in criteria["criteria"] if c["kind"] == "scenario")
    assert scenario["id"] == "c-1" and scenario["sources"] == ["scenario.s-one-payment", "uc.take-payment"] and scenario["given"] == "one captured payment"
    rule = next(c for c in criteria["criteria"] if c["kind"] == "rule")
    assert set(rule["sources"]) >= {"rule.capture-once"} and rule["text"].startswith("A payment is captured at most once")
    assert all(c["sources"] for c in criteria["criteria"]), "every criterion traces to the nodes it came from"
    skeleton = open(os.path.join(out_dir, "test_criteria_checkout.py"), encoding="utf-8").read()
    assert skeleton.startswith('"""Acceptance criteria of Checkout') and "import pytest" in skeleton
    assert '@pytest.mark.skip(reason="criterion c-1 not yet implemented' in skeleton and "def test_c_1_" in skeleton
    assert "scenario.s-one-payment" in skeleton and "A payment is captured at most once" in skeleton
    assert skeleton.count("def test_c_") == len(criteria["criteria"])
    compile(skeleton, "test_criteria_checkout.py", "exec")


def test_criteria_of_a_context_with_a_policy_and_of_a_component_s_context(domain, tmp_path):
    out_dir = str(tmp_path / "settlement")
    code, out = _cli("factory", "criteria", "--context", "bc.settlement", "--out", out_dir, "--project", domain)
    assert code == 0, out
    text = open(os.path.join(out_dir, "criteria.md"), encoding="utf-8").read()
    assert "Payment evidence is kept seven years" in text and "policy.pol-evidence" in text, "a policy from outside that applies to the context"
    assert "A settlement keeps its evidence seven years" in text and "rule.evidence-kept" in text
    with open(os.path.join(out_dir, "criteria.json"), encoding="utf-8") as f:
        kinds = {c["kind"] for c in json.load(f)["criteria"]}
    assert "policy" in kinds and "rule" in kinds
    out_dir = str(tmp_path / "intake")
    code, out = _cli("factory", "criteria", "--component", "component.invoice-intake", "--out", out_dir, "--project", domain)
    assert code == 0, out
    with open(os.path.join(out_dir, "criteria.json"), encoding="utf-8") as f:
        criteria = json.load(f)
    assert criteria["context"] == "bc.invoice-approval" and criteria["component"] == "component.invoice-intake"
    budget = next(c for c in criteria["criteria"] if c["kind"] == "budget")
    assert "900 ms" in budget["text"] and "p95 latency of invoice submission" in budget["text"] and "nfr.req-042" in budget["sources"]
    control = next(c for c in criteria["criteria"] if c["kind"] == "control")
    assert "PII encrypted at rest" in control["text"] and "control.pii-at-rest" in control["sources"] and "relationship.intake-stores" in control["sources"]
    code, out = _cli("factory", "criteria", "--context", "bc.nope", "--out", str(tmp_path / "x"), "--project", domain)
    assert code == 1 and "bc.nope" in out
    code, out = _cli("factory", "criteria", "--component", "component.payment-scheduler", "--out", str(tmp_path / "y"), "--project", domain)
    assert code == 1 and "no bounded context" in out and "deployed_as" in out, "a component no context runs as: nothing to draw the criteria from, said"
    code, out = _cli("factory", "criteria", "--out", str(tmp_path / "z"), "--project", domain)
    assert code == 1 and "--context" in out and "--component" in out


# ---- I7, H5: deviations as change proposals ----

@pytest.fixture
def run(domain, tmp_path):
    plan = str(tmp_path / "plan.json")
    code, out = _cli("factory", "plan", "--all", "--json", "--out", plan, "--project", domain)
    assert code == 0, out
    runs = str(tmp_path / "runs")
    code, out = _cli("factory", "run", "start", "--plan", plan, "--at", "2026-10-27", "--id", "r-009", "--runs", runs)
    assert code == 0, out
    return os.path.join(runs, "r-009")


def test_a_deviation_becomes_a_change_proposal_with_its_evidence_and_siblings(domain, run):
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.approval-policy", "--about", "contract.invoice-events-v1",
                     "--observed", "InvoiceSubmitted carries no supplier id, which the approval rules need",
                     "--proposes", "Add supplier_id to InvoiceSubmitted as version 2 of the invoice events contract",
                     "--at", "2026-10-28", "--into", domain)
    assert code == 0, out
    assert "changeproposal.r-009-1" in out and "deviation-r-009-1" in out and "curate add" in out, out
    assert "Invoice intake" in out and "approval-policy" not in out.split("siblings")[1].split("\n")[0], "the siblings through the contract: the intake exposes it; the deviating component itself is not its own sibling"
    assert "failed" in out, "the build stops until a person decides"
    text = open(os.path.join(domain, "build", "documents", "deviation-r-009-1.md"), encoding="utf-8").read()
    assert text.startswith("# Deviation r-009-1") and "InvoiceSubmitted carries no supplier id" in text and "Add supplier_id to InvoiceSubmitted" in text and "contract.invoice-events-v1" in text
    assert "Invoice intake (component.invoice-intake)" in text, "the siblings are in the document"
    with open(os.path.join(domain, "proposals", "deviation-r-009-1.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    evidence = nodes["evidence.deviation-r-009-1"]
    assert evidence["type"] == "Evidence" and evidence["attributes"]["kind"] == "review" and evidence["attributes"]["value"] == "InvoiceSubmitted carries no supplier id, which the approval rules need"
    assert evidence["attributes"]["source_url"] == "run r-009" and evidence["attributes"]["observed_on"] == "2026-10-28"
    cp = nodes["changeproposal.r-009-1"]
    assert cp["type"] == "ChangeProposal" and cp["label"].startswith("CP r-009-1:") and "Add supplier_id" in cp["label"] and cp["attributes"] == {"status": "proposed"}
    assert "Invoice intake" in cp["summary"], "the affected siblings are in the proposal's own words"
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("changeproposal.r-009-1", "prompted_by", "evidence.deviation-r-009-1") in edges
    assert ("changeproposal.r-009-1", "proposes_change_to", "contract.invoice-events-v1") in edges
    assert ("evidence.deviation-r-009-1", "evidence_of", "component.approval-policy") in edges
    assert ("evidence.deviation-r-009-1", "evidence_of", "contract.invoice-events-v1") in edges
    assert nodes["document.deviation-r-009-1"]["attributes"] == {"kind": "run"}
    _gates(domain, os.path.join(domain, "proposals", "deviation-r-009-1.json"), "a deviation from run r-009")
    code, out = _cli("query", "--project", domain, "ask", "AR7")
    assert code == 0 and "CP r-009-1" in out and "InvoiceSubmitted carries no supplier id" in out, out
    code, out = _cli("factory", "run", "status", "--run", run)
    assert code == 0 and "Approval policy (component.approval-policy): failed" in out, out
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.invoice-intake", "--about", "component.payment-scheduler",
                     "--observed", "the scheduling API has no idempotency key", "--proposes", "An idempotency key on the scheduling API", "--at", "2026-10-28", "--into", domain)
    assert code == 0 and "deviation-r-009-2" in out and "Approval policy" in out, "about a component: the siblings are what its relationships reach"
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.nope", "--about", "contract.invoice-events-v1", "--observed", "x", "--proposes", "y", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "component.nope" in out
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.invoice-intake", "--about", "contract.nope", "--observed", "x", "--proposes", "y", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "contract.nope" in out
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.invoice-intake", "--about", "contract.invoice-events-v1", "--proposes", "y", "--at", "2026-10-28", "--into", domain)
    assert code == 1 and "--observed" in out
    code, out = _cli("factory", "deviate", "--run", run, "--component", "component.invoice-intake", "--about", "contract.invoice-events-v1", "--observed", "x", "--proposes", "y", "--into", domain)
    assert code == 1 and "--at" in out


# ---- H6: measured requirements as promoted facts ----

def test_measurements_from_reports_become_evidence_of_the_requirement(domain, tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    coverage = tmp_path / "coverage.xml"
    coverage.write_text(COVERAGE, encoding="utf-8")
    k6 = tmp_path / "k6-summary.json"
    k6.write_text(json.dumps(K6), encoding="utf-8")
    assert _arch.measure_from(str(junit)) == ("junit", "10 of 12 tests passed (1 failed, 1 skipped)")
    assert _arch.measure_from(str(coverage)) == ("coverage", "87 % of lines covered (174 of 200)")
    assert _arch.measure_from(str(k6)) == ("k6", "p95 870 ms over 5000 requests")
    with pytest.raises(_arch.ArchError):
        _arch.measure_from(str(tmp_path / "nothing.txt"))
    (tmp_path / "odd.json").write_text("{}", encoding="utf-8")
    with pytest.raises(_arch.ArchError) as e:
        _arch.measure_from(str(tmp_path / "odd.json"))
    assert "junit" in str(e.value) and "coverage" in str(e.value) and "k6" in str(e.value)
    code, out = _cli("arch", "measure", "--nfr", "nfr.req-042", "--from", str(k6), "--at", "2026-10-29", "--source", "https://ci.invoice.example/runs/2026-10-29/k6", "--project", domain)
    assert code == 0, out
    assert "870 ms" in out and "measure-req-042-2026-10-29" in out and "curate add" in out, out
    text = open(os.path.join(domain, "build", "documents", "measure-req-042-2026-10-29.md"), encoding="utf-8").read()
    assert text.startswith("# Measurement of REQ-042") and "p95 870 ms over 5000 requests" in text and "k6" in text and "budget 900 ms" in text
    with open(os.path.join(domain, "proposals", "measure-req-042-2026-10-29.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    evidence = nodes["evidence.measure-req-042-2026-10-29"]
    assert evidence["type"] == "Evidence" and evidence["attributes"] == {"kind": "measurement", "value": "p95 870 ms over 5000 requests", "observed_on": "2026-10-29",
                                                                          "source_url": "https://ci.invoice.example/runs/2026-10-29/k6"}
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("evidence.measure-req-042-2026-10-29", "measurement_of", "nfr.req-042") in edges and ("evidence.measure-req-042-2026-10-29", "evidence_of", "component.invoice-intake") in edges
    assert nodes["document.measure-req-042-2026-10-29"]["attributes"] == {"kind": "run"}
    _gates(domain, os.path.join(domain, "proposals", "measure-req-042-2026-10-29.json"), "the k6 run of 2026-10-29")
    code, out = _cli("query", "--project", domain, "ask", "AR6", "NFR=nfr.req-042")
    assert code == 0 and "p95 870 ms over 5000 requests" in out and "870 ms" in out, "the measured value, straight from the graph"
    from test_apps import _engine
    engine = _engine(Project.standard(domain))
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "arch_context", "arguments": {"node": "component.invoice-intake"}}})
    context = "".join(c["text"] for c in reply["result"]["content"])
    assert "measured p95 870 ms over 5000 requests on 2026-10-29" in context, "the latest measurement is what an agent reads before it edits"
    code, out = _cli("arch", "measure", "--nfr", "nfr.req-042", "--value", "640 ms", "--at", "2026-10-30", "--project", domain)
    assert code == 0 and "640 ms" in out, "a value stated by hand, cited the same way"
    code, out = _cli("arch", "measure", "--nfr", "nfr.nope", "--value", "1", "--at", "2026-10-30", "--project", domain)
    assert code == 1 and "nfr.nope" in out
    code, out = _cli("arch", "measure", "--nfr", "component.invoice-intake", "--value", "1", "--at", "2026-10-30", "--project", domain)
    assert code == 1 and "NFR" in out and "Requirement" in out
    code, out = _cli("arch", "measure", "--nfr", "nfr.req-042", "--at", "2026-10-30", "--project", domain)
    assert code == 1 and "--from" in out and "--value" in out
    code, out = _cli("arch", "measure", "--nfr", "nfr.req-042", "--value", "1", "--project", domain)
    assert code == 1 and "--at" in out


def test_the_docs_name_criteria_deviations_and_measurements():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto factory criteria" in text and "oto factory deviate" in text and "oto arch measure" in text
    with open(os.path.join(ROOT, "factory", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "criteria" in readme and "deviate" in readme
