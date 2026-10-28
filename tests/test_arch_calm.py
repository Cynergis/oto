"""CALM in and out (roadmap Epic H, H1's done-when): a CALM model maps into the graph with nothing
lost, and comes back out the same.

`oto arch import --framework calm --file model.json --at <date>` reads a CALM 1.x model into a document in the corpus
(one line per node, interface, relationship, control, flow and step, each the evidence its fact
quotes) and a proposal in the architecture vocabulary that goes through the gates like any other
change: a CALM node is an estate node with its id and type, a relationship is a `Relationship` node
with its ends, controls and flows are nodes, and the plain estate edges (part_of, runs_in, exposes,
consumes, depends_on) are derived beside them so the estate's questions answer. What CALM carries
that the questions do not ask for (metadata, details, an interface's fields, a control's
requirements, an option's lists, the model's own header) is kept as the JSON it was given, so
`oto arch export --framework calm` writes the model back: export of import equals the input."""
import contextlib
import io
import json
import os

import pytest

from oto import arch
from oto.packs import calm as _calm
from oto.cli import main
from oto.curate import session
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "calm")
INVOICE = os.path.join(FIXTURES, "invoice-platform.calm.json")
TRADING = os.path.join(FIXTURES, "trading-system.architecture.json")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _gates(root, proposal, note):
    for step in (("curate", "start"), ("curate", "add", "--from", proposal), ("curate", "check"),
                 ("curate", "apply", "--by", "Sam Lee", "--note", note)):
        code, out = _cli(*step, "--project", root)
        assert code == 0 and "not in the document" not in out and "blocking" not in out.split("gap (")[0], (step, out)
    code, out = _cli("build", "--project", root)
    assert code == 0, out


def canonical(model):
    """The model with what export cannot tell apart from absence removed: empty interface lists,
    empty controls, transitions in sequence order."""
    out = json.loads(json.dumps(model))
    for n in out.get("nodes") or []:
        for key in ("interfaces", "controls"):
            if key in n and not n[key]:
                del n[key]
    for f in out.get("flows") or []:
        f["transitions"] = sorted(f.get("transitions") or [], key=lambda t: t["sequence-number"])
    return out


@pytest.fixture
def empty(tmp_path):
    """An architecture project with no sample, an environment declared for what CALM does not deploy."""
    root = str(tmp_path / "arch")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="arch", name="Architecture", ontology="architecture", empty=True)
    seed = os.path.join(root, "seed.json")
    with open(seed, "w", encoding="utf-8") as f:
        json.dump({"source_doc": "estate", "as_of": "2026-10-01", "nodes": [
            {"id": "environment.production", "type": "Environment", "label": "Production", "attributes": {}}], "edges": []}, f)
    _gates(root, seed, "the environment")
    return root


# ---- the mapping, as a function ----

def test_a_calm_model_maps_into_the_vocabulary_with_nothing_lost():
    model = _load(INVOICE)
    proposal, gaps = _calm.propose(model, "calm-invoice-platform", "2026-10-27")
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert nodes["system.invoice-platform"]["type"] == "System" and nodes["system.invoice-platform"]["attributes"]["external_type"] == "system"
    assert json.loads(nodes["system.invoice-platform"]["attributes"]["external_payload"]) == {"details": {"detailed-architecture": "https://invoice.example/calm/invoice-platform-detailed.json"}}
    assert nodes["environment.payments-network"]["type"] == "Environment" and nodes["role.ap-clerk"]["type"] == "Role"
    assert json.loads(nodes["role.ap-clerk"]["attributes"]["external_payload"]) == {"metadata": {"department": "finance"}}, "metadata and details travel as one payload"
    assert nodes["component.invoice-intake"]["type"] == "Component" and nodes["component.invoice-intake"]["label"] == "Invoice intake"
    assert nodes["datastore.invoice-db"]["type"] == "DataStore" and nodes["datastore.invoice-db"]["attributes"]["external_type"] == "database"
    assert nodes["component.reporting-lake"]["type"] == "Component" and nodes["component.reporting-lake"]["attributes"]["external_type"] == "lakehouse", "a custom node type is kept, and the node is a component"
    api = nodes["interface.invoice-api"]
    assert api["type"] == "Interface" and api["attributes"]["external_id"] == "invoice-api" and api["attributes"]["definition_url"].endswith("https-url.json")
    assert api["attributes"]["url"] == "https://invoice.example/api/v1/invoices", "a url inside the config is also the estate's url"
    assert json.loads(api["attributes"]["config"]) == {"definition-url": "https://invoice.example/calm/interfaces/https-url.json", "config": {"url": "https://invoice.example/api/v1/invoices"}}
    events = nodes["interface.invoice-events"]
    assert events["label"] == "Invoice events" and json.loads(events["attributes"]["config"]) == {"name": "Invoice events", "protocol": "AMQP", "exchange": "invoices", "routing-key": "invoice.*"}
    rel = nodes["relationship.intake-stores"]
    assert rel["type"] == "Relationship" and rel["attributes"]["kind"] == "connects" and rel["attributes"]["protocol"] == "JDBC"
    assert json.loads(rel["attributes"]["external_payload"]) == {"metadata": {"pii": True}} and rel["summary"] == "The intake writes the invoice to the database."
    assert nodes["relationship.policy-schedules"]["summary"] == "" and nodes["relationship.policy-schedules"]["label"] == "policy-schedules", "no description: the id is the label"
    assert nodes["relationship.store-options"]["attributes"]["kind"] == "options"
    option = nodes["decision.store-options-2"]
    assert option["type"] == "Decision" and option["label"] == "Move the invoice store to a managed ledger service." and option["attributes"]["status"] == "proposed"
    assert json.loads(option["attributes"]["external_payload"])["controls"] == ["pii-at-rest"]
    assert nodes["control.model-encryption-in-transit"]["type"] == "Control" and nodes["control.model-encryption-in-transit"]["attributes"]["requirement_url"].endswith("encryption-in-transit.requirement.json")
    assert json.loads(nodes["control.model-encryption-in-transit"]["attributes"]["config"])["requirements"][0]["config"] == {"protocol": "TLS", "minimumVersion": "1.3"}
    assert nodes["control.invoice-intake-input-validation"]["type"] == "Control", "a node's control is scoped to the node"
    assert nodes["control.intake-stores-pii-at-rest"]["attributes"]["config_url"].endswith("encryption-at-rest.config.json")
    assert nodes["control.invoice-approval-four-eyes"]["type"] == "Control", "a flow's control is scoped to the flow"
    flow = nodes["flow.invoice-approval"]
    assert flow["type"] == "Flow" and flow["attributes"]["requirement_url"].endswith("invoice-approval.requirement.json")
    steps = {n["attributes"]["sequence"]: n for n in nodes.values() if n["type"] == "FlowStep"}
    assert set(steps) == {1, 2, 3} and "direction" not in steps[1]["attributes"] and steps[3]["attributes"]["direction"] == "destination-to-source", "a direction is kept only when the model said it"
    doc = nodes["document.calm-invoice-platform"]
    assert doc["type"] == "Document" and doc["attributes"]["kind"] == "architecture" and doc["label"] == "CALM model Invoice platform", "named apart from the system of the same name"
    header = json.loads(doc["attributes"]["external_payload"])
    assert header["$id"] == "https://invoice.example/calm/invoice-platform.json" and header["adrs"] == ["https://invoice.example/adrs/ADR-007.md"] and header["metadata"] == {"owner": "payments-platform", "tier": "2"}
    assert not any(k in header for k in ("nodes", "relationships", "controls", "flows"))
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("relationship.clerk-submits", "connects_from", "role.ap-clerk") in edges and ("relationship.clerk-submits", "connects_to", "component.invoice-intake") in edges
    assert ("relationship.intake-emits", "via", "interface.invoice-events") in edges
    assert ("relationship.deployed-in-network", "connects_from", "environment.payments-network") in edges and ("relationship.deployed-in-network", "connects_to", "datastore.invoice-db") in edges
    assert ("relationship.store-options", "offers_option", "decision.store-options-1") in edges
    assert ("control.intake-stores-pii-at-rest", "safeguards", "relationship.intake-stores") in edges and ("control.invoice-intake-input-validation", "safeguards", "component.invoice-intake") in edges
    assert ("control.invoice-approval-four-eyes", "safeguards", "flow.invoice-approval") in edges
    assert not any(f == "control.model-encryption-in-transit" for f, _r, _t in edges), "a model-level control safeguards nothing in particular"
    assert ("flowstep.invoice-approval-2", "over", "relationship.intake-emits") in edges and ("flowstep.invoice-approval-2", "step_of", "flow.invoice-approval") in edges
    # the estate's own edges, derived
    assert ("component.invoice-intake", "part_of", "system.invoice-platform") in edges and ("datastore.invoice-db", "part_of", "system.invoice-platform") in edges
    assert ("component.invoice-intake", "runs_in", "environment.payments-network") in edges and ("datastore.invoice-db", "runs_in", "environment.payments-network") in edges
    assert ("component.invoice-intake", "exposes", "interface.invoice-api") in edges and ("component.invoice-intake", "exposes", "interface.invoice-events") in edges
    assert ("component.approval-policy", "consumes", "interface.invoice-events") in edges, "a connection through an interface: the destination side consumes it"
    assert ("component.approval-policy", "depends_on", "component.payment-scheduler") in edges, "a connection with no interface: depends_on"
    assert not any(rel in ("reads_from", "writes_to") for _f, rel, _t in edges), "CALM does not say whether a connection to a store reads or writes"
    assert any("reporting-lake" in g and "composed" in g for g in gaps) or any("reporting-lake" in g for g in gaps), "a component nothing composes or deploys is a gap the gates will name"
    assert all(n.get("evidence") for n in proposal["nodes"]), "every node quotes its line"


def test_the_model_s_own_header_and_the_relationship_type_as_a_string_are_read():
    model = _load(INVOICE)
    model["relationships"][0] = {"unique-id": "clerk-submits", "relationship-type": "interacts", "interacts": {"actor": "ap-clerk", "nodes": ["invoice-intake"]}}
    proposal, _gaps = _calm.propose(model, "calm-x", "2026-10-27")
    assert {n["id"] for n in proposal["nodes"] if n["type"] == "Relationship"} >= {"relationship.clerk-submits"}, "the older form, relationship-type as a string beside its body"
    assert any(e["from"] == "relationship.clerk-submits" and e["rel"] == "connects_from" for e in proposal["edges"])


def test_what_is_not_a_model_is_refused():
    with pytest.raises(arch.ArchError):
        _calm.propose({"relationships": []}, "calm-x", "2026-10-27")
    with pytest.raises(arch.ArchError) as e:
        _calm.propose({"nodes": [{"unique-id": "a", "node-type": "service", "name": "A", "description": ""}],
                      "relationships": [{"unique-id": "r", "relationship-type": {"connects": {"source": {"node": "a"}, "destination": {"node": "nowhere"}}}}]}, "calm-x", "2026-10-27")
    assert "nowhere" in str(e.value)
    with pytest.raises(arch.ArchError) as e:
        _calm.propose({"nodes": [{"unique-id": "a", "node-type": "service", "name": "A", "description": ""}, {"unique-id": "a", "node-type": "service", "name": "A2", "description": ""}],
                      "relationships": []}, "calm-x", "2026-10-27")
    assert "twice" in str(e.value) or "duplicate" in str(e.value).lower()
    with pytest.raises(arch.ArchError):
        _calm.propose({"nodes": [{"node-type": "service", "name": "A", "description": ""}], "relationships": []}, "calm-x", "2026-10-27")


# ---- the command ----

def test_import_writes_the_document_and_the_proposal_and_the_gates_take_it(empty):
    root = empty
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    assert "8 node(s)" in out and "7 relationship(s)" in out and "calm-invoice-platform" in out and "curate add" in out, out
    assert "reporting-lake" in out and "composed" in out, "the gap the gates would name is said first"
    text = open(os.path.join(root, "build", "documents", "calm-invoice-platform.md"), encoding="utf-8").read()
    assert text.startswith("# CALM model Invoice platform") and "- invoice-intake (service)" in text and "  - interface invoice-events" in text
    assert "- intake-stores (connects, JDBC)" in text and "- flow invoice-approval" in text and "  - step 3 over policy-schedules" in text and "- control model/encryption-in-transit" in text
    assert os.path.exists(os.path.join(root, "archive", "calm-invoice-platform.md"))
    with open(os.path.join(root, "proposals", "calm-invoice-platform.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    assert proposal["source_doc"] == "calm-invoice-platform" and proposal["as_of"] == "2026-10-27"
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "add", "--from", os.path.join(root, "proposals", "calm-invoice-platform.json"), "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "check", "--project", root)
    assert code == 1 and "reporting-lake" in out and "part_of" in out, "the lakehouse nothing composes: the estate's shape, named at the gate"
    code, out = _cli("curate", "abort", "--project", root)
    assert code == 0, out
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-27", "--environment", "environment.production", "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "proposals", "calm-invoice-platform.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("component.reporting-lake", "runs_in", "environment.production") in edges and ("component.invoice-intake", "runs_in", "environment.payments-network") in edges, \
        "--environment deploys what CALM did not; what CALM deployed keeps its network"
    assert ("component.reporting-lake", "part_of", "system.invoice-platform") not in edges, "composition is the model's to say; the gate will still ask for it"


def test_round_trip_of_the_invoice_model_is_exact(empty):
    root = empty
    model = _load(INVOICE)
    model["relationships"] = [r for r in model["relationships"]]
    model["nodes"] = [n for n in model["nodes"] if n["unique-id"] != "reporting-lake"]      # the one node CALM composes in nothing
    path = os.path.join(root, "invoice.calm.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    code, out = _cli("arch", "import", "--framework", "calm", "--file", path, "--at", "2026-10-27", "--project", root)
    assert code == 0, out
    _gates(root, os.path.join(root, "proposals", "calm-invoice.json"), "the CALM model")
    code, out = _cli("arch", "export", "--framework", "calm", "--project", root)
    assert code == 0, out
    assert json.loads(out) == model, "export of import is the input"
    code, out = _cli("query", "--project", root, "ask", "AR1", "NODE=component.invoice-intake")
    assert code == 0 and "status: answered" in out and "JDBC" in out and "AMQP" in out, out
    code, out = _cli("query", "--project", root, "ask", "AR3", "FLOW=flow.invoice-approval")
    assert code == 0 and out.count("sequence=") == 3 and "destination-to-source" in out, out
    code, out = _cli("query", "--project", root, "ask", "SA1", "SYSTEM=system.invoice-platform")
    assert code == 0 and "status: answered" in out and "Invoice intake" in out, "the estate's question answers from the derived edges"
    code, out = _cli("ontology", "check", "--project", root)
    assert code == 0 and "every node satisfies them" in out, out
    out_path = os.path.join(root, "exported.calm.json")
    code, out = _cli("arch", "export", "--framework", "calm", "--out", out_path, "--project", root)
    assert code == 0 and os.path.exists(out_path) and _load(out_path) == model


def test_round_trip_of_finos_trading_system(empty):
    """A real model from the FINOS repository (Apache-2.0): thirteen nodes of seven types, sixteen
    connections, interfaces with their own fields, seven flows, model-level controls and metadata."""
    root = empty
    model = _load(TRADING)
    code, out = _cli("arch", "import", "--framework", "calm", "--file", TRADING, "--at", "2026-10-27", "--environment", "environment.production", "--project", root)
    assert code == 0 and "13 node(s)" in out and "18 relationship(s)" in out, out
    _gates(root, os.path.join(root, "proposals", "calm-trading-system.json"), "the trading system")
    code, out = _cli("arch", "export", "--framework", "calm", "--project", root)
    assert code == 0, out
    assert canonical(json.loads(out)) == canonical(model), "export of import is the input, up to empty containers"
    code, out = _cli("query", "--project", root, "ask", "AR1", "NODE=component.web-gui")
    assert code == 0 and "status: answered" in out and "HTTPS" in out, out
    code, out = _cli("query", "--project", root, "ask", "AR8")
    assert code == 0 and "status: answered" in out and "Trade Service" in out, "a model-level control safeguards nothing in particular, so every node is on the gap list"
    code, out = _cli("query", "--project", root, "ask", "SA1", "SYSTEM=system.trading-system")
    assert code == 0 and "status: answered" in out and "Trade Service" in out, out


def test_import_and_export_refuse_what_they_cannot_do(empty, tmp_path):
    root = empty
    code, out = _cli("arch", "export", "--framework", "calm", "--project", root)
    assert code == 1 and "no CALM" in out, "nothing imported, nothing to export"
    code, out = _cli("arch", "import", "--framework", "calm", "--file", str(tmp_path / "missing.json"), "--at", "2026-10-27", "--project", root)
    assert code == 1 and "missing.json" in out, out
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out = _cli("arch", "import", "--framework", "calm", "--file", str(bad), "--at", "2026-10-27", "--project", root)
    assert code == 1 and "JSON" in out, out
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--project", root)
    assert code == 1 and "--at" in out, "the date is never defaulted"
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-27", "--environment", "environment.nope", "--project", root)
    assert code == 1 and "environment.nope" in out, out
    plain = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(plain, slug="plain", name="Plain", ontology="communication")
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-27", "--project", plain)
    assert code == 1 and "Relationship" in out and "architecture" in out, out
    assert not os.path.exists(os.path.join(root, "proposals", "calm-invoice-platform.json"))


def test_the_docs_and_the_licence_name_the_fixture():
    with open(os.path.join(ROOT, "THIRD-PARTY-LICENSES.md"), encoding="utf-8") as f:
        assert "trading-system.architecture.json" in f.read()
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto arch import" in text and "oto arch export" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        assert "oto arch import --framework calm --file" in f.read()
