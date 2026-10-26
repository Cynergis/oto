"""arch_context and the trace and impact queries (roadmap Epic H, H3 and H4).

`arch_context` is the served tool an agent calls before it edits: for a path of the code or a node
of the architecture, the node, the requirements it satisfies with each budget and the latest
measured value, the decisions that govern it, the controls on it and on its connections, its
connections, the modules that implement it with their last commit, and the open change proposals
about it. `oto arch impact` reads the graph for what a decision affects (the nodes it governs,
their connections, modules and open proposals, and whether it is superseded), the orphans (nodes
no relationship reaches) and the untraced code (modules nothing implements, components with no
module); with `--files` it reports the impact of every decision record among the files a pull
request changed, which the checks workflow posts as a comment."""
import contextlib
import io
import json
import os

import pytest

from oto import arch, repo as _repo
from oto.cli import main
from oto.project import Project
from oto.scaffold import init
from oto.serve import http as _http

from test_apps import _engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _call(engine, name, **arguments):
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    result = reply["result"]
    return result["isError"], "".join(c["text"] for c in result["content"])


@pytest.fixture
def invoice(tmp_path):
    """The architecture pack's sample, built: the invoice-approval example with its trace to code."""
    root = str(tmp_path / "invoice")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="invoice", name="Invoice approval", ontology="architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


# ---- the served tool ----

def test_arch_context_for_a_node_gives_what_an_agent_must_know_before_editing(invoice):
    engine = _engine(Project.standard(invoice))
    error, text = _call(engine, "arch_context", node="component.invoice-intake")
    assert not error, text
    assert text.startswith("=== Invoice intake  [Component]  (component.invoice-intake) ===")
    assert "REQ-042" in text and "budget 900 ms, measured 870 ms on 2026-10-20" in text, "the budget and the latest measurement, side by side"
    assert "decisions: none recorded" in text
    assert "PII encrypted at rest on Intake stores the invoice" in text and "encryption-at-rest.requirement.json" in text, "a control on a connection of the node counts"
    assert "→ Invoice database (connects, JDBC)" in text and "→ Approval policy (connects, AMQP)" in text and "← Accounts payable clerk (interacts)" in text
    assert "src/intake (python), last touched 9f3c2a1 on 2026-10-18 by Sam Lee" in text
    assert "open change proposals" not in text


def test_arch_context_for_a_path_resolves_the_module_and_its_component(invoice):
    engine = _engine(Project.standard(invoice))
    error, text = _call(engine, "arch_context", path="src/scheduler/jobs/nightly.py")
    assert not error, text
    assert "[Component]  (component.payment-scheduler)" in text and "from src/scheduler/jobs/nightly.py (src/scheduler)" in text, "the longest module path that covers the file"
    assert "ADR-007: read invoice data only through the intake's API [accepted]: One writer and one read path" in text
    assert "controls: none" in text
    assert "open change proposals:" in text and "CP-001" in text
    error, text = _call(engine, "arch_context", path="./src/legacy/old.js")
    assert not error and "untraced" in text and "src/legacy" in text and "AR9" in text, "a module nothing implements: said, not guessed"
    error, text = _call(engine, "arch_context", path="docs/nothing.md")
    assert error and "docs/nothing.md" in text and "oto arch map" in text, "no module covers it"
    error, text = _call(engine, "arch_context")
    assert error and "path" in text and "node" in text
    error, text = _call(engine, "arch_context", node="no such thing anywhere")
    assert "no " in text.lower()


def test_arch_context_is_served_over_http_and_forwarded_across_graphs():
    assert _http.ROUTES["arch-context"] == "arch_context"
    from oto.serve import engine
    assert "arch_context" in engine.FORWARDABLE, "a concierge can ask the architecture graph for a path's context"
    tool = engine.TOOL_BY_NAME["arch_context"]
    assert set(tool["inputSchema"]["properties"]) == {"path", "node"} and "before" in tool["description"]


# ---- impact ----

def test_impact_of_a_decision_names_what_it_governs_and_what_that_reaches(invoice):
    code, out = _cli("arch", "impact", "--decision", "decision.adr-007", "--project", invoice)
    assert code == 0, out
    assert "ADR-007" in out and "accepted" in out
    assert "Payment scheduler" in out and "Approval policy" in out, "what it governs"
    assert "src/scheduler" in out, "the modules that implement what it governs"
    assert "CP-001" in out, "the open proposals about what it governs"
    assert "Invoice intake" in out, "reached through a connection of what it governs"
    code, out2 = _cli("arch", "impact", "--decision", "ADR-007", "--project", invoice)
    assert code == 0 and out2 == out, "an ADR id names its decision"
    code, out = _cli("arch", "impact", "--decision", "decision.nope", "--project", invoice)
    assert code == 1 and "decision.nope" in out


def test_a_superseded_decision_s_impact_says_so():
    graph = {"nodes": [
        {"id": "decision.adr-001", "type": "Decision", "label": "ADR-001: one ledger", "summary": "", "attributes": {"status": "accepted"}, "status": "superseded", "superseded_by": "decision.adr-002"},
        {"id": "decision.adr-002", "type": "Decision", "label": "ADR-002: two ledgers", "summary": "", "attributes": {"status": "accepted"}, "status": "current"},
        {"id": "component.ledger", "type": "Component", "label": "Ledger", "summary": "", "attributes": {}, "status": "current"},
        {"id": "component.reports", "type": "Component", "label": "Reports", "summary": "", "attributes": {}, "status": "current"},
        {"id": "relationship.reads", "type": "Relationship", "label": "Reports read the ledger", "summary": "", "attributes": {"kind": "connects", "protocol": "HTTPS"}, "status": "current"},
        {"id": "codemodule.ledger", "type": "CodeModule", "label": "src/ledger", "summary": "", "attributes": {"path": "src/ledger"}, "status": "current"}],
        "edges": [{"from": "decision.adr-001", "rel": "governs", "to": "component.ledger"}, {"from": "relationship.reads", "rel": "connects_from", "to": "component.reports"},
                  {"from": "relationship.reads", "rel": "connects_to", "to": "component.ledger"}, {"from": "component.ledger", "rel": "implemented_by", "to": "codemodule.ledger"}]}
    report = arch.impact(graph, "decision.adr-001")
    assert report["superseded_by"] == "decision.adr-002" and report["status"] == "superseded"
    assert [g["id"] for g in report["governs"]] == ["component.ledger"]
    assert report["governs"][0]["connections"] == [{"id": "relationship.reads", "label": "Reports read the ledger", "kind": "connects", "protocol": "HTTPS", "other": "Reports", "other_id": "component.reports"}]
    assert report["governs"][0]["modules"] == ["src/ledger"] and report["reached"] == ["Reports"]
    text = arch.render_impact(report, "markdown")
    assert text.startswith("## Impact of ADR-001: one ledger") and "superseded by ADR-002: two ledgers" in text and "- Ledger (component.ledger)" in text
    with pytest.raises(arch.ArchError):
        arch.impact(graph, "component.ledger")


def test_orphans_and_untraced_code(invoice):
    code, out = _cli("arch", "impact", "--orphans", "--project", invoice)
    assert code == 0 and "orphan" in out.lower(), out
    assert "Payment API" in out, "the estate sample's components no relationship reaches"
    assert "Invoice intake" not in out and "Invoice database" not in out
    code, out = _cli("arch", "impact", "--untraced", "--project", invoice)
    assert code == 0, out
    assert "src/legacy" in out and "src/intake" not in out and "src/scheduler" not in out, "modules nothing implements"
    assert "Approval policy" in out and "Invoice intake" not in out, "components with no module"
    code, out = _cli("arch", "impact", "--project", invoice)
    assert code == 1 and "--decision" in out and "--orphans" in out and "--files" in out


def test_impact_of_the_decision_records_a_pull_request_changed(invoice, tmp_path):
    adr_dir = os.path.join(invoice, "docs", "adr")
    os.makedirs(adr_dir, exist_ok=True)
    adr = os.path.join(adr_dir, "0007-read-through-the-intake-api.md")
    with open(adr, "w", encoding="utf-8") as f:
        f.write("---\nid: ADR-007\ntitle: Read invoice data only through the intake's API\nstatus: accepted\ndecided_on: 2026-09-30\n---\n\n# Read through the API\n\n## Decision\n\nThe scheduler reads through the intake's API.\n")
    readme = os.path.join(invoice, "README.md")
    code, out = _cli("arch", "impact", "--files", adr, readme, str(tmp_path / "gone.md"), "--format", "markdown", "--project", invoice)
    assert code == 0, out
    assert out.startswith("## Impact of ADR-007") and "Payment scheduler" in out and "src/scheduler" in out and "CP-001" in out, out
    assert "README" not in out
    code, out = _cli("arch", "impact", "--files", readme, "--format", "markdown", "--project", invoice)
    assert code == 0 and out.strip() == "", "no decision record among the files: nothing to say"
    unknown = os.path.join(adr_dir, "0099-not-yet-in-the-graph.md")
    with open(unknown, "w", encoding="utf-8") as f:
        f.write("---\nid: ADR-099\nstatus: proposed\n---\n\n## Decision\n\nSomething new.\n")
    code, out = _cli("arch", "impact", "--files", unknown, "--format", "markdown", "--project", invoice)
    assert code == 0 and "ADR-099" in out and "not in the graph" in out, "a record the graph does not hold yet: said, so the reviewer knows"


def test_the_checks_workflow_posts_the_impact_of_changed_decision_records():
    files = _repo.files("acme", "Acme")
    checks = files[os.path.join(".github", "workflows", "oto-checks.yml")]
    assert "pull-requests: write" in checks and "fetch-depth: 0" in checks
    assert "oto arch impact --files" in checks and "--format markdown" in checks and "gh pr comment" in checks
    assert "docs/adr/" in checks and "github.event.pull_request.base.sha" in checks
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "arch_context" in text and "oto arch impact" in text
