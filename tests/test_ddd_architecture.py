"""The ddd pack on the architecture pack (roadmap Epic I, I1), and event-storming output in the
graph with a named person's sign-off (I2).

I1: the `ddd` pack now extends `architecture`, so a bounded context's deployed component and its
CALM node are one node, with one `external_id`, and the architecture's questions answer in a ddd project.
Readiness (draft, ready, built, on use cases, contexts, commands and aggregates) is a decision: a
new element reads as a draft until a named person says otherwise.

I2: `oto ddd storm --from board.json --at <date>` turns an event-storming board (stickies by kind:
event, command, actor, aggregate, policy, read model, external system, hot spot) into a document in
the corpus and a capture against the pack's capture schema; `oto curate propose --from` makes the
proposal, the gates take it, and `oto decide <node> readiness=ready --by <person> --at <date>` is the
analyst's sign-off on the graph itself, in place of the Epic D UI."""
import contextlib
import io
import json
import os

import pytest

from oto.cli import main
from oto.curate import session
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICE = os.path.join(ROOT, "tests", "fixtures", "calm", "invoice-platform.calm.json")

BOARD = {
    "session": "Invoice approval, big picture", "held_on": "2026-10-20", "facilitator": "Ana Lyst", "context": "Invoice approval",
    "stickies": [
        {"kind": "actor", "text": "Approver"},
        {"kind": "aggregate", "text": "Invoice"},
        {"kind": "external system", "text": "Supplier portal", "sends": ["Submit invoice"]},
        {"kind": "command", "text": "Submit invoice", "handled_by": "Invoice", "raises": "Invoice submitted"},
        {"kind": "event", "text": "Invoice submitted", "by": "Invoice"},
        {"kind": "policy", "text": "Whenever an invoice is submitted, check the approval rules", "when": "Invoice submitted", "then": "Check approval rules"},
        {"kind": "command", "text": "Check approval rules", "handled_by": "Invoice", "raises": "Invoice checked"},
        {"kind": "event", "text": "Invoice checked", "by": "Invoice"},
        {"kind": "command", "text": "Approve invoice", "actor": "Approver", "handled_by": "Invoice", "raises": "Invoice approved"},
        {"kind": "event", "text": "Invoice approved", "by": "Invoice"},
        {"kind": "read model", "text": "Pending invoices", "from": ["Invoice submitted", "Invoice checked"], "consulted_by": "Approver", "fields": ["supplier", "amount"]},
        {"kind": "hot spot", "text": "Who approves above 10k?", "about": "Approve invoice"},
    ]}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _gates(root, proposal, note):
    for step in (("curate", "start"), ("curate", "add", "--from", proposal), ("curate", "check"),
                 ("curate", "apply", "--by", "Sam Lee", "--note", note)):
        code, out = _cli(*step, "--project", root)
        assert code == 0 and "not in the document" not in out, (step, out)
    code, out = _cli("build", "--project", root)
    assert code == 0, out


@pytest.fixture
def ddd(tmp_path):
    root = str(tmp_path / "ddd")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ddd", name="The invoice domain", ontology="ddd")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


# ---- I1: one vocabulary, one node ----

def test_the_ddd_pack_sits_on_the_architecture_pack_and_readiness_is_a_decision():
    manifest = ontologies.manifest_for("ddd")
    assert manifest["extends"] == ["architecture"] and manifest["release"] == 2
    assert ontologies.self_check("ddd") == [], ontologies.self_check("ddd")
    config, sample, _readme = ontologies.load("ddd")
    assert {"Relationship", "Control", "Flow", "CodeModule", "BoundedContext", "DomainEvent", "Table"} - {"Table"} <= set(config["classes"]), "the domain's and the architecture's classes compose"
    assert config["attributes"]["Component"]["external_id"]["type"] == "string", "a context's deployed component is a CALM node"
    for kind in ("UseCase", "BoundedContext", "Command", "Aggregate"):
        spec = config["attributes"][kind]["readiness"]
        assert spec["default"] == "draft" and spec.get("decision") is True, kind
    with open(os.path.join(ROOT, "oto", "ontologies", "ddd", "ontology.config.json"), encoding="utf-8") as f:
        own = json.load(f)
    assert own["classes"].keys() == {"Subdomain", "BoundedContext", "ContextRelationship", "UseCase", "DomainEvent", "Command", "Reaction", "ReadModel",
                                     "ExternalSystem", "Aggregate", "Entity", "ValueObject", "BusinessRule", "DomainService"}, "the pack's own classes are unchanged"
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert ("bc.invoice-approval", "deployed_as", "component.invoice-intake") in edges, "the sample's new context runs as the architecture sample's CALM node"
    intake = next(n for n in sample["nodes"] if n["id"] == "component.invoice-intake")
    assert intake["attributes"]["external_id"] == "invoice-intake", "one node per component across the domain and CALM"


def test_a_ddd_project_answers_the_context_and_the_calm_facts_from_one_node(ddd):
    code, out = _cli("query", "--project", ddd, "ask", "DD2", "CONTEXT=bc.invoice-approval")
    assert code == 0 and "status: answered" in out and "Invoice intake" in out, out
    code, out = _cli("query", "--project", ddd, "ask", "AR1", "NODE=component.invoice-intake")
    assert code == 0 and "status: answered" in out and "JDBC" in out, "the architecture's question, in the ddd project"
    code, out = _cli("query", "--project", ddd, "ask", "DD23")
    assert code == 0, out
    code, out = _cli("ontology", "check", "--project", ddd)
    assert code == 0 and "every node satisfies them" in out, out
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-27", "--environment", "environment.payments-network", "--project", ddd)
    assert code == 0, "a CALM model imports into a ddd project: the classes are there"


# ---- I2: the board, through the capture form and the gates ----

def test_storm_turns_a_board_into_a_document_and_a_capture_the_gates_take(ddd, tmp_path):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(BOARD), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(board), "--at", "2026-10-21", "--project", ddd)
    assert code == 0, out
    assert "12 sticky" in out and "storm-invoice-approval" in out and "curate propose" in out, out
    text = open(os.path.join(ddd, "build", "documents", "storm-invoice-approval.md"), encoding="utf-8").read()
    assert text.startswith("# Event storming: Invoice approval, big picture") and "Ana Lyst" in text and "2026-10-20" in text
    assert "- [event] Invoice submitted" in text and "- [policy] Whenever an invoice is submitted, check the approval rules" in text and "- [hot spot] Who approves above 10k?" in text
    assert os.path.exists(os.path.join(ddd, "archive", "storm-invoice-approval.md"))
    with open(os.path.join(ddd, "captures", "storm-invoice-approval.json"), encoding="utf-8") as f:
        capture = json.load(f)
    assert capture["doc"] == "storm-invoice-approval" and capture["as_of"] == "2026-10-21"
    items = {i["id"]: i for i in capture["items"]}
    kinds = {i["type"] for i in capture["items"]}
    assert kinds == {"BoundedContext", "Role", "Aggregate", "Entity", "ExternalSystem", "Command", "DomainEvent", "Reaction", "ReadModel", "OpenQuestion"}
    assert items["invoice-approval"]["type"] == "BoundedContext" and items["invoice-approval"]["quote"] == "Invoice approval"
    assert items["invoice"]["type"] == "Aggregate" and items["invoice"]["links"]["root"] == ["invoice-root"] and items["invoice-root"]["type"] == "Entity", "an aggregate needs a root entity: named after it"
    submit = items["submit-invoice"]
    assert submit["type"] == "Command" and submit["links"]["handled_by"] == ["invoice"] and submit["links"]["raises"] == ["invoice-submitted"]
    assert submit["fields"]["trigger_kind"] == "external_system" and submit["links"]["triggered_by"] == ["supplier-portal"]
    assert items["approve-invoice"]["fields"]["trigger_kind"] == "actor" and items["approve-invoice"]["links"]["triggered_by"] == ["approver"] and items["approver"]["type"] == "Role"
    assert items["check-approval-rules"]["fields"]["trigger_kind"] == "policy"
    policy = items["whenever-an-invoice-is-submitted-check-the-approval-rules"]
    assert policy["type"] == "Reaction" and policy["links"]["reacts_to"] == ["invoice-submitted"] and policy["links"]["issues"] == ["check-approval-rules"]
    assert items["invoice-submitted"]["links"]["emitted_by"] == ["invoice"] and items["invoice-submitted"]["links"]["precedes"] == ["invoice-checked"], "events in board order precede each other"
    assert items["pending-invoices"]["links"]["projected_from"] == ["invoice-submitted", "invoice-checked"] and items["pending-invoices"]["links"]["consulted_by"] == ["approver"]
    assert items["pending-invoices"]["fields"]["fields"] == ["supplier", "amount"]
    assert items["supplier-portal"]["links"]["sends"] == ["submit-invoice"] and items["supplier-portal"]["links"]["integrated_by"] == ["invoice-approval"]
    hot = items["who-approves-above-10k"]
    assert hot["type"] == "OpenQuestion" and hot["fields"]["state"] == "open" and hot["links"]["about"] == ["approve-invoice"]
    assert all(i["links"].get("part_of") == ["invoice-approval"] for i in capture["items"] if i["type"] in ("DomainEvent", "Command", "Reaction", "ReadModel", "Aggregate"))
    assert all(i["quote"] and i["where"] for i in capture["items"]), "every sticky is its own evidence"
    assert "readiness" not in json.dumps(capture), "readiness is the person's to say: the default reads as draft"
    code, out = _cli("curate", "propose", "--from", os.path.join(ddd, "captures", "storm-invoice-approval.json"), "--project", ddd)
    assert code == 0, out
    proposal = os.path.join(ddd, "proposals", "storm-invoice-approval.json")
    assert os.path.exists(proposal), out
    _gates(ddd, proposal, "the storming session")
    code, out = _cli("query", "--project", ddd, "ask", "DD8", "EVENT=domainevent.invoice-submitted")
    assert code == 0 and "status: answered" in out and "Submit invoice" in out and "Invoice" in out, out
    code, out = _cli("query", "--project", ddd, "ask", "DD12")
    assert code == 0 and "check the approval rules" in out.lower() or "Check approval rules" in out, out
    code, out = _cli("query", "--project", ddd, "ask", "DD9", "EVENT=domainevent.invoice-submitted")
    assert code == 0 and "Invoice checked" in out, out
    code, out = _cli("query", "--project", ddd, "ask", "DD22", "CONTEXT=boundedcontext.invoice-approval")
    assert code == 0 and "status: answered" in out and "Pending invoices" in out and "Invoice" in out, out
    code, out = _cli("ontology", "check", "--project", ddd)
    assert code == 0 and "every node satisfies them" in out, out


def test_a_named_person_signs_off_on_the_graph_itself(ddd, tmp_path):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(BOARD), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(board), "--at", "2026-10-21", "--project", ddd)
    assert code == 0, out
    code, out = _cli("curate", "propose", "--from", os.path.join(ddd, "captures", "storm-invoice-approval.json"), "--project", ddd)
    assert code == 0, out
    _gates(ddd, os.path.join(ddd, "proposals", "storm-invoice-approval.json"), "the storming session")
    code, out = _cli("query", "--project", ddd, "ask", "DD23")
    assert code == 0 and "boundedcontext.invoice-approval" not in out, "a draft context lists nothing: nothing is ready yet"
    code, out = _cli("decide", "boundedcontext.invoice-approval", "readiness=ready", "--by", "Ana Lyst", "--at", "2026-10-22", "--note", "signed off at the review", "--project", ddd)
    assert code == 0 and "ready" in out and "Ana Lyst" in out, out
    graph = session.live(Project.standard(ddd))
    bc = next(n for n in graph["nodes"] if n["id"] == "boundedcontext.invoice-approval")
    assert bc["attributes"]["readiness"] == "ready" and any(str(s).startswith("assertion:") for s in bc["sources"])
    with open(os.path.join(ddd, "assertions.jsonl"), encoding="utf-8") as f:
        last = json.loads(f.read().strip().splitlines()[-1])
    assert last["by"] == "Ana Lyst" and "readiness" in last["text"] and "ready" in last["text"]
    code, out = _cli("audit", "log", "--project", ddd)
    assert code == 0 and "decide" in out and "signed off at the review" in out, out
    code, out = _cli("audit", "verify", "--project", ddd)
    assert code == 0, out
    code, out = _cli("build", "--project", ddd)
    assert code == 0, out
    code, out = _cli("query", "--project", ddd, "ask", "DD23")
    assert code == 0 and "Invoice" in out and "Aggregate" in out, "a ready context whose aggregate is still a draft: DD23 names it"
    code, out = _cli("decide", "aggregate.invoice", "readiness=ready", "--by", "Ana Lyst", "--at", "2026-10-22", "--project", ddd)
    assert code == 0, out
    code, out = _cli("decide", "aggregate.invoice", "readiness=ready", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 0 and "already" in out, out
    code, out = _cli("decide", "aggregate.invoice", "readiness=flying", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 1 and "draft" in out and "ready" in out and "built" in out, "the values the vocabulary takes"
    code, out = _cli("decide", "command.submit-invoice", "schedule=nightly", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 1 and "decision" in out, "a fact is not a decision: it moves by a supersession, not a signature"
    code, out = _cli("decide", "aggregate.nope", "readiness=ready", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 1 and "aggregate.nope" in out
    code, out = _cli("decide", "aggregate.invoice", "readiness=built", "--at", "2026-10-23", "--by", "", "--project", ddd)
    assert code == 1 and "--by" in out
    code, out = _cli("decide", "aggregate.invoice", "readiness=built", "--by", "Ana Lyst", "--project", ddd)
    assert code == 1 and "--at" in out
    code, out = _cli("decide", "aggregate.invoice", "readiness", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 1 and "attribute=value" in out
    code, out = _cli("data", "confirm", "aggregate.invoice", "--by", "Ana Lyst", "--at", "2026-10-23", "--project", ddd)
    assert code == 1 and "Table or a Column" in out, "data confirm stays a meaning's: the general command is decide"


def test_storm_refuses_what_it_cannot_cite(ddd, tmp_path):
    code, out = _cli("ddd", "storm", "--from", str(tmp_path / "missing.json"), "--at", "2026-10-21", "--project", ddd)
    assert code == 1 and "missing.json" in out
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(bad), "--at", "2026-10-21", "--project", ddd)
    assert code == 1 and "JSON" in out
    board = tmp_path / "board.json"
    board.write_text(json.dumps(BOARD), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(board), "--project", ddd)
    assert code == 1 and "--at" in out
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"session": "x", "stickies": []}), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(empty), "--at", "2026-10-21", "--project", ddd)
    assert code == 1 and "stickies" in out
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"session": "x", "context": "c", "stickies": [{"kind": "banana", "text": "x"}]}), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(odd), "--at", "2026-10-21", "--project", ddd)
    assert code == 1 and "banana" in out and "event" in out
    loose = tmp_path / "loose.json"
    loose.write_text(json.dumps({"session": "x", "context": "c", "stickies": [{"kind": "command", "text": "Do it"}, {"kind": "hot spot", "text": "Why?", "about": "Nothing here"}]}), encoding="utf-8")
    code, out = _cli("ddd", "storm", "--from", str(loose), "--at", "2026-10-21", "--project", ddd)
    assert code == 0 and "Do it" in out and "handled_by" in out and "Nothing here" in out, "a command with no aggregate and a hot spot about nothing: said before the gates"
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="communication")
    code, out = _cli("ddd", "storm", "--from", str(board), "--at", "2026-10-21", "--project", plain)
    assert code == 1 and "DomainEvent" in out


def test_the_docs_name_the_board_and_the_sign_off():
    with open(os.path.join(ROOT, "oto", "ontologies", "ddd", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "oto ddd storm" in readme and "oto decide" in readme and "architecture" in readme
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto ddd storm" in text and "oto decide" in text
