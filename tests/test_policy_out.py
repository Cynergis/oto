"""Policy and IAM out (ADR-0006, step 4). The policy pack stands on data and agent, depends on no
framework, and its generated bindings are a class of its own, `IamBinding`, that binds one resource,
grants the principals and derives from the rules. The compiler, the snapshot, the IAM derivation,
the two stages, the command, the write hook and the served read hook live in oto/packs/policy and
reach the engine only through the pack's manifest; the engine imports none of them. A framework adapter
that knows binding nodes (the registry's calm pack) exports them as controls; the engine provides none."""
import contextlib
import io
import json
import os

from oto import extensions
from oto.cli import main
from oto.curate import session as _session
from oto.model import ontologies
from oto.packs import policy as _policy
from oto.packs.policy import iam as _iam
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/policy.py", "oto/iam.py", "oto/targets/policy.py", "oto/targets/iam.py", "oto/cli/policy.py")
ENGINE = ("oto/serve/engine.py", "oto/builder.py", "oto/cli/__init__.py", "oto/publish.py", "oto/assertion.py", "oto/cli/curate.py", "oto/deploy.py", "oto/extensions.py")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _project(tmp_path, ontology, slug):
    root = str(tmp_path / slug)
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=slug, name=slug.title(), ontology=ontology)
    return root


def test_the_pack_stands_on_data_and_agent_with_a_binding_class_of_its_own():
    manifest = ontologies.manifest_for("policy")
    assert manifest["extends"] == ["data", "agent"] and manifest["release"] == 4
    assert ontologies.self_check("policy") == [], ontologies.self_check("policy")
    own = ontologies.load_raw("policy")["config"]
    assert set(own["classes"]) == {"PolicyRule", "Permission", "Principal", "IamBinding"}
    assert "safeguards" not in own["properties"], "the architecture's relation is no longer widened: the pack stands on its own"
    binds, grants, derives = own["properties"]["binds"], own["properties"]["grants"], own["properties"]["derives_from"]
    assert binds["domain"] == "IamBinding" and set(binds["range"].split("|")) == {"Table", "DataStore", "Component", "Interface"} and binds["max"] == 1
    assert grants["domain"] == "IamBinding" and grants["range"] == "Principal"
    assert derives["domain"] == "IamBinding" and derives["range"] == "PolicyRule"
    attrs = own["attributes"]["IamBinding"]
    assert {"provider", "resource_uri", "bindings", "withheld", "generated_by"} <= set(attrs) and attrs["generated_by"]["required"] is True
    for kind in ("Table", "DataStore", "Component", "Interface"):
        assert own["attributes"][kind]["resource_uri"]["type"] == "string", kind
    config, _sample, _readme = ontologies.load("policy")
    assert "Control" not in config["classes"] and "Relationship" not in config["classes"], "nothing of the architecture pack composes in"
    questions = ontologies.questions_for("policy")
    assert "PL9" in questions and "RESOURCE" in questions["PL9"]["params"] and "IamBinding" in questions["PL9"]["terms"]
    assert "grants" in questions["PL8"]["terms"]
    architecture = ontologies.load_raw("architecture")["config"]
    assert not any("resource_uri" in v for v in architecture["attributes"].values()) and "generated_by" not in architecture["attributes"]["Control"]
    assert "AR12" not in ontologies.questions_for("architecture") and ontologies.manifest_for("architecture")["release"] == 6


def test_the_code_lives_behind_the_pack_and_the_engine_imports_none_of_it():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    for name in ("__init__.py", "iam.py", "bundle_stage.py", "iam_stage.py", "cli.py"):
        assert os.path.exists(os.path.join(ROOT, "oto", "packs", "policy", name)), name
    for path in ENGINE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(("#", '"')) and "\"" not in l[:8])
        assert "packs.policy" not in code and "import policy" not in code and "policy as _policy" not in code, path
    provides = ontologies.manifest_for("policy")["provides"]
    assert provides["read_hooks"] == ["oto.packs.policy:police_read"] and provides["write_hooks"] == ["oto.packs.policy:enforce"]
    assert {s["module"] for s in provides["stages"]} == {"oto.packs.policy.bundle_stage", "oto.packs.policy.iam_stage"}
    assert provides["commands"][0]["module"] == "oto.packs.policy.cli"
    assert _policy.police_read and _policy.enforce and _iam.BINDING == "IamBinding"


def test_the_read_hook_is_the_pack_s_and_a_project_without_it_has_none(tmp_path):
    ledger = _project(tmp_path, "policy", "ledger")
    hooks = extensions.read_hooks(Project.standard(ledger))
    assert [h.__name__ for h in hooks] == ["police_read"]
    plain = _project(tmp_path, "data", "plain")
    assert extensions.read_hooks(Project.standard(plain)) == []


def test_the_bindings_are_proposed_as_binding_nodes_that_bind_grant_and_derive():
    config, sample, _readme = ontologies.load("policy")
    doc = _iam.compile(sample, classes=config["classes"])
    proposal = _iam.propose(doc, sample, "2026-10-27", classes=config["classes"])
    nodes = {n["id"]: n for n in proposal["nodes"]}
    assert set(nodes) == {"iambinding.table-invoices", "iambinding.table-ledger-daily-balances", "iambinding.table-ledger-postings"}
    invoices = nodes["iambinding.table-invoices"]
    assert invoices["type"] == "IamBinding" and invoices["attributes"]["provider"] == "gcp" and invoices["attributes"]["generated_by"] == "oto policy iam"
    assert invoices["attributes"]["resource_uri"].startswith("//bigquery.googleapis.com/")
    assert json.loads(invoices["attributes"]["bindings"]) == [{"role": "roles/bigquery.dataEditor", "members": ["serviceAccount:invoice-intake@acme.iam"]},
                                                              {"role": "roles/bigquery.dataViewer", "members": ["serviceAccount:factory-runner@acme.iam"]}]
    assert json.loads(invoices["attributes"]["withheld"]) == []
    assert not any(a in invoices["attributes"] for a in ("external_id", "requirement_url", "config", "calm_id")), "nothing of a framework on the node"
    edges = {(e["from"], e["rel"], e["to"]) for e in proposal["edges"]}
    assert ("iambinding.table-invoices", "binds", "table.invoices") in edges
    assert ("iambinding.table-invoices", "grants", "principal.invoice-intake") in edges and ("iambinding.table-invoices", "grants", "principal.factory-runner") in edges
    assert ("iambinding.table-invoices", "derives_from", "policyrule.intake-writes-invoices") in edges
    assert not any(rel == "safeguards" for _f, rel, _t in edges)
    shipped = next(n for n in sample["nodes"] if n["id"] == "iambinding.table-invoices")
    assert shipped["attributes"]["bindings"] == invoices["attributes"]["bindings"], "the sample holds the node as the generator writes it"
    without = _iam.propose(doc, sample, "2026-10-27", classes=[c for c in config["classes"] if c != "IamBinding"])
    assert without["nodes"] == []


def test_a_policy_project_binds_and_publishes_the_bundle_summary_with_no_framework_to_export_to(tmp_path):
    ledger = _project(tmp_path, "policy", "ledger")
    code, out = _cli("build", "--project", ledger)
    assert code == 0 and "iam: 4 binding(s) on 3 resource(s)" in out and "3 binding node(s) proposed" in out, out
    project = Project.standard(ledger)
    assert os.path.exists(os.path.join(project.layout.iam, "bindings.proposal.json"))
    with open(os.path.join(project.layout.iam, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["proposed"] == 3 and "controls" not in manifest
    code, out = _cli("arch", "export", "--framework", "calm", "--project", ledger)
    assert code == 1 and "no adapter" in out and "calm" in out, "the engine ships no framework adapter (ADR-0008): " + out


def test_the_docs_know_where_the_code_is_and_what_a_binding_node_is():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "packs/policy" in text and "IamBinding" in text and "oto/policy.py" not in text and "AR1 to AR11" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "bindings.proposal.json" in e2e and "controls.proposal.json" not in e2e and "PL9" in e2e
    with open(os.path.join(ROOT, "oto", "ontologies", "policy", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "IamBinding" in readme and "oto/packs/policy" in readme and "depends on no framework" in readme
