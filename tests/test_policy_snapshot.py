"""The signed policy snapshot and the guards that read it (roadmap E3). The policy pack gains a
`Principal` (an identity that holds a session) and the roles an `Agent` is granted; `oto policy
snapshot --agent --principal` writes the intersection of what the two may do, with the paths it
reaches through the code map, hashed and signed, to `.factory/policy.json`; the engine plugin's
PreToolUse guard and the factory guard read it in plain Python and refuse what it does not permit;
every refusal is an event, and `oto policy denials` (and `oto factory run sync`) turn the events
into audit records."""
import contextlib
import hashlib
import hmac
import io
import json
import os
import subprocess
import sys

import pytest

from oto import audit as _audit, policy as _policy
from oto.cli import main
from oto.model import ontologies
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "oto", "ontologies", "policy")
ENGINE_GUARD = os.path.join(ROOT, "hooks", "policy_guard.py")
FACTORY_GUARD = os.path.join(ROOT, "factory", "hooks", "guard.py")
KEY_ENV = "OTO_POLICY_KEY"


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _hook(script, payload, cwd, env=None):
    done = subprocess.run([sys.executable, "-I", script], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))
    return done.returncode, done.stdout, done.stderr


# ---- the pack, release 2 ----

def test_the_pack_now_knows_principals_and_the_roles_an_agent_is_granted():
    manifest = ontologies.manifest_for("policy")
    assert manifest["extends"] == ["data", "agent", "architecture"] and manifest["release"] == 3
    assert ontologies.self_check("policy") == [], ontologies.self_check("policy")
    config, sample, _readme = ontologies.load("policy")
    assert {"Principal", "Agent", "PolicyRule"} <= set(config["classes"]), "the agent pack's Agent, not a second one"
    with open(os.path.join(PACK, "ontology.config.json"), encoding="utf-8") as f:
        own = json.load(f)
    holds, granted = own["properties"]["holds_role"], own["properties"]["granted_role"]
    assert holds["domain"] == "Principal" and set(holds["range"].split("|")) == {"Role", "Team"} and holds["min"] == 1
    assert granted["domain"] == "Agent" and set(granted["range"].split("|")) == {"Role", "Team"}
    assert own["attributes"]["Principal"]["kind"]["type"] == "enum:person|service" and own["attributes"]["Principal"]["kind"]["required"] is True
    assert own["attributes"]["Principal"]["identity"]["type"] == "string"
    questions = ontologies.questions_for("policy")
    assert "PRINCIPAL" in questions["PL6"]["params"] and "AGENT" in questions["PL7"]["params"]
    principals = [n for n in sample["nodes"] if n["type"] == "Principal"]
    assert {n["attributes"]["kind"] for n in principals} == {"person", "service"}
    edges = {(e["from"], e["rel"], e["to"]) for e in sample["edges"]}
    assert any(rel == "granted_role" and f == "agent.merchant-assistant" for f, rel, _t in edges), "the agent pack's own agent is granted roles here"
    assert all(any(f == n["id"] and rel == "holds_role" for f, rel, _t in edges) for n in principals)


# ---- the snapshot ----

def _node(id, type, label, **attributes):
    return {"id": id, "type": type, "label": label, "status": "current", "attributes": attributes}


def _graph():
    nodes = [
        _node("role.dev", "Role", "Developer"), _node("role.ops", "Role", "Operator"), _node("team.reports", "Team", "Reports"),
        _node("agent.runner", "Agent", "Factory runner", packaging="plugin"),
        _node("principal.ada", "Principal", "Ada", kind="person", identity="ada@acme.example"),
        _node("principal.bot", "Principal", "The reports bot", kind="service", identity="reports-bot"),
        _node("component.intake", "Component", "Invoice intake"), _node("component.scheduler", "Component", "Payment scheduler", tier="core"),
        _node("component.legacy", "Component", "Legacy", tier="legacy"),
        _node("codemodule.src-intake", "CodeModule", "src/intake", path="src/intake"), _node("codemodule.tests-intake", "CodeModule", "tests/intake", path="tests/intake"),
        _node("codemodule.src-scheduler", "CodeModule", "src/scheduler", path="src/scheduler"), _node("codemodule.src-legacy", "CodeModule", "src/legacy", path="src/legacy"),
        _node("table.orders", "Table", "orders", pii=False),
        _node("permission.write-components", "Permission", "Write components", action="write", resource_class="Component", selector=["tier!=legacy"]),
        _node("permission.write-legacy", "Permission", "Write the legacy code", action="write", resource_class="Component"),
        _node("permission.read-orders", "Permission", "Read orders", action="read", resource_class="Table", selector=["pii=false"]),
        _node("permission.export-orders", "Permission", "Export orders", action="export", resource_class="Table"),
        _node("policyrule.devs-write", "PolicyRule", "Developers write components", effect="permit", priority=10, status="active"),
        _node("policyrule.ops-write-intake", "PolicyRule", "Operators write the intake", effect="permit", priority=10, status="active"),
        _node("policyrule.nobody-writes-legacy", "PolicyRule", "Nobody writes the legacy code", effect="forbid", priority=100, status="active"),
        _node("policyrule.ops-read-orders", "PolicyRule", "Operators read orders", effect="permit", priority=5, status="active"),
        _node("policyrule.devs-read-orders", "PolicyRule", "Developers read orders", effect="permit", priority=5, status="active"),
        _node("policyrule.reports-export", "PolicyRule", "Reports export orders", effect="permit", priority=5, status="active"),
        _node("policyrule.devs-export-draft", "PolicyRule", "Developers export orders (draft)", effect="permit", priority=5),
    ]
    edges = [
        ("component.intake", "implemented_by", "codemodule.src-intake"), ("component.intake", "implemented_by", "codemodule.tests-intake"),
        ("component.scheduler", "implemented_by", "codemodule.src-scheduler"), ("component.legacy", "implemented_by", "codemodule.src-legacy"),
        ("agent.runner", "granted_role", "role.dev"), ("agent.runner", "granted_role", "team.reports"),
        ("principal.ada", "holds_role", "role.ops"), ("principal.ada", "holds_role", "role.dev"),
        ("principal.bot", "holds_role", "team.reports"),
        ("policyrule.devs-write", "for_role", "role.dev"), ("policyrule.devs-write", "of_permission", "permission.write-components"),
        ("policyrule.ops-write-intake", "for_role", "role.ops"), ("policyrule.ops-write-intake", "of_permission", "permission.write-components"),
        ("policyrule.ops-write-intake", "singles_out", "component.intake"),
        ("policyrule.nobody-writes-legacy", "for_role", "role.dev"), ("policyrule.nobody-writes-legacy", "for_role", "role.ops"),
        ("policyrule.nobody-writes-legacy", "of_permission", "permission.write-legacy"), ("policyrule.nobody-writes-legacy", "singles_out", "component.legacy"),
        ("policyrule.ops-read-orders", "for_role", "role.ops"), ("policyrule.ops-read-orders", "of_permission", "permission.read-orders"),
        ("policyrule.devs-read-orders", "for_role", "role.dev"), ("policyrule.devs-read-orders", "of_permission", "permission.read-orders"),
        ("policyrule.reports-export", "for_role", "team.reports"), ("policyrule.reports-export", "of_permission", "permission.export-orders"),
        ("policyrule.devs-export-draft", "for_role", "role.dev"), ("policyrule.devs-export-draft", "of_permission", "permission.export-orders"),
    ]
    return {"nodes": nodes, "edges": [{"from": f, "rel": r, "to": t, "status": "current"} for f, r, t in edges]}


def test_the_snapshot_is_the_intersection_of_what_the_agent_and_the_principal_may_do():
    snap = _policy.snapshot(_graph(), "agent.runner", "principal.ada", at="2026-10-27", version={"build_seq": 3})
    assert snap["snapshot_version"] == _policy.SNAPSHOT_VERSION and snap["generated_at"] == "2026-10-27" and snap["version"] == {"build_seq": 3}
    assert snap["agent"] == {"id": "agent.runner", "label": "Factory runner", "roles": ["role.dev", "team.reports"]}
    assert snap["principal"] == {"id": "principal.ada", "label": "Ada", "kind": "person", "identity": "ada@acme.example", "roles": ["role.dev", "role.ops"]}
    permits = {p["permission"]: p for p in snap["permits"]}
    assert set(permits) == {"permission.write-components", "permission.read-orders"}, "what both may do; the export is the agent's alone, the draft never counts"
    write = permits["permission.write-components"]
    assert write["action"] == "write" and write["resource_class"] == "Component" and write["selector"] == [{"key": "tier", "op": "!=", "value": "legacy"}]
    assert write["resources"] is None, "neither side singles out resources on the rule both share; the selector decides"
    assert write["via"] == {"agent": "policyrule.devs-write", "principal": "policyrule.devs-write"}
    assert permits["permission.read-orders"]["via"] == {"agent": "policyrule.devs-read-orders", "principal": "policyrule.devs-read-orders"}
    forbids = {f["permission"]: f for f in snap["forbids"]}
    assert set(forbids) == {"permission.write-legacy"} and forbids["permission.write-legacy"]["resources"] == ["component.legacy"]
    assert forbids["permission.write-legacy"]["via"] == {"agent": "policyrule.nobody-writes-legacy", "principal": "policyrule.nobody-writes-legacy"}
    assert snap["scopes"] == {"write": ["src/intake", "src/scheduler", "tests/intake"], "denied": ["src/legacy"]}, \
        "the paths of the components the selector admits, through the code map; the forbidden component's paths are denied"
    assert snap["hash"] == _policy.snapshot_hash(snap) and snap["signature"] is None


def test_a_principal_s_forbid_and_a_singled_out_resource_narrow_the_snapshot():
    graph = _graph()
    graph["edges"].append({"from": "policyrule.devs-write", "rel": "singles_out", "to": "component.scheduler", "status": "current"})
    snap = _policy.snapshot(graph, "agent.runner", "principal.ada")
    write = next(p for p in snap["permits"] if p["permission"] == "permission.write-components")
    assert write["resources"] == ["component.scheduler"], "the agent's rule singles out the scheduler; the principal's own route is the same rule"
    assert snap["scopes"]["write"] == ["src/scheduler"]
    graph = _graph()
    graph["edges"] = [e for e in graph["edges"] if not (e["from"] == "policyrule.nobody-writes-legacy" and e["to"] == "role.dev")]
    snap = _policy.snapshot(graph, "agent.runner", "principal.ada")
    assert [f["via"] for f in snap["forbids"]] == [{"agent": None, "principal": "policyrule.nobody-writes-legacy"}], "a forbid on either side forbids"
    assert snap["scopes"]["denied"] == ["src/legacy"]
    bot = _policy.snapshot(_graph(), "agent.runner", "principal.bot")
    assert [p["permission"] for p in bot["permits"]] == ["permission.export-orders"] and bot["scopes"] == {"write": [], "denied": ["src/legacy"]}, \
        "the bot exports and nothing else; the legacy code stays denied through the agent's own role"


def test_what_is_not_an_agent_or_a_principal_is_refused():
    with pytest.raises(_policy.PolicyError, match="agent.nobody"):
        _policy.snapshot(_graph(), "agent.nobody", "principal.ada")
    with pytest.raises(_policy.PolicyError, match="Principal"):
        _policy.snapshot(_graph(), "agent.runner", "role.dev")
    with pytest.raises(_policy.PolicyError, match="Agent"):
        _policy.snapshot(_graph(), "principal.ada", "principal.ada")


def test_the_snapshot_file_is_hashed_signed_and_verifiable(tmp_path, monkeypatch):
    out = str(tmp_path / ".factory" / "policy.json")
    monkeypatch.setenv(KEY_ENV, "s3cret")
    snap = _policy.write_snapshot(_graph(), "agent.runner", "principal.ada", out, at="2026-10-27", key_env=KEY_ENV)
    with open(out, encoding="utf-8") as f:
        written = json.load(f)
    assert written == snap and snap["signature"] == {"algorithm": "HMAC-SHA256", "key": KEY_ENV,
                                                     "value": hmac.new(b"s3cret", snap["hash"].encode("utf-8"), hashlib.sha256).hexdigest()}
    assert _policy.verify_snapshot(out, key_env=KEY_ENV) == [] and _policy.verify_snapshot(out) == []
    monkeypatch.setenv(KEY_ENV, "wrong")
    assert any("signature" in p for p in _policy.verify_snapshot(out, key_env=KEY_ENV))
    written["scopes"]["write"].append("anything")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(written, f)
    assert any("hash" in p for p in _policy.verify_snapshot(out)), "a snapshot edited by hand is not the one the engine wrote"
    monkeypatch.delenv(KEY_ENV)
    with pytest.raises(_policy.PolicyError):
        _policy.write_snapshot(_graph(), "agent.runner", "principal.ada", out, key_env=KEY_ENV)


# ---- the guards ----

def _write(cwd, snap):
    os.makedirs(os.path.join(cwd, ".factory"), exist_ok=True)
    with open(os.path.join(cwd, ".factory", "policy.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f)


def _events(cwd):
    path = os.path.join(cwd, ".factory", "events.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_the_two_guards_share_one_reader_that_stays_plain_python():
    with open(os.path.join(ROOT, "hooks", "policy_snapshot.py"), encoding="utf-8") as f:
        engine = f.read()
    with open(os.path.join(ROOT, "factory", "hooks", "policy_snapshot.py"), encoding="utf-8") as f:
        factory = f.read()
    assert engine == factory, "one reader, copied into both plugins byte for byte"
    assert "import oto" not in engine and "from oto" not in engine, "no engine on the runner's machine"
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    pre = [h["command"] for group in hooks["PreToolUse"] for h in group["hooks"]]
    assert any("policy_guard.py" in c and "python3 -I" in c for c in pre), "the engine plugin guards every session that has a snapshot"
    assert "Edit" in hooks["PreToolUse"][0]["matcher"] and "Bash" in hooks["PreToolUse"][0]["matcher"]


@pytest.mark.parametrize("script", [ENGINE_GUARD, FACTORY_GUARD])
def test_a_guard_refuses_what_the_snapshot_does_not_permit_and_records_the_denial(script, tmp_path):
    cwd = str(tmp_path)
    snap = _policy.snapshot(_graph(), "agent.runner", "principal.ada", at="2026-10-27")
    _write(cwd, snap)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse"}
    code, _out, err = _hook(script, dict(base, tool_name="Edit", tool_input={"file_path": "src/intake/app.py"}), cwd)
    assert code == 0, err
    code, _out, err = _hook(script, dict(base, tool_name="Write", tool_input={"file_path": os.path.join(cwd, "src/legacy/old.py")}), cwd)
    assert code == 2 and "policyrule.nobody-writes-legacy" in err and "src/legacy" in err, err
    code, _out, err = _hook(script, dict(base, tool_name="Edit", tool_input={"file_path": "docs/notes.md"}), cwd)
    assert code == 2 and "docs/notes.md" in err and "src/intake" in err, "outside every permitted path: the snapshot names what it permits\n" + err
    code, _out, err = _hook(script, dict(base, tool_name="Bash", tool_input={"command": "rm -rf src/legacy/old.py"}), cwd)
    assert code == 2 and "src/legacy" in err, err
    code, _out, err = _hook(script, dict(base, tool_name="Bash", tool_input={"command": "pytest tests/intake"}), cwd)
    assert code == 0, err
    code, _out, err = _hook(script, dict(base, tool_name="Read", tool_input={"file_path": "src/legacy/old.py"}), cwd)
    assert code == 0, "reading is not writing"
    events = _events(cwd)
    assert [e["event"] for e in events] == ["denied", "denied", "denied"]
    denied = events[0]
    assert denied["agent"] == "agent.runner" and denied["principal"] == "principal.ada" and denied["rule"] == "policyrule.nobody-writes-legacy"
    assert denied["action"] == "write" and denied["path"] == "src/legacy/old.py" and denied["tool"] == "Write" and denied["snapshot"] == snap["hash"] and denied["at"]
    assert events[1]["rule"] is None and events[1]["path"] == "docs/notes.md", "no rule forbids it; none permits it either"


@pytest.mark.parametrize("script", [ENGINE_GUARD, FACTORY_GUARD])
def test_a_guard_blocks_every_write_on_a_snapshot_it_cannot_trust_and_allows_everything_without_one(script, tmp_path, monkeypatch):
    cwd = str(tmp_path)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/intake/app.py"}}
    code, _out, _err = _hook(script, base, cwd)
    assert code == 0, "no snapshot: not a guarded session"
    snap = _policy.snapshot(_graph(), "agent.runner", "principal.ada", at="2026-10-27")
    tampered = dict(snap, scopes={"write": ["src/intake", "anything"], "denied": []})
    _write(cwd, tampered)
    code, _out, err = _hook(script, base, cwd)
    assert code == 2 and "hash" in err, "edited by hand: nothing is permitted\n" + err
    monkeypatch.setenv(KEY_ENV, "s3cret")
    signed = _policy.write_snapshot(_graph(), "agent.runner", "principal.ada", os.path.join(cwd, ".factory", "policy.json"), at="2026-10-27", key_env=KEY_ENV)
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: "s3cret"})
    assert code == 0, err
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: "wrong"})
    assert code == 2 and "signature" in err, "the key the guard holds does not verify it\n" + err
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: ""})
    assert code == 0, "without the key the guard checks the hash alone and says nothing\n" + err
    with open(os.path.join(cwd, ".factory", "policy.json"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    code, _out, err = _hook(script, base, cwd)
    assert code == 2 and "cannot be read" in err
    assert signed["signature"]["key"] == KEY_ENV


def test_the_factory_guard_keeps_the_run_s_read_only_paths_beside_the_snapshot(tmp_path):
    cwd = str(tmp_path)
    os.makedirs(os.path.join(cwd, ".factory"))
    with open(os.path.join(cwd, ".factory", "run.json"), "w", encoding="utf-8") as f:
        json.dump({"component": "component.intake", "label": "Invoice intake", "write_scope": ["src/intake", "docs"], "read_only": ["contracts"], "cap": 3, "iteration": 0}, f)
    _write(cwd, _policy.snapshot(_graph(), "agent.runner", "principal.ada", at="2026-10-27"))
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse"}
    code, _out, err = _hook(FACTORY_GUARD, dict(base, tool_name="Edit", tool_input={"file_path": "contracts/intake.yaml"}), cwd)
    assert code == 2 and "read-only" in err
    code, _out, err = _hook(FACTORY_GUARD, dict(base, tool_name="Edit", tool_input={"file_path": "docs/notes.md"}), cwd)
    assert code == 2 and "docs/notes.md" in err, "in the run's write scope, but the policy snapshot permits no write there: the policy wins"
    code, _out, err = _hook(FACTORY_GUARD, dict(base, tool_name="Edit", tool_input={"file_path": "src/scheduler/job.py"}), cwd)
    assert code == 0, "permitted by the policy though the run's own scope is narrower: the snapshot is the scope"


# ---- installed: the command, the denials as audit records ----

@pytest.fixture
def ledger(tmp_path):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="The ledger, governed", ontology="policy")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    return root


def test_oto_policy_snapshot_writes_the_file_and_verify_reads_it_and_denials_become_audit_records(ledger, tmp_path, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    out = str(tmp_path / "code" / ".factory" / "policy.json")
    code, text = _cli("policy", "snapshot", "--agent", "agent.merchant-assistant", "--principal", "principal.factory-runner", "--out", out, "--at", "2026-10-27", "--project", ledger)
    assert code == 0 and os.path.exists(out) and "permit(s)" in text, text
    with open(out, encoding="utf-8") as f:
        snap = json.load(f)
    assert snap["agent"]["id"] == "agent.merchant-assistant" and snap["principal"]["kind"] == "service"
    assert [p["action"] for p in snap["permits"]] and snap["scopes"]["write"] == [], "the ledger sample maps no code: a permit on components reaches no path"
    code, text = _cli("policy", "verify", out, "--project", ledger)
    assert code == 0 and "snapshot" in text and "holds" in text, text
    code, text = _cli("policy", "snapshot", "--agent", "agent.merchant-assistant", "--principal", "principal.nobody", "--out", out, "--project", ledger)
    assert code == 1 and "principal.nobody" in text
    code, text = _cli("query", "--project", ledger, "ask", "PL6", "PRINCIPAL=principal.factory-runner")
    assert code == 0 and "status: answered" in text, text
    events = os.path.join(str(tmp_path / "code"), ".factory", "events.jsonl")
    with open(events, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "denied", "tool": "Edit", "action": "write", "path": "src/legacy/old.py", "rule": "policyrule.reports-never-write-postings",
                            "agent": "agent.merchant-assistant", "principal": "principal.factory-runner", "snapshot": snap["hash"], "at": "2026-10-27T10:00:00Z"}) + "\n")
        f.write(json.dumps({"event": "iteration", "run": "r1", "component": "c", "iteration": 1}) + "\n")
        f.write(json.dumps({"event": "denied", "tool": "Bash", "action": "write", "path": "docs/x.md", "rule": None,
                            "agent": "agent.merchant-assistant", "principal": "principal.factory-runner", "snapshot": snap["hash"], "at": "2026-10-27T10:01:00Z"}) + "\n")
    code, text = _cli("policy", "denials", "--events", events, "--project", ledger)
    assert code == 0 and "2 denial(s) recorded" in text, text
    records = [r for r in _audit.read(Project.standard(ledger)) if r.get("action") == "policy denied"]
    assert len(records) == 2 and records[0]["decision"] == "refused" and records[0]["principal"] == "principal.factory-runner"
    assert set(records[0]["nodes"]) == {"agent.merchant-assistant", "principal.factory-runner", "policyrule.reports-never-write-postings"}
    assert "src/legacy/old.py" in records[0]["detail"] and "Edit" in records[0]["detail"]
    assert records[1]["nodes"] == ["agent.merchant-assistant", "principal.factory-runner"] and "no rule permits" in records[1]["detail"]
    code, text = _cli("policy", "denials", "--events", events, "--project", ledger)
    assert code == 0 and "0 denial(s) recorded" in text and "2 already" in text, "each once\n" + text
    code, text = _cli("audit", "verify", "--project", ledger)
    assert code == 0 and "chain intact" in text


def test_the_docs_know_the_snapshot_and_the_guards():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto policy snapshot" in text and "policy_guard.py" in text and "oto policy denials" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 29." in e2e and "oto policy snapshot" in e2e
    with open(os.path.join(ROOT, "factory", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "policy.json" in readme and "oto policy snapshot" in readme
