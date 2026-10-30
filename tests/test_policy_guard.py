"""The engine plugin's guard (hooks/policy_guard.py) and the reader it imports (hooks/policy_snapshot.py),
which any plugin copies byte for byte. A session that has a snapshot (`.factory/policy.json`, written by the
policy pack's `oto policy snapshot`, a pack of the registry since ADR-0010) may write only where the snapshot
permits; a snapshot the guard cannot trust blocks every write; no snapshot guards nothing. The guard is plain
Python with no engine on the machine, so these tests write the snapshot by hand, in the shape the pack writes,
hashed and signed the way the reader checks it."""
import datetime
import hashlib
import hmac
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_GUARD = os.path.join(ROOT, "hooks", "policy_guard.py")
KEY_ENV = "OTO_POLICY_KEY"


def _reader():
    spec = importlib.util.spec_from_file_location("policy_snapshot_under_test", os.path.join(ROOT, "hooks", "policy_snapshot.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(key=None, scopes=None):
    """A snapshot as the policy pack writes one for agent.runner acting for principal.ada: intake and
    scheduler writable, the legacy code denied by a named rule."""
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap = {"agent": {"id": "agent.runner", "label": "Factory runner"}, "principal": {"id": "principal.ada", "label": "Ada"},
            "scopes": scopes or {"write": ["src/intake", "tests/intake", "src/scheduler"], "denied": ["src/legacy"]},
            "forbids": [{"paths": ["src/legacy"], "via": {"principal": "policyrule.nobody-writes-legacy"}}],
            "written_at": "2026-10-27T10:00:00Z", "ttl_hours": 1, "expires_at": expires, "signature": None}
    snap["hash"] = _reader().content_hash(snap)
    if key:
        snap["signature"] = {"key": KEY_ENV, "value": hmac.new(key.encode("utf-8"), snap["hash"].encode("utf-8"), hashlib.sha256).hexdigest()}
    return snap


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


def _hook(script, payload, cwd, env=None):
    done = subprocess.run([sys.executable, "-I", script], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True,
                          env=dict(os.environ, **(env or {})))
    return done.returncode, done.stdout, done.stderr


def test_the_reader_any_guard_copies_stays_plain_python():
    with open(os.path.join(ROOT, "hooks", "policy_snapshot.py"), encoding="utf-8") as f:
        engine = f.read()
    assert "byte for byte" in engine, "the reader says it is copied whole into any plugin whose guard reads the snapshot"
    assert "import oto" not in engine and "from oto" not in engine, "no engine on the runner's machine"
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    pre = [h["command"] for group in hooks["PreToolUse"] for h in group["hooks"]]
    assert any("policy_guard.py" in c and "python3 -I" in c for c in pre), "the engine plugin guards every session that has a snapshot"
    assert "Edit" in hooks["PreToolUse"][0]["matcher"] and "Bash" in hooks["PreToolUse"][0]["matcher"]
    reader = _reader()
    assert reader.check(_snapshot()) is None and reader.check(dict(_snapshot(), hash="0" * 64)) is not None


@pytest.mark.parametrize("script", [ENGINE_GUARD])
def test_a_guard_refuses_what_the_snapshot_does_not_permit_and_records_the_denial(script, tmp_path):
    cwd = str(tmp_path)
    snap = _snapshot()
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


@pytest.mark.parametrize("script", [ENGINE_GUARD])
def test_a_guard_blocks_every_write_on_a_snapshot_it_cannot_trust_and_allows_everything_without_one(script, tmp_path):
    cwd = str(tmp_path)
    base = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/intake/app.py"}}
    code, _out, _err = _hook(script, base, cwd)
    assert code == 0, "no snapshot: not a guarded session"
    snap = _snapshot()
    tampered = dict(snap, scopes={"write": ["src/intake", "anything"], "denied": []})
    _write(cwd, tampered)
    code, _out, err = _hook(script, base, cwd)
    assert code == 2 and "hash" in err, "edited by hand: nothing is permitted\n" + err
    _write(cwd, _snapshot(key="s3cret"))
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: "s3cret"})
    assert code == 0, err
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: "wrong"})
    assert code == 2 and "signature" in err, "the key the guard holds does not verify it\n" + err
    code, _out, err = _hook(script, base, cwd, env={KEY_ENV: ""})
    assert code == 0, "without the key the guard checks the hash alone and says nothing\n" + err
    expired = _snapshot()
    expired["expires_at"] = "2026-10-27T10:00:00Z"
    expired["hash"] = _reader().content_hash(expired)
    _write(cwd, expired)
    code, _out, err = _hook(script, base, cwd)
    assert code == 2 and "expired" in err, err
    with open(os.path.join(cwd, ".factory", "policy.json"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    code, _out, err = _hook(script, base, cwd)
    assert code == 2 and "cannot be read" in err
