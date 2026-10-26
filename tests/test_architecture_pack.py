"""The architecture pack (roadmap Epic H, H1): the architecture graph for implementation, aligned
with CALM 1.0 (the FINOS Common Architecture Language Model), on software-architecture.

    calm_id, calm_type       a CALM node is an estate node: system, service, database, network, actor, ...
    Relationship             a CALM relationship as a node: interacts, connects, deployed-in, composed-of, options; its protocol
    Control, Flow, FlowStep  what governs a node or a connection; an ordered walk over relationships
    NFR, Evidence            a requirement with a metric and a budget, and what measured it
    CodeModule, Commit       where a component is implemented, and what last changed it
    ChangeProposal           a proposed change, raised by evidence, settled by a decision, implemented in a commit
"""
import contextlib
import io
import json
import os

import pytest

from oto.cli import main
from oto.model import ontologies
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "oto", "ontologies", "architecture")
CALM = "https://calm.finos.org/release/1.0/meta/core.json"
NODE_TYPES = ["actor", "ecosystem", "system", "service", "database", "network", "ldap", "webclient", "data-asset"]
RELATIONSHIP_KINDS = ["interacts", "connects", "deployed-in", "composed-of", "options"]
PROTOCOLS = ["HTTP", "HTTPS", "FTP", "SFTP", "JDBC", "WebSocket", "SocketIO", "LDAP", "AMQP", "TLS", "mTLS", "TCP"]


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _own():
    with open(os.path.join(PACK, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _enum(spec):
    assert spec["type"].startswith("enum:"), spec
    return spec["type"][5:].split("|")


# ---- the vocabulary ----

def test_the_pack_sits_on_software_architecture_and_pins_calm():
    manifest = ontologies.manifest_for("architecture")
    assert manifest["extends"] == ["software-architecture"] and manifest["release"] == 1 and manifest["domain"] == "software"
    assert manifest["engine"] == ">=0.11" and CALM in manifest["summary"], "the CALM release is pinned where the pack says what it is"
    assert ontologies.self_check("architecture") == [], ontologies.self_check("architecture")
    config, _sample, readme = ontologies.load("architecture")
    assert {"Relationship", "Control", "Flow", "FlowStep", "NFR", "Evidence", "CodeModule", "Commit", "ChangeProposal"} <= set(config["classes"])
    assert {"System", "Component", "Interface", "DataStore", "Environment", "Role", "Requirement", "Decision", "Repository"} <= set(config["classes"]), \
        "composed on the estate: nothing is declared twice"
    assert set(_own()["classes"]) == {"Relationship", "Control", "Flow", "FlowStep", "NFR", "Evidence", "CodeModule", "Commit", "ChangeProposal"}, \
        "a CALM node is an estate node, not a class of its own"
    assert CALM in readme and ("first draft" in readme.lower() or "edit it" in readme.lower())


def test_a_calm_node_is_an_estate_node_with_its_id_and_type():
    own = _own()
    for kind in ("System", "Component", "DataStore", "Environment"):
        assert own["attributes"][kind]["calm_id"]["type"] == "string", kind
        assert _enum(own["attributes"][kind]["calm_type"]) == NODE_TYPES, kind
        assert own["attributes"][kind]["calm_metadata"]["type"] == "string", "metadata carried as given, never read"
    assert own["attributes"]["Role"]["calm_id"]["type"] == "string", "an actor is a role"
    assert own["attributes"]["Interface"]["calm_id"]["type"] == "string"
    assert own["attributes"]["Interface"]["definition_url"]["type"] == "string" and own["attributes"]["Interface"]["config"]["type"] == "string", \
        "an interface definition: the schema it conforms to and its configuration, as given"
    config, _sample, _readme = ontologies.load("architecture")
    assert config["attributes"]["Interface"]["url"]["type"] == "string", "the estate's own url stays"


def test_a_relationship_is_a_node_with_its_ends_its_kind_and_its_protocol():
    own = _own()
    rel = own["attributes"]["Relationship"]
    assert _enum(rel["kind"]) == RELATIONSHIP_KINDS and rel["kind"]["required"] is True
    assert _enum(rel["protocol"]) == PROTOCOLS
    assert rel["calm_id"]["required"] is True and rel["calm_metadata"]["type"] == "string"
    props = own["properties"]
    assert props["connects_from"]["domain"] == "Relationship" and set(props["connects_from"]["range"].split("|")) == {"System", "Component", "DataStore", "Environment", "Role"}
    assert props["connects_to"]["domain"] == "Relationship" and set(props["connects_to"]["range"].split("|")) == {"System", "Component", "DataStore", "Environment"}
    assert props["via"] == dict(props["via"], domain="Relationship", range="Interface")
    assert props["offers_option"] == dict(props["offers_option"], domain="Relationship", range="Decision"), "an options relationship offers decisions; `offers` is the product pack's"
    assert props["safeguards"]["domain"] == "Control" and {"Relationship", "Flow", "Component", "DataStore"} <= set(props["safeguards"]["range"].split("|"))
    assert "governs" not in props, "a decision's `governs` stays the decision's: a control has its own relation, so what no control safeguards can be asked"
    control = own["attributes"]["Control"]
    assert control["calm_id"]["required"] is True and control["requirement_url"]["required"] is True
    assert control["config_url"]["type"] == "string" and control["config"]["type"] == "string"


def test_a_flow_is_ordered_steps_over_relationships():
    own = _own()
    step = own["attributes"]["FlowStep"]
    assert step["sequence"]["type"] == "integer" and step["sequence"]["required"] is True
    assert _enum(step["direction"]) == ["source-to-destination", "destination-to-source"] and step["direction"]["default"] == "source-to-destination"
    assert own["properties"]["step_of"] == dict(own["properties"]["step_of"], domain="FlowStep", range="Flow", min=1, max=1)
    assert own["properties"]["over"] == dict(own["properties"]["over"], domain="FlowStep", range="Relationship", min=1, max=1)
    assert own["attributes"]["Flow"]["calm_id"]["required"] is True and own["attributes"]["Flow"]["requirement_url"]["type"] == "string"


def test_implementation_traces_from_a_requirement_through_evidence_code_and_commits():
    own = _own()
    assert own["classes"]["NFR"]["subclass_of"] == ["Requirement"], "a non-functional requirement is a requirement"
    assert own["attributes"]["NFR"]["metric"]["required"] is True and own["attributes"]["NFR"]["budget"]["type"] == "string"
    assert _enum(own["attributes"]["Evidence"]["kind"]) == ["measurement", "test", "review", "gate", "log"] and own["attributes"]["Evidence"]["kind"]["required"] is True
    assert own["attributes"]["Evidence"]["observed_on"]["type"] == "date" and own["attributes"]["Evidence"]["value"]["type"] == "string"
    props = own["properties"]
    assert props["measurement_of"] == dict(props["measurement_of"], domain="Evidence", range="NFR")
    assert "ChangeProposal" in props["evidence_of"]["range"].split("|") and "Component" in props["evidence_of"]["range"].split("|")
    assert own["attributes"]["CodeModule"]["path"]["required"] is True and own["attributes"]["CodeModule"]["language"]["type"] == "string"
    assert set(props["implemented_by"]["range"].split("|")) == {"Repository", "CodeModule"} and props["implemented_by"]["domain"] == "Component", "widened to the module"
    assert props["located_in"] == dict(props["located_in"], domain="CodeModule", range="Repository", max=1)
    assert own["attributes"]["Commit"]["sha"]["required"] is True and own["attributes"]["Commit"]["committed_on"]["type"] == "date"
    assert props["touches"] == dict(props["touches"], domain="Commit", range="CodeModule")
    assert _enum(own["attributes"]["ChangeProposal"]["status"]) == ["proposed", "accepted", "rejected", "implemented"] and own["attributes"]["ChangeProposal"]["status"]["default"] == "proposed"
    assert props["prompted_by"] == dict(props["prompted_by"], domain="ChangeProposal", range="Evidence"), "`triggered_by` and `raised_by` belong to the ddd pack: no name is declared twice across the packs that compose"
    assert props["decided_in"] == dict(props["decided_in"], domain="ChangeProposal", range="Decision", max=1)
    assert props["implemented_in"] == dict(props["implemented_in"], domain="ChangeProposal", range="Commit")
    assert "Control" in props["proposes_change_to"]["range"].split("|") and "Relationship" in props["proposes_change_to"]["range"].split("|")


def test_no_relation_or_inverse_name_collides_with_another_pack():
    """The packs compose: a name declared twice with two meanings is a composition error, so none is."""
    own = _own()
    names = {rel for rel in own["properties"] if rel != "implemented_by"}
    names |= {spec["inverse"] for rel, spec in own["properties"].items() if rel != "implemented_by" and spec.get("inverse")}
    import glob
    for path in glob.glob(os.path.join(ROOT, "oto", "ontologies", "*", "ontology.config.json")):
        pack = os.path.basename(os.path.dirname(path))
        if pack == "architecture":
            continue
        with open(path, encoding="utf-8") as f:
            other = json.load(f)
        taken = set(other.get("properties") or {}) | {s["inverse"] for s in (other.get("properties") or {}).values() if s.get("inverse")}
        assert not names & taken, (pack, names & taken)
        assert not set(own["classes"]) & set(other.get("classes") or {}) or pack in ("software-architecture", "product", "portfolio"), (pack, set(own["classes"]) & set(other["classes"]))


# ---- the questions ----

def test_the_questions_say_what_the_graph_is_for():
    questions = ontologies.questions_for("architecture")
    ids = [q for q in questions if q.startswith("AR")]
    assert ids == ["AR%d" % i for i in range(1, 10)], ids
    asks = {q: questions[q]["question"].lower() for q in ids}
    assert "NODE" in questions["AR1"]["params"] and "protocol" in asks["AR1"], "AR1: what a node connects to"
    assert "NODE" in questions["AR2"]["params"] and "control" in asks["AR2"], "AR2: what safeguards it"
    assert "FLOW" in questions["AR3"]["params"] and "sequence" in asks["AR3"] or "order" in asks["AR3"], "AR3: a flow's steps"
    assert "NODE" in questions["AR4"]["params"] and "budget" in asks["AR4"], "AR4: the budgets a node must meet"
    assert "NODE" in questions["AR5"]["params"] and "commit" in asks["AR5"], "AR5: where it is implemented"
    assert "NFR" in questions["AR6"]["params"] and "evidence" in asks["AR6"], "AR6: what measured a requirement"
    assert "proposal" in asks["AR7"] and "evidence" in asks["AR7"], "AR7: the open change proposals"
    assert "control" in asks["AR8"] and "no control" in asks["AR8"], "AR8: nodes no control safeguards"
    assert "module" in asks["AR9"] and ("trace" in asks["AR9"] or "no node" in asks["AR9"]), "AR9: untraced code"
    assert questions["AR8"]["gate"] == "any" and questions["AR9"]["gate"] == "any"


def test_the_sample_is_the_invoice_approval_example():
    _config, sample, _readme = ontologies.load("architecture")
    own = {n["id"]: n for n in sample["nodes"] if n.get("source_doc") == "invoice-architecture"}, "the estate's own sample composes beside it"
    own = own[0]
    kinds = {n["type"] for n in own.values()}
    assert {"Relationship", "Control", "Flow", "FlowStep", "NFR", "Evidence", "CodeModule", "Commit", "ChangeProposal", "System", "Component", "DataStore", "Environment", "Role", "Interface", "Decision", "Repository"} <= kinds
    relationships = [n for n in own.values() if n["type"] == "Relationship"]
    assert {n["attributes"]["kind"] for n in relationships} == set(RELATIONSHIP_KINDS), "one of each CALM shape"
    assert all(n["attributes"].get("calm_id") for n in relationships)
    assert {n["attributes"].get("protocol") for n in relationships if n["attributes"]["kind"] == "connects"} <= set(PROTOCOLS)
    components = [n for n in own.values() if n["type"] == "Component"]
    assert all(n["attributes"]["calm_type"] == "service" and n["attributes"]["calm_id"] for n in components)
    assert any(n["type"] == "DataStore" and n["attributes"]["calm_type"] == "database" for n in own.values())
    assert any(n["type"] == "Environment" and n["attributes"]["calm_type"] == "network" for n in own.values())
    assert any(n["type"] == "Role" and n["attributes"].get("calm_id") for n in own.values()), "the clerk is the actor"
    steps = sorted((n["attributes"]["sequence"] for n in own.values() if n["type"] == "FlowStep"))
    assert steps == [1, 2, 3]
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert ("control.pii-at-rest", "safeguards", "datastore.invoice-db") in edges and ("control.pii-at-rest", "safeguards", "relationship.intake-stores") in edges
    assert ("evidence.k6-2026-10-20", "measurement_of", "nfr.req-042") in edges and ("component.invoice-intake", "satisfies", "nfr.req-042") in edges
    assert ("changeproposal.cp-001", "prompted_by", "evidence.gate-2026-10-21") in edges and own["changeproposal.cp-001"]["attributes"].get("status", "proposed") == "proposed"
    assert ("changeproposal.cp-000", "decided_in", "decision.adr-007") in edges and ("changeproposal.cp-000", "implemented_in", "commit.9f3c2a1") in edges
    assert ("commit.9f3c2a1", "touches", "codemodule.src-intake") in edges and ("component.invoice-intake", "implemented_by", "codemodule.src-intake") in edges
    assert all(("component.%s" % c, "part_of", "system.invoice-platform") in edges and ("component.%s" % c, "runs_in", "environment.payments-network") in edges
               for c in ("invoice-intake", "approval-policy", "payment-scheduler")), "the estate's own shapes hold"
    assert "codemodule.src-legacy" in own and not any(to == "codemodule.src-legacy" and rel == "implemented_by" for _f, rel, to in edges), "one module nothing traces to, for AR9"


# ---- installed ----

@pytest.fixture
def invoice(tmp_path):
    root = str(tmp_path / "invoice")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="invoice", name="Invoice approval, as architecture", ontology="architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


def test_the_installed_project_answers_what_a_node_connects_to_what_governs_it_and_where_it_is_implemented(invoice):
    code, out = _cli("query", "--project", invoice, "ask", "AR1", "NODE=component.invoice-intake")
    assert code == 0 and "status: answered" in out and "JDBC" in out and "AMQP" in out and "Invoice database" in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR2", "NODE=datastore.invoice-db")
    assert code == 0 and "status: answered" in out and "PII encrypted at rest" in out and "encryption-at-rest.requirement.json" in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR3", "FLOW=flow.invoice-approval")
    assert code == 0 and "status: answered" in out and out.count("sequence=") == 3 and "destination-to-source" not in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR4", "NODE=component.invoice-intake")
    assert code == 0 and "status: answered" in out and "900 ms" in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR5", "NODE=component.invoice-intake")
    assert code == 0 and "status: answered" in out and "src/intake" in out and "9f3c2a1" in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR6", "NFR=nfr.req-042")
    assert code == 0 and "status: answered" in out and "870 ms" in out and "measurement" in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR7")
    assert code == 0 and "status: answered" in out and "cp-001" in out.lower() and "cp-000" not in out.lower(), "only the open proposals"
    code, out = _cli("query", "--project", invoice, "ask", "AR8")
    assert code == 0 and "status: answered" in out and "Payment scheduler" in out and "Invoice database" not in out, out
    code, out = _cli("query", "--project", invoice, "ask", "AR9")
    assert code == 0 and "status: answered" in out and "src/legacy" in out and "src/intake" not in out, out
    code, out = _cli("query", "--project", invoice, "ask", "SA1", "SYSTEM=system.invoice-platform")
    assert code == 0 and "status: answered" in out and "Invoice intake" in out, "the estate's own questions still answer: one vocabulary"
    code, out = _cli("ontology", "check", "--project", invoice)
    assert code == 0 and "every node satisfies them" in out, out


def test_the_docs_name_the_pack():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "ontologies/architecture" in text and "CALM" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        assert "oto init" in f.read() and "architecture" in text
