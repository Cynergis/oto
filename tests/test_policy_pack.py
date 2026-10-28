"""The policy pack (roadmap E1) and `oto policy compile` (E2). A `PolicyRule` permits or forbids a
`Permission` (an action on a kind of resource, narrowed by a selector) for a role or a team, a table
or a column carries a classification and whether it holds personal data, and the active rules
compile into a Cedar bundle and a JSON form, versioned, hashed and signed, written by the build so
the deploy pipeline carries them. ADR-0004 records the choice of Cedar.
"""
import contextlib
import hashlib
import hmac
import io
import json
import os

import pytest

from oto import adr as _adr, policy as _policy
from oto.cli import main
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "oto", "ontologies", "policy")
KEY_ENV = "OTO_POLICY_KEY"


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _own():
    with open(os.path.join(PACK, "ontology.config.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- the vocabulary (E1) ----

def test_the_pack_sits_on_data_and_passes_its_own_check():
    manifest = ontologies.manifest_for("policy")
    assert manifest["extends"] == ["data", "agent", "architecture"] and manifest["release"] == 3 and manifest["domain"] == "security"
    assert ontologies.self_check("policy") == [], ontologies.self_check("policy")
    config, _sample, readme = ontologies.load("policy")
    assert {"PolicyRule", "Permission"} <= set(config["classes"])
    assert {"Role", "Team", "Table", "Column", "Policy", "DataStore", "Component"} <= set(config["classes"]), "composed on data and the estate"
    assert config["classes"]["PolicyRule"]["subclass_of"] == ["Policy"], "a policy rule is a kind of the estate's Policy"
    assert "cedar" in readme.lower() and "ADR-0004" in readme


def test_a_rule_names_its_roles_and_one_permission_and_may_single_out_resources():
    own = _own()
    for_role, of_permission, singles_out = own["properties"]["for_role"], own["properties"]["of_permission"], own["properties"]["singles_out"]
    assert for_role["domain"] == "PolicyRule" and set(for_role["range"].split("|")) == {"Role", "Team"} and for_role["min"] == 1
    assert of_permission["domain"] == "PolicyRule" and of_permission["range"] == "Permission" and of_permission["min"] == 1 and of_permission["max"] == 1
    assert singles_out["domain"] == "PolicyRule" and {"Table", "Column", "DataStore", "Component", "Interface"} <= set(singles_out["range"].split("|"))
    assert not singles_out.get("min"), "singling out resources is optional: a rule without it covers every resource its selector admits"
    attrs = own["attributes"]
    assert attrs["PolicyRule"]["effect"]["type"] == "enum:permit|forbid" and attrs["PolicyRule"]["effect"]["required"] is True
    assert attrs["PolicyRule"]["status"] == dict(attrs["PolicyRule"]["status"], type="enum:draft|active|retired", default="draft", decision=True), \
        "a rule is a draft until a named person activates it; only active rules compile"
    assert attrs["PolicyRule"]["priority"]["type"] == "integer"
    assert attrs["Permission"]["action"]["type"] == "enum:read|write|export|delete|admin" and attrs["Permission"]["action"]["required"] is True
    assert attrs["Permission"]["resource_class"]["required"] is True and attrs["Permission"]["selector"]["type"] == "list"


def test_a_table_and_a_column_carry_a_classification_and_whether_they_hold_personal_data():
    own = _own()
    for kind in ("Table", "Column"):
        assert own["attributes"][kind]["classification"]["type"] == "enum:public|internal|confidential|restricted"
        assert own["attributes"][kind]["pii"]["type"] == "boolean"
    config, _s, _r = ontologies.load("policy")
    assert config["attributes"]["Column"]["type"]["required"] is True, "the data pack's own attributes stay beside the markers"
    rules = {r["id"]: r for r in ontologies.load_raw("policy")["rules"]}
    assert rules["table-holds-personal-data-when-a-column-does"]["kind"] == "derive" and rules["table-holds-personal-data-when-a-column-does"]["then"] == {"attribute": ["t", "pii", True]}
    assert rules["personal-data-in-a-public-table"]["kind"] == "policy" and rules["personal-data-in-a-public-table"]["severity"] == "warn"


def test_the_questions_say_what_the_pack_is_for():
    questions = ontologies.questions_for("policy")
    ids = [q for q in questions if q.startswith("PL")]
    assert ids == ["PL1", "PL2", "PL3", "PL4", "PL5", "PL6", "PL7", "PL8"], ids
    assert "ROLE" in questions["PL1"]["params"] and questions["PL1"]["gate"] == "any", "PL1: what a role may do; a role no rule names may do nothing, an answer too"
    assert questions["PL2"]["gate"] == "any" and "personal" in questions["PL2"]["question"].lower(), "PL2: where the personal and restricted data is"
    assert questions["PL3"]["gate"] == "any" and "draft" in questions["PL3"]["question"].lower(), "PL3: what is not active"
    assert "RULE" in questions["PL4"]["params"], "PL4: one rule, in full"
    assert "TABLE" in questions["PL5"]["params"], "PL5: who may do what on a table"


def test_the_sample_has_active_draft_and_forbidding_rules_on_the_ledger():
    _config, sample, _readme = ontologies.load("policy")
    rules = [n for n in sample["nodes"] if n["type"] == "PolicyRule"]
    status = {n["id"]: n["attributes"].get("status", "draft") for n in rules}
    assert sum(1 for s in status.values() if s == "active") >= 3 and "draft" in status.values()
    assert any(n["attributes"]["effect"] == "forbid" for n in rules)
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert all(any(f == n["id"] and rel == "for_role" for f, rel, _t in edges) for n in rules), "every rule names a role or a team"
    assert any(rel == "singles_out" and to.startswith("table.") for _f, rel, to in edges)
    columns = [n for n in sample["nodes"] if n["type"] == "Column" and n["attributes"].get("pii") is True]
    assert columns and any(n["type"] == "Table" and n["attributes"].get("classification") == "restricted" for n in sample["nodes"])


# ---- the compile (E2) ----

def _sample():
    _config, sample, _readme = ontologies.load("policy")
    return sample


def test_only_active_rules_compile_most_urgent_first():
    doc = _policy.compile(_sample())
    assert doc["bundle_version"] == _policy.BUNDLE_VERSION and doc["problems"] == []
    ids = [r["id"] for r in doc["rules"]]
    assert "policyrule.owner-admin" not in ids, "a draft does not compile"
    assert ids == [r["id"] for r in sorted(doc["rules"], key=lambda r: (-r["priority"], r["id"]))]
    forbid = next(r for r in doc["rules"] if r["effect"] == "forbid")
    assert forbid["roles"] == [{"id": "team.reports", "type": "Team", "label": forbid["roles"][0]["label"]}]
    assert forbid["permission"]["action"] == "write" and forbid["permission"]["resource_class"] == "Table"
    assert forbid["resources"] == [{"id": "table.ledger-postings", "type": "Table", "label": "ledger.postings"}]
    reads = next(r for r in doc["rules"] if r["id"] == "policyrule.compliance-reads-ledger")
    assert reads["permission"]["selector"] == [{"key": "pii", "op": "==", "value": False}] and reads["resources"] == []
    assert reads["roles"][0]["id"] == "role.r-compliance" and reads["rationale"]


def test_the_cedar_text_says_the_same_as_the_json():
    doc = _policy.compile(_sample())
    cedar = _policy.cedar(doc)
    assert '@id("policyrule.compliance-reads-ledger")' in cedar
    assert 'permit (\n  principal in Role::"role.r-compliance",\n  action == Action::"read",\n  resource is Table\n) when { resource.pii == false };' in cedar
    assert 'forbid (\n  principal in Team::"team.reports",\n  action == Action::"write",\n  resource in [Table::"table.ledger-postings"]\n);' in cedar
    assert cedar.count("@id(") == len(doc["rules"]) and cedar.startswith("// ")
    assert "policyrule.owner-admin" not in cedar


def test_what_cannot_compile_is_named_not_guessed():
    sample = _sample()
    nodes = [dict(n) for n in sample["nodes"]]
    for n in nodes:
        if n["id"] == "permission.read-ledger-tables":
            n["attributes"] = dict(n["attributes"], resource_class="Spreadsheet", selector=["pii"])
    doc = _policy.compile({"nodes": nodes, "edges": sample["edges"]})
    assert any("Spreadsheet" in p for p in doc["problems"]) and any("selector" in p and "pii" in p for p in doc["problems"])
    assert "policyrule.compliance-reads-ledger" not in [r["id"] for r in doc["rules"]], "a rule that cannot compile is left out and named"
    assert _policy.compile({"nodes": [], "edges": []}) == {"bundle_version": _policy.BUNDLE_VERSION, "rules": [], "problems": [],
                                                           "roles": [], "permissions": []}


def test_the_bundle_is_hashed_signed_and_verifiable(tmp_path, monkeypatch):
    out = str(tmp_path / "policy")
    monkeypatch.delenv(KEY_ENV, raising=False)
    manifest = _policy.bundle(_sample(), out, version={"build_seq": 7, "graph": "abc123", "ontology": 1}, at="2026-10-27")
    assert sorted(os.listdir(out)) == ["manifest.json", "policies.cedar", "policies.json"]
    assert manifest["bundle_version"] == _policy.BUNDLE_VERSION and manifest["version"] == {"build_seq": 7, "graph": "abc123", "ontology": 1}
    assert manifest["generated_at"] == "2026-10-27" and manifest["rules"] == 4 and manifest["signature"] is None
    with open(os.path.join(out, "policies.json"), "rb") as f:
        body = f.read()
    assert manifest["files"]["policies.json"] == hashlib.sha256(body).hexdigest() and manifest["hash"] == _policy.content_hash(json.loads(body))
    assert _policy.verify(out) == []
    with open(os.path.join(out, "policies.json"), "w", encoding="utf-8") as f:
        json.dump({"rules": []}, f)
    assert any("policies.json" in p for p in _policy.verify(out)), "an edited file is not the one the manifest names"
    monkeypatch.setenv(KEY_ENV, "s3cret")
    manifest = _policy.bundle(_sample(), out, version={"build_seq": 8}, at="2026-10-27", key_env=KEY_ENV)
    assert manifest["signature"] == {"algorithm": "HMAC-SHA256", "key": KEY_ENV,
                                     "value": hmac.new(b"s3cret", manifest["hash"].encode("utf-8"), hashlib.sha256).hexdigest()}
    assert _policy.verify(out, key_env=KEY_ENV) == []
    monkeypatch.setenv(KEY_ENV, "wrong")
    assert any("signature" in p for p in _policy.verify(out, key_env=KEY_ENV))
    assert _policy.verify(out) == [], "without a key the hash still verifies; the signature is reported, not checked"
    monkeypatch.delenv(KEY_ENV)
    with pytest.raises(_policy.PolicyError):
        _policy.bundle(_sample(), out, version={}, at="2026-10-27", key_env=KEY_ENV)


# ---- installed: the build writes the bundle, the command reads it ----

@pytest.fixture
def ledger(tmp_path):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="The ledger, governed", ontology="policy")
    return root


def test_the_build_writes_the_bundle_and_the_command_compiles_lists_and_verifies_it(ledger, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    code, out = _cli("build", "--project", ledger)
    assert code == 0 and "policy: 4 rule(s)" in out and "unsigned" in out, out
    project = Project.standard(ledger)
    bundle = project.layout.policy
    assert sorted(os.listdir(bundle)) == ["manifest.json", "policies.cedar", "policies.json"]
    with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["version"]["build_seq"] == int(project.build_seq()) and manifest["version"]["ontology"] >= 1 and manifest["version"]["graph"]
    code, out = _cli("policy", "verify", "--project", ledger)
    assert code == 0 and "holds" in out, out
    code, out = _cli("policy", "list", "--project", ledger)
    assert code == 0 and "policyrule.compliance-reads-ledger" in out and "forbid" in out and "draft" in out and "owner-admin" in out, out
    code, out = _cli("query", "--project", ledger, "ask", "PL2")
    assert code == 0 and "ledger.customers" in out and "t.pii=True" in out, "the table holds personal data because a column does (derived)\n" + out
    code, out = _cli("query", "--project", ledger, "ask", "PL1", "ROLE=role.r-compliance")
    assert code == 0 and "status: answered" in out and "read" in out, out
    other = str(os.path.join(ledger, "elsewhere"))
    code, out = _cli("policy", "compile", "--project", ledger, "--out", other, "--at", "2026-10-27")
    assert code == 0 and os.path.exists(os.path.join(other, "policies.cedar")) and "4 rule(s)" in out, out
    code, out = _cli("policy", "verify", other, "--project", ledger)
    assert code == 0, out
    with open(os.path.join(other, "policies.cedar"), "a", encoding="utf-8") as f:
        f.write("\n// edited by hand\n")
    code, out = _cli("policy", "verify", other, "--project", ledger)
    assert code == 1 and "policies.cedar" in out, out


def test_activating_a_draft_rule_is_a_decision_that_changes_the_next_bundle(ledger, monkeypatch):
    monkeypatch.setenv(KEY_ENV, "k")
    with open(os.path.join(ledger, "project.config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["policy"] = {"sign_with": KEY_ENV}
    with open(os.path.join(ledger, "project.config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    code, out = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, out
    code, out = _cli("build", "--project", ledger)
    assert code == 0 and "policy: 5 rule(s)" in out and "signed with %s" % KEY_ENV in out, out
    with open(os.path.join(Project.standard(ledger).layout.policy, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["rules"] == 5 and manifest["signature"]["key"] == KEY_ENV
    code, out = _cli("policy", "verify", "--project", ledger)
    assert code == 0 and "signed" in out, out
    monkeypatch.setenv(KEY_ENV, "another")
    code, out = _cli("policy", "verify", "--project", ledger)
    assert code == 1 and "signature" in out, out
    monkeypatch.delenv(KEY_ENV)
    code, out = _cli("build", "--project", ledger)
    assert code == 1 and KEY_ENV in out, "a project that says it signs cannot build without the key\n" + out


def test_a_project_without_the_pack_writes_no_bundle(tmp_path):
    root = str(tmp_path / "estate")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="acme", name="Acme", ontology="software-architecture")
    code, out = _cli("build", "--project", root)
    assert code == 0 and "policy:" not in out, "a project without the pack never runs its stage (ADR-0006): " + out
    assert not os.path.exists(Project.standard(root).layout.policy)
    code, out = _cli("policy", "compile", "--project", root)
    assert code == 1 and "PolicyRule" in out


# ---- the decision ----

def test_adr_0004_chooses_cedar_and_keeps_the_hooks_plain():
    with open(os.path.join(ROOT, "docs", "adr", "0004-cedar-for-policy.md"), encoding="utf-8") as f:
        text = f.read()
    record = _adr.parse(text)
    assert _adr.problems(record) == [], _adr.problems(record)
    front = record["front"]
    assert front["id"] == "ADR-0004" and front["status"] == "accepted" and front["governs"] == ["workitem.epic-e"]
    assert "cedar" in _adr.first_sentence(record["sections"]["Decision"]).lower()
    body = text.lower()
    assert "plain python" in body and "stdlib" in body, "the hooks evaluate the JSON form in plain Python; no Cedar engine on the runner's machine"


def test_the_docs_know_the_pack_and_the_command():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto policy compile" in text and "ontologies/policy" in text and "ADR-0004" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 28." in e2e and "oto policy compile" in e2e and "oto policy verify" in e2e
    with open(os.path.join(ROOT, "skills", "concierge", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    assert "oto policy compile" in skill
