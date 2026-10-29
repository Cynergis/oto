"""The generated system's IAM (roadmap E7): the active rules of the access policy, read through the
roles each principal holds, become the platform's bindings, a design-time output the deploy
pipeline carries and OTO never enforces (ADR-0005). The policy pack models the component that runs
as a principal (`runs_as`), the platform role a permission maps to (`cloud_role`) and where a
resource is on the platform (`resource_uri`); `oto policy iam` (and the `iam` build stage) writes
`build/iam/`: the bindings, the GCP form, the binding nodes as a proposal in the policy vocabulary,
each an `IamBinding` that `binds` the resource, `grants` the principals and `derives_from` the
rules it came from, hashed and signed like the policy bundle. A
forbid withholds the binding a permit would have made; what cannot bind is named, never guessed."""
import contextlib
import hashlib
import hmac
import io
import json
import os

import pytest

from oto import adr as _adr
from oto.packs import policy as _policy
from oto.packs.policy import iam as _iam
from oto.cli import main
from oto.curate import evidence as _evidence
from oto.curate import session as _session
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "oto", "ontologies", "policy")
ARCHITECTURE = os.path.join(ROOT, "oto", "ontologies", "architecture")
KEY_ENV = "OTO_POLICY_KEY"
INTAKE, RUNNER, CLERK = "serviceAccount:invoice-intake@acme.iam", "serviceAccount:factory-runner@acme.iam", "user:clerk@acme.example"
VIEWER, EDITOR = "roles/bigquery.dataViewer", "roles/bigquery.dataEditor"


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _own(pack):
    with open(os.path.join(pack, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _sample():
    config, sample, _readme = ontologies.load("policy")
    return config, sample


def _node(nid, type_, **attributes):
    return {"id": nid, "type": type_, "label": attributes.pop("label", nid), "attributes": attributes}


def _graph(nodes, edges):
    return {"nodes": nodes, "edges": [{"from": a, "rel": r, "to": b} for a, r, b in edges]}


def _ledger_graph(**changes):
    """A small policy over one table: a writer role permitted to write it, a reader role permitted to
    read it, two principals. `changes` override the nodes by id before the graph is built."""
    nodes = {
        "table.t": _node("table.t", "Table", label="t", resource_uri="//bigquery.googleapis.com/projects/p/datasets/d/tables/t"),
        "role.writer": _node("role.writer", "Role", label="Writer"),
        "role.reader": _node("role.reader", "Role", label="Reader"),
        "role.auditor": _node("role.auditor", "Role", label="Auditor"),
        "permission.write": _node("permission.write", "Permission", label="Write tables", action="write", resource_class="Table", cloud_role=EDITOR),
        "permission.read": _node("permission.read", "Permission", label="Read tables", action="read", resource_class="Table", cloud_role=VIEWER),
        "policyrule.writers-write": _node("policyrule.writers-write", "PolicyRule", label="Writers write", effect="permit", status="active", priority=10),
        "policyrule.readers-read": _node("policyrule.readers-read", "PolicyRule", label="Readers read", effect="permit", status="active", priority=10),
        "policyrule.auditors-never-write": _node("policyrule.auditors-never-write", "PolicyRule", label="Auditors never write", effect="forbid",
                                                status="active", priority=100),
        "principal.svc": _node("principal.svc", "Principal", label="The service", kind="service", identity="svc@p.iam"),
        "principal.ann": _node("principal.ann", "Principal", label="Ann", kind="person", identity="ann@example.com"),
        "component.api": _node("component.api", "Component", label="API", external_id="api", external_type="service"),
    }
    for nid, node in changes.items():
        if node is None:
            nodes.pop(nid, None)
        else:
            nodes[nid] = node
    edges = [("policyrule.writers-write", "for_role", "role.writer"), ("policyrule.writers-write", "of_permission", "permission.write"),
             ("policyrule.readers-read", "for_role", "role.reader"), ("policyrule.readers-read", "of_permission", "permission.read"),
             ("policyrule.auditors-never-write", "for_role", "role.auditor"), ("policyrule.auditors-never-write", "of_permission", "permission.write"),
             ("principal.svc", "holds_role", "role.writer"), ("principal.svc", "holds_role", "role.reader"),
             ("principal.ann", "holds_role", "role.reader"), ("component.api", "runs_as", "principal.svc")]
    return _graph(list(nodes.values()), edges)


CLASSES = ["Table", "Role", "Permission", "PolicyRule", "Principal", "Component", "IamBinding"]


# ---- the model ----

def test_the_policy_pack_models_who_runs_as_what_and_where_a_resource_is_on_the_platform():
    manifest = ontologies.manifest_for("policy")
    assert manifest["extends"] == ["data", "agent"] and manifest["release"] >= 4
    assert ontologies.self_check("policy") == [], ontologies.self_check("policy")
    own = _own(POLICY)
    runs_as, derives = own["properties"]["runs_as"], own["properties"]["derives_from"]
    assert set(runs_as["domain"].split("|")) == {"Component", "System"} and runs_as["range"] == "Principal" and runs_as["max"] == 1
    assert runs_as["inverse"] == "identity_of"
    assert derives["domain"] == "IamBinding" and derives["range"] == "PolicyRule" and derives["inverse"] == "derived_into"
    assert own["attributes"]["Permission"]["cloud_role"]["type"] == "string"
    for kind in ("Table", "DataStore", "Component", "Interface"):
        assert own["attributes"][kind]["resource_uri"]["type"] == "string", kind
    questions = ontologies.questions_for("policy")
    assert "PL8" in questions and "PRINCIPAL" in questions["PL8"]["params"] and "runs as" in questions["PL8"]["question"].lower()
    assert {"runs_as", "derives_from", "Permission.cloud_role", "Table.resource_uri"} <= set(questions["PL8"]["terms"])


# ---- the derivation ----

def test_bindings_follow_the_active_rules_through_the_roles_each_principal_holds():
    doc = _iam.compile(_ledger_graph(), classes=CLASSES)
    assert doc["bundle_version"] == 1 and doc["provider"] == "gcp"
    by_role = {(b["resource"]["id"], b["role"]): b for b in doc["bindings"]}
    assert set(by_role) == {("table.t", EDITOR), ("table.t", VIEWER)}
    assert by_role[("table.t", EDITOR)]["members"] == ["serviceAccount:svc@p.iam"]
    assert by_role[("table.t", EDITOR)]["rules"] == ["policyrule.writers-write"] and by_role[("table.t", EDITOR)]["principals"] == ["principal.svc"]
    assert by_role[("table.t", VIEWER)]["members"] == ["serviceAccount:svc@p.iam", "user:ann@example.com"], "a service account and a person, in GCP's member form"
    assert by_role[("table.t", VIEWER)]["resource"]["uri"] == "//bigquery.googleapis.com/projects/p/datasets/d/tables/t"
    assert doc["withheld"] == [] and doc["problems"] == []
    assert [m["member"] for m in doc["members"]] == ["user:ann@example.com", "serviceAccount:svc@p.iam"], "every principal with an identity, by id"
    assert doc["resources"] == ["table.t"]


def test_a_forbid_withholds_the_binding_a_permit_would_have_made():
    graph = _ledger_graph()
    graph["edges"].append({"from": "principal.svc", "rel": "holds_role", "to": "role.auditor"})
    doc = _iam.compile(graph, classes=CLASSES)
    roles = {(b["resource"]["id"], b["role"]): b["members"] for b in doc["bindings"]}
    assert roles == {("table.t", VIEWER): ["serviceAccount:svc@p.iam", "user:ann@example.com"]}, "the write binding is gone; the read one stays"
    assert len(doc["withheld"]) == 1
    held = doc["withheld"][0]
    assert held["principal"] == "principal.svc" and held["member"] == "serviceAccount:svc@p.iam" and held["resource"]["id"] == "table.t"
    assert held["action"] == "write" and held["role"] == EDITOR
    assert held["permitted_by"] == ["policyrule.writers-write"] and held["forbidden_by"] == ["policyrule.auditors-never-write"]


def test_what_cannot_bind_is_named_not_guessed():
    graph = _ledger_graph(**{
        "permission.write": _node("permission.write", "Permission", label="Write tables", action="write", resource_class="Table"),
        "table.t": _node("table.t", "Table", label="t"),
        "principal.ann": _node("principal.ann", "Principal", label="Ann", kind="person"),
    })
    doc = _iam.compile(graph, classes=CLASSES)
    assert doc["bindings"] == []
    problems = "\n".join(doc["problems"])
    assert "permission.write has no cloud_role" in problems and "policyrule.writers-write" in problems
    assert "table.t has no resource_uri" in problems
    assert "principal.ann has no identity" in problems
    assert doc["problems"] == sorted(set(doc["problems"]), key=doc["problems"].index), "each problem once"
    draft = _ledger_graph(**{"policyrule.writers-write": _node("policyrule.writers-write", "PolicyRule", label="Writers write", effect="permit", status="draft")})
    doc = _iam.compile(draft, classes=CLASSES)
    assert {b["role"] for b in doc["bindings"]} == {VIEWER}, "a draft rule binds nothing"
    with pytest.raises(_iam.IamError):
        _iam.compile(_ledger_graph(), classes=CLASSES, provider="aws")


def test_the_gcp_form_is_one_policy_per_resource_in_the_shape_set_iam_policy_takes():
    doc = _iam.compile(_ledger_graph(), classes=CLASSES)
    policies = _iam.gcp_policies(doc)
    assert policies == [{"resource": "//bigquery.googleapis.com/projects/p/datasets/d/tables/t",
                         "policy": {"bindings": [{"role": EDITOR, "members": ["serviceAccount:svc@p.iam"]},
                                                 {"role": VIEWER, "members": ["serviceAccount:svc@p.iam", "user:ann@example.com"]}]}}]


# ---- the controls ----

def test_the_binding_nodes_are_proposed_in_the_policy_vocabulary_and_quote_the_document():
    graph = _ledger_graph()
    graph["edges"].append({"from": "principal.svc", "rel": "holds_role", "to": "role.auditor"})
    doc = _iam.compile(graph, classes=CLASSES)
    _title, text = _iam.document(doc, "2026-10-27")
    assert "oto policy iam" in text and "never enforced" in text.lower() or "does not enforce" in text.lower()
    proposal = _iam.propose(doc, graph, "2026-10-27", classes=CLASSES)
    assert proposal["source_doc"] == _iam.DOC and proposal["as_of"] == "2026-10-27"
    assert [n["id"] for n in proposal["nodes"]] == ["iambinding.table-t"]
    binding = proposal["nodes"][0]
    assert binding["type"] == "IamBinding" and binding["label"] == "IAM bindings on t"
    a = binding["attributes"]
    assert a["provider"] == "gcp" and a["resource_uri"] == "//bigquery.googleapis.com/projects/p/datasets/d/tables/t" and a["generated_by"] == "oto policy iam"
    assert json.loads(a["bindings"]) == [{"role": VIEWER, "members": ["serviceAccount:svc@p.iam", "user:ann@example.com"]}]
    assert json.loads(a["withheld"]) == [{"member": "serviceAccount:svc@p.iam", "role": EDITOR, "forbidden_by": ["policyrule.auditors-never-write"]}]
    assert not any(k in a for k in ("external_id", "requirement_url", "config")), "nothing of a framework on the node: the calm adapter shapes the control"
    for e in binding["evidence"]:
        assert e["doc"] == _iam.DOC and _evidence.found(e["quote"], _evidence.normalise(text)), e["quote"]
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("iambinding.table-t", "binds", "table.t") in edges
    assert ("iambinding.table-t", "grants", "principal.svc") in edges and ("iambinding.table-t", "grants", "principal.ann") in edges
    assert ("iambinding.table-t", "derives_from", "policyrule.readers-read") in edges
    assert ("iambinding.table-t", "derives_from", "policyrule.auditors-never-write") in edges, "the forbid that withheld a binding shaped the node"
    assert ("iambinding.table-t", "derives_from", "policyrule.writers-write") in edges
    without = _iam.propose(doc, graph, "2026-10-27", classes=[c for c in CLASSES if c != "IamBinding"])
    assert without["nodes"] == [] and without["edges"] == [], "no IamBinding in the vocabulary: nothing to propose"


def test_the_sample_holds_the_invoice_platform_s_binding_node_as_the_generator_writes_it():
    config, sample = _sample()
    doc = _iam.compile(sample, classes=config["classes"])
    bindings = {(b["resource"]["id"], b["role"]): b for b in doc["bindings"]}
    assert bindings[("table.invoices", EDITOR)]["members"] == [INTAKE] and bindings[("table.invoices", EDITOR)]["rules"] == ["policyrule.intake-writes-invoices"]
    assert bindings[("table.invoices", VIEWER)]["members"] == [RUNNER], "compliance reads every table without personal data, the runner's account holds the role"
    assert bindings[("table.ledger-daily-balances", VIEWER)]["members"] == [RUNNER, CLERK]
    assert sorted(bindings[("table.ledger-daily-balances", VIEWER)]["rules"]) == ["policyrule.compliance-reads-ledger", "policyrule.reports-export-balances"]
    assert bindings[("table.ledger-postings", VIEWER)]["members"] == [RUNNER]
    assert doc["resources"] == ["table.invoices", "table.ledger-daily-balances", "table.ledger-postings"]
    assert doc["problems"] == ["table.ledger-accounts has no resource_uri: no binding on it (policyrule.compliance-reads-ledger)",
                               "table.ledger-customers has no resource_uri: no binding on it (policyrule.compliance-reads-ledger)"], \
        "the accounts table is admitted by the selector and has no place on the platform: said, not invented; the customers table is admitted " \
        "here only because the sample is read raw: a build derives its pii from the email column and keeps it out (the build test holds that)"
    assert "table.ledger-customers" not in {b["resource"]["id"] for b in doc["bindings"]}
    proposal = _iam.propose(doc, sample, "2026-10-27", classes=config["classes"])
    generated = {n["id"]: n for n in proposal["nodes"]}
    shipped = {n["id"]: n for n in sample["nodes"] if n["type"] == "IamBinding"}
    assert set(shipped) == {"iambinding.table-invoices"} and set(generated) == {"iambinding.table-invoices", "iambinding.table-ledger-daily-balances",
                                                                                 "iambinding.table-ledger-postings"}
    assert shipped["iambinding.table-invoices"]["attributes"]["bindings"] == generated["iambinding.table-invoices"]["attributes"]["bindings"]
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert ("iambinding.table-invoices", "binds", "table.invoices") in edges and ("iambinding.table-invoices", "grants", "principal.invoice-intake") in edges
    assert ("iambinding.table-invoices", "derives_from", "policyrule.intake-writes-invoices") in edges
    assert ("component.invoice-intake", "runs_as", "principal.invoice-intake") in edges


# ---- the bundle ----

def test_the_bundle_is_hashed_signed_and_verifiable_like_the_policy_bundle(tmp_path, monkeypatch):
    out = str(tmp_path / "iam")
    monkeypatch.setenv(KEY_ENV, "a-key-nobody-commits")
    manifest = _iam.bundle(_ledger_graph(), out, version={"build_seq": 3, "graph": "abc", "ontology": 1}, at="2026-10-27", key_env=KEY_ENV, classes=CLASSES)
    assert sorted(os.listdir(out)) == ["bindings.json", "bindings.proposal.json", "gcp.json", "iam-bindings.md", "manifest.json"]
    assert manifest["bundle_version"] == 1 and manifest["provider"] == "gcp" and manifest["content"] == "bindings.json"
    assert manifest["bindings"] == 2 and manifest["resources"] == 1 and manifest["members"] == 2 and manifest["proposed"] == 1 and manifest["withheld"] == 0
    assert manifest["generated_at"] == "2026-10-27" and manifest["version"]["build_seq"] == 3
    assert set(manifest["files"]) == {"bindings.json", "bindings.proposal.json", "gcp.json", "iam-bindings.md"}
    with open(os.path.join(out, "bindings.json"), encoding="utf-8") as f:
        bindings = json.load(f)
    assert bindings["provider"] == "gcp" and len(bindings["bindings"]) == 2 and bindings["generated_at"] == "2026-10-27"
    assert manifest["hash"] == _policy.content_hash(bindings)
    assert manifest["signature"]["key"] == KEY_ENV and "a-key-nobody-commits" not in json.dumps(manifest)
    assert manifest["signature"]["value"] == hmac.new(b"a-key-nobody-commits", manifest["hash"].encode(), hashlib.sha256).hexdigest()
    with open(os.path.join(out, "gcp.json"), encoding="utf-8") as f:
        assert json.load(f)[0]["policy"]["bindings"][0]["role"] == EDITOR
    with open(os.path.join(out, "bindings.proposal.json"), encoding="utf-8") as f:
        assert json.load(f)["nodes"][0]["id"] == "iambinding.table-t"
    assert _policy.verify(out, key_env=KEY_ENV) == []
    assert _iam.describe(manifest).startswith("2 binding(s) on 1 resource(s) for 2 member(s), 1 binding node(s) proposed")
    monkeypatch.setenv(KEY_ENV, "another")
    assert any("does not verify" in p for p in _policy.verify(out, key_env=KEY_ENV))
    monkeypatch.setenv(KEY_ENV, "a-key-nobody-commits")
    with open(os.path.join(out, "gcp.json"), "a", encoding="utf-8") as f:
        f.write("\n")
    assert any("gcp.json" in p for p in _policy.verify(out, key_env=KEY_ENV))
    with pytest.raises(_policy.PolicyError):
        monkeypatch.delenv(KEY_ENV)
        _iam.bundle(_ledger_graph(), str(tmp_path / "unsigned"), key_env=KEY_ENV, classes=CLASSES)


# ---- the build, the command, the controls applied ----

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="The ledger, governed", ontology="policy")
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("OTO_POLICY_SNAPSHOT", raising=False)
    return root


def test_the_build_writes_the_bindings_beside_the_policy_bundle(ledger):
    code, out = _cli("build", "--project", ledger)
    assert code == 0, out
    assert "policy: 4 rule(s)" in out
    assert "iam: 4 binding(s) on 3 resource(s) for 3 member(s)" in out and "3 binding node(s) proposed" in out and "unsigned" in out, out
    assert "not bound: table.ledger-accounts has no resource_uri" in out, out
    project = Project.standard(ledger)
    assert sorted(os.listdir(project.layout.iam)) == ["bindings.json", "bindings.proposal.json", "gcp.json", "iam-bindings.md", "manifest.json"]
    with open(os.path.join(project.layout.iam, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["version"]["build_seq"] == int(project.build_seq()) and manifest["problems"] == [
        "table.ledger-accounts has no resource_uri: no binding on it (policyrule.compliance-reads-ledger)"], "the derived pii keeps the customers table out"
    code, out = _cli("policy", "verify", project.layout.iam, "--project", ledger)
    assert code == 0 and "holds" in out and "4 binding(s)" in out, out
    with open(os.path.join(project.layout.iam, "gcp.json"), encoding="utf-8") as f:
        gcp = json.load(f)
    assert [p["resource"] for p in gcp] == sorted(p["resource"] for p in gcp) and all(p["resource"].startswith("//bigquery.googleapis.com/") for p in gcp)


def test_the_command_writes_the_bundle_anywhere_and_applies_the_controls_through_the_gates(ledger):
    code, out = _cli("build", "--project", ledger)
    assert code == 0, out
    elsewhere = os.path.join(ledger, "elsewhere")
    code, out = _cli("policy", "iam", "--project", ledger, "--out", elsewhere, "--at", "2026-10-27")
    assert code == 0 and "4 binding(s) on 3 resource(s)" in out and "bindings.proposal.json" in out and "oto curate add --from" in out, out
    assert os.path.exists(os.path.join(elsewhere, "bindings.json")) and os.path.exists(os.path.join(ledger, "build", "documents", _iam.DOC + ".md"))
    project = Project.standard(ledger)
    before = {n["id"] for n in _session.live(project)["nodes"] if n["type"] == "IamBinding"}
    assert "iambinding.table-ledger-postings" not in before
    code, out = _cli("policy", "iam", "--project", ledger, "--apply", "--by", "Chiheb Dkhil", "--at", "2026-10-27")
    assert code == 0 and "applied" in out, out
    live = _session.live(project)
    bindings = {n["id"]: n for n in live["nodes"] if n["type"] == "IamBinding"}
    assert set(bindings) == {"iambinding.table-invoices", "iambinding.table-ledger-daily-balances", "iambinding.table-ledger-postings"}
    edges = {(e["from"], e["rel"], e["to"]) for e in live["edges"] if (e.get("status") or "current") == "current"}
    assert ("iambinding.table-ledger-postings", "binds", "table.ledger-postings") in edges
    assert ("iambinding.table-ledger-postings", "derives_from", "policyrule.compliance-reads-ledger") in edges
    code, out = _cli("query", "--project", ledger, "ask", "PL9", "RESOURCE=table.ledger-postings")
    assert code == 0 and "status: answered" in out and "iambinding.table-ledger-postings" in out and "oto policy iam" in out and VIEWER in out, out
    code, out = _cli("query", "--project", ledger, "ask", "PL8", "PRINCIPAL=principal.invoice-intake")
    assert code == 0 and "status: answered" in out and "component.invoice-intake" in out and "iambinding.table-invoices" in out and EDITOR in out, out
    code, out = _cli("query", "--project", ledger, "ask", "PL8", "PRINCIPAL=principal.ops-clerk")
    assert code == 0 and "nothing runs as" in out, "a person's account: " + out
    code, out = _cli("policy", "iam", "--project", ledger, "--apply", "--at", "2026-10-27")
    assert code == 1 and "--by" in out, "applying is a person's or a workflow's act, named"


def test_the_command_refuses_a_provider_it_does_not_know(ledger):
    path = os.path.join(ledger, "project.config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["policy"] = {"provider": "aws"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    code, out = _cli("policy", "iam", "--project", ledger, "--at", "2026-10-27")
    assert code == 1 and "aws" in out and "gcp" in out, out
    code, out = _cli("build", "--project", ledger)
    assert code == 1 and "aws" in out, out


def test_a_project_without_the_pack_writes_no_bindings(tmp_path):
    root = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plain", name="Plain", ontology="data")
    code, out = _cli("build", "--project", root)
    assert code == 0 and "iam:" not in out and "policy:" not in out, "a project without the pack never runs its stages: " + out
    assert not os.path.isdir(Project.standard(root).layout.iam)


# ---- the decision and the docs ----

def test_adr_0005_makes_the_generated_system_s_iam_an_output_never_an_enforcement():
    with open(os.path.join(ROOT, "docs", "adr", "0005-iam-is-generated-never-enforced.md"), encoding="utf-8") as f:
        text = f.read()
    record = _adr.parse(text)
    assert _adr.problems(record) == [], _adr.problems(record)
    front = record["front"]
    assert front["id"] == "ADR-0005" and front["status"] == "accepted" and front["governs"] == ["workitem.epic-e"]
    decision = _adr.first_sentence(record["sections"]["Decision"]).lower()
    assert "binding" in decision and ("derived" in decision or "generated" in decision)
    body = text.lower()
    assert "cloud_role" in body and "resource_uri" in body and "control" in body and "never enforce" in body or "does not enforce" in body


def test_the_docs_know_the_bindings_the_stage_and_the_command():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto policy iam" in text and "ADR-0005" in text and "build/iam" in text and "runs_as" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 32." in e2e and "oto policy iam" in e2e and "gcp.json" in e2e
    with open(os.path.join(ROOT, "skills", "concierge", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    assert "oto policy iam" in skill
    with open(os.path.join(POLICY, "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "oto policy iam" in readme and "ADR-0005" in readme and "runs_as" in readme and "cloud_role" in readme
    with open(os.path.join(ARCHITECTURE, "README.md"), encoding="utf-8") as f:
        arch = f.read()
    assert "generated_by" not in arch and "resource_uri" not in arch, "the architecture pack carries nothing for the policy pack's sake"
