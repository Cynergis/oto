"""The snapshot's time to live and the re-check before a write (roadmap E6), and the served engine
holding a read to the caller's policy (E5). A snapshot carries `expires_at`; a guard, `verify` and
the engine refuse an expired one. Before `curate apply`, `decide` and `promote`, the engine re-checks
the snapshot it runs under: intact, signed when the project signs, not expired, and still what the
graph says now; a project that requires one refuses a write without it. The served `kg_read` is
answered only for a principal the policy permits to read the tables the query names, the same
computation as the snapshot, with the agent's grants intersected when the caller names one; a
refusal is an audit record."""
import contextlib
import datetime
import io
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

import pytest

from oto import audit as _audit, deploy as _deploy, policy as _policy
from oto.cli import main
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_GUARD = os.path.join(ROOT, "hooks", "policy_guard.py")
KEY_ENV = "OTO_POLICY_KEY"
AGENT, PRINCIPAL = "agent.merchant-assistant", "principal.factory-runner"


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _hook(script, payload, cwd):
    done = subprocess.run([sys.executable, "-I", script], input=json.dumps(payload), cwd=cwd, capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def _config(root, **policy):
    path = os.path.join(root, "project.config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["policy"] = dict(cfg.get("policy") or {}, **policy)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _rewrite(path, **changes):
    """Edit a snapshot the way the engine would have written it: the content changes, the hash follows."""
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    snap.update(changes)
    snap["signature"] = None
    snap["hash"] = _policy.snapshot_hash(snap)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    return snap


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    root = str(tmp_path / "ledger")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="ledger", name="The ledger, governed", ontology="policy")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("OTO_POLICY_SNAPSHOT", raising=False)
    monkeypatch.delenv("OTO_PRINCIPAL", raising=False)
    monkeypatch.delenv("OTO_AGENT", raising=False)
    return root


# ---- the time to live (E6) ----

def test_a_snapshot_expires_and_an_expired_one_is_refused_everywhere(ledger, tmp_path):
    out = str(tmp_path / "code" / ".factory" / "policy.json")
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--ttl", "2", "--project", ledger)
    assert code == 0 and "expires" in text, text
    with open(out, encoding="utf-8") as f:
        snap = json.load(f)
    expires = datetime.datetime.strptime(snap["expires_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert datetime.timedelta(hours=1, minutes=55) < expires - now <= datetime.timedelta(hours=2) and snap["ttl_hours"] == 2
    assert _policy.verify_snapshot(out) == []
    code, text = _cli("policy", "verify", out, "--project", ledger)
    assert code == 0 and "expires" in text, text
    _rewrite(out, expires_at="2026-01-01T00:00:00Z")
    assert any("expired" in p for p in _policy.verify_snapshot(out))
    code, text = _cli("policy", "verify", out, "--project", ledger)
    assert code == 1 and "expired" in text, text
    cwd = str(tmp_path / "code")
    payload = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/x.py"}}
    code, _out, err = _hook(ENGINE_GUARD, payload, cwd)
    assert code == 2 and "expired" in err, "a guard refuses every write on an expired snapshot\n" + err


def test_the_default_ttl_comes_from_the_project_or_is_a_day(ledger, tmp_path):
    out = str(tmp_path / "a.json")
    code, _t = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["ttl_hours"] == 24
    _config(ledger, ttl_hours=6)
    code, _t = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0
    with open(out, encoding="utf-8") as f:
        assert json.load(f)["ttl_hours"] == 6
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--ttl", "0", "--project", ledger)
    assert code == 1 and "ttl" in text.lower()


# ---- the re-check before a write (E6) ----

def test_a_write_needs_no_snapshot_until_the_project_requires_one(ledger):
    code, text = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, text
    _config(ledger, require_snapshot=True)
    code, text = _cli("decide", "policyrule.owner-admin", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "snapshot" in text and "oto policy snapshot" in text, text
    records = [r for r in _audit.read(Project.standard(ledger)) if r.get("action") == "policy denied"]
    assert len(records) == 1 and records[0]["decision"] == "refused" and "decide" in records[0]["detail"] and records[0]["principal"] == "Ada"


def test_the_snapshot_is_re_checked_before_decide(ledger, tmp_path, monkeypatch):
    _config(ledger, require_snapshot=True)
    out = str(tmp_path / "code" / ".factory" / "policy.json")
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0, text
    monkeypatch.setenv("OTO_POLICY_SNAPSHOT", out)
    code, text = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, "a fresh, intact snapshot whose policy is unchanged for this agent and principal lets the decision through\n" + text
    applied = [r for r in _audit.read(Project.standard(ledger)) if r.get("action") == "decide" and r.get("decision") == "applied"]
    assert applied and "snapshot" in (applied[-1]["detail"] or "") and PRINCIPAL in applied[-1]["detail"], "the record says under which snapshot"
    code, text = _cli("decide", "policyrule.compliance-reads-ledger", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, "retiring a rule the snapshot rests on is itself allowed: the snapshot held when it was checked\n" + text
    code, text = _cli("decide", "policyrule.owner-admin", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "changed since" in text and "oto policy snapshot" in text, "now the policy differs from the snapshot: write it again\n" + text
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0
    code, text = _cli("decide", "policyrule.owner-admin", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, text
    _rewrite(out, expires_at="2026-01-01T00:00:00Z")
    code, text = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "expired" in text, text
    with open(out, encoding="utf-8") as f:
        snap = json.load(f)
    snap["scopes"]["write"].append("anything")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f)
    code, text = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "hash" in text, text
    denied = [r for r in _audit.read(Project.standard(ledger)) if r.get("action") == "policy denied"]
    assert len(denied) == 3 and all(r["decision"] == "refused" for r in denied)


def test_a_signing_project_refuses_an_unsigned_snapshot_and_a_wrong_key(ledger, tmp_path, monkeypatch):
    _config(ledger, require_snapshot=True, sign_with=KEY_ENV)
    out = str(tmp_path / "code" / ".factory" / "policy.json")
    monkeypatch.setenv("OTO_POLICY_SNAPSHOT", out)
    monkeypatch.setenv(KEY_ENV, "k1")
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0 and "signed with %s" % KEY_ENV in text, text
    code, text = _cli("decide", "policyrule.owner-admin", "status=active", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 0, text
    monkeypatch.setenv(KEY_ENV, "k2")
    code, text = _cli("decide", "policyrule.owner-admin", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "signature" in text, text
    monkeypatch.setenv(KEY_ENV, "k1")
    _rewrite(out)
    code, text = _cli("decide", "policyrule.owner-admin", "status=retired", "--by", "Ada", "--at", "2026-10-27", "--project", ledger)
    assert code == 1 and "unsigned" in text, "the project signs; an unsigned snapshot is not its\n" + text


def test_curate_apply_and_promote_re_check_the_snapshot_too(ledger, tmp_path, monkeypatch):
    _config(ledger, require_snapshot=True)
    project = Project.standard(ledger)
    with pytest.raises(_policy.PolicyError, match="snapshot"):
        _policy.enforce(project, "curate apply", "Ada")
    with pytest.raises(_policy.PolicyError, match="snapshot"):
        _deploy.promote(project, "test", "abc123", by="Ada")
    code, text = _cli("curate", "start", "--project", ledger)
    assert code == 0, text
    code, text = _cli("curate", "apply", "--by", "Ada", "--note", "nothing", "--project", ledger)
    assert code == 1 and "snapshot" in text, text
    out = str(tmp_path / "code" / ".factory" / "policy.json")
    code, text = _cli("policy", "snapshot", "--agent", AGENT, "--principal", PRINCIPAL, "--out", out, "--project", ledger)
    assert code == 0
    monkeypatch.setenv("OTO_POLICY_SNAPSHOT", out)
    note = _policy.enforce(project, "curate apply", "Ada")
    assert note and PRINCIPAL in note and AGENT in note
    assert len([r for r in _audit.read(project) if r.get("action") == "policy denied"]) == 3


# ---- the served read, per principal (E5) ----

LEDGER_SQL = """
CREATE TABLE postings (posting_id INTEGER PRIMARY KEY, account_id INTEGER, amount_cents INTEGER);
INSERT INTO postings VALUES (1, 10, 1000), (2, 11, 900);
CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, email TEXT);
INSERT INTO customers VALUES (10, 'a@example.com');
CREATE TABLE daily_balances (account_id INTEGER, day TEXT, balance_cents INTEGER);
INSERT INTO daily_balances VALUES (10, '2026-10-27', 1000);
"""


def _engine(project):
    import importlib
    os.environ["OTO_DB"] = project.layout.database
    os.environ["OTO_PROJECT_CONFIG"] = project.config_path
    os.environ.pop("OTO_STORE", None)
    from oto.serve import engine
    importlib.reload(engine)
    return engine


def _call(engine, name, caller=None, **arguments):
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}, caller=caller)
    result = reply["result"]
    return result["isError"], "".join(c["text"] for c in result["content"])


@pytest.fixture
def served(ledger, tmp_path):
    store = str(tmp_path / "ledger.sqlite")
    con = sqlite3.connect(store)
    con.executescript(LEDGER_SQL)
    con.commit()
    con.close()
    cfg = _deploy.starter("acme/ledger-kg", "https://github.com/acme/ledger-kg-store", "ledger-kg")
    cfg["overlay"] = {"connector": "sqlite", "connection": {"endpoint": store, "auth": "file"}, "native_read": True}
    with open(os.path.join(ledger, _deploy.NAME), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return ledger


def test_kg_read_is_answered_for_the_principal_the_policy_permits_and_refused_otherwise(served):
    project = Project.standard(served)
    engine = _engine(project)
    error, text = _call(engine, "kg_read", sql="SELECT account_id FROM postings")
    assert error and "principal" in text and "X-Oto-Principal" in text, "a policed project needs to know who asks\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": "principal.nobody"}, sql="SELECT account_id FROM postings")
    assert error and "principal.nobody" in text, text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL}, sql="SELECT account_id, amount_cents FROM postings ORDER BY 1")
    assert not error and "2 row(s)" in text and "1000" in text, "compliance reads a table that holds no personal data\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL}, sql="SELECT email FROM customers")
    assert error and "customers" in text and "no rule permits" in text, "the table holds personal data (derived from its column): the selector pii=false does not admit it\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": "principal.ops-clerk"}, sql="SELECT account_id FROM postings")
    assert error and "principal.ops-clerk" in text and "read" in text, "the clerk's team exports and reads nothing\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL}, sql="SELECT p.account_id FROM postings p JOIN daily_balances b ON b.account_id = p.account_id")
    assert not error, "every table the query names is permitted\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL}, sql="SELECT p.account_id FROM postings p JOIN customers c ON c.customer_id = p.account_id")
    assert error and "customers" in text, "one table the query names is not\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL}, sql="SELECT 1 FROM nowhere")
    assert error and "nowhere" in text and "knows no table" in text, text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL, "agent": AGENT}, sql="SELECT account_id FROM postings")
    assert not error, "the agent is granted compliance's role too: the intersection still permits\n" + text
    error, text = _call(engine, "kg_read", caller={"principal": PRINCIPAL, "agent": "agent.nobody"}, sql="SELECT account_id FROM postings")
    assert error and "agent.nobody" in text
    denied = [r for r in _audit.read(project) if r.get("action") == "policy denied"]
    assert len(denied) == 3 and all(r["decision"] == "refused" for r in denied), \
        "the three reads a rule decided against; an anonymous caller, an unknown principal or agent and an unknown table are refused before any decision"
    assert any("customers" in (r["detail"] or "") and PRINCIPAL == r["principal"] for r in denied), "a refused read is an audit record"
    assert not any("postings" in (r["detail"] or "") and r["principal"] == PRINCIPAL and "customers" not in (r["detail"] or "") for r in denied), "a permitted read is not"


def test_the_caller_comes_from_the_environment_on_stdio_and_from_headers_over_http(served, monkeypatch):
    project = Project.standard(served)
    engine = _engine(project)
    monkeypatch.setenv("OTO_PRINCIPAL", PRINCIPAL)
    error, text = _call(engine, "kg_read", sql="SELECT account_id FROM postings")
    assert not error, text
    monkeypatch.delenv("OTO_PRINCIPAL")
    from oto.serve import http as _http
    server = _http.Server(engine, "127.0.0.1", 0, app_dir=None, project_root=served, identity=project.config()).start()
    try:
        def get(url, headers=None):
            req = urllib.request.Request(url, headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8")
        status, text = get(server.url + "/api/read?sql=SELECT+account_id+FROM+postings")
        assert status == 400 and "X-Oto-Principal" in text, text
        status, text = get(server.url + "/api/read?sql=SELECT+account_id+FROM+postings", {"X-Oto-Principal": PRINCIPAL})
        assert status == 200 and "2 row(s)" in text, text
        status, text = get(server.url + "/api/read?sql=SELECT+email+FROM+customers", {"X-Oto-Principal": PRINCIPAL})
        assert status == 400 and "no rule permits" in text, text
        body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "kg_read", "arguments": {"sql": "SELECT account_id FROM postings"}}}).encode("utf-8")
        req = urllib.request.Request(server.url + "/rpc", data=body, headers={"Content-Type": "application/json", "X-Oto-Principal": PRINCIPAL, "X-Oto-Agent": AGENT}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            reply = json.loads(r.read().decode("utf-8"))
        assert reply["result"]["isError"] is False and "2 row(s)" in reply["result"]["content"][0]["text"]
    finally:
        server.stop()


def test_a_project_without_the_policy_pack_reads_as_before(tmp_path, monkeypatch):
    root = str(tmp_path / "plain")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plain", name="Plain", ontology="data")
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    store = str(tmp_path / "plain.sqlite")
    con = sqlite3.connect(store)
    con.executescript(LEDGER_SQL)
    con.commit()
    con.close()
    cfg = _deploy.starter("acme/plain-kg", "https://github.com/acme/plain-kg-store", "plain-kg")
    cfg["overlay"] = {"connector": "sqlite", "connection": {"endpoint": store, "auth": "file"}, "native_read": True}
    with open(os.path.join(root, _deploy.NAME), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    monkeypatch.delenv("OTO_PRINCIPAL", raising=False)
    engine = _engine(Project.standard(root))
    error, text = _call(engine, "kg_read", sql="SELECT account_id FROM postings")
    assert not error, "no PolicyRule in the vocabulary: nothing to hold the read to\n" + text


def test_the_docs_know_the_ttl_the_re_check_and_the_principal_header():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "X-Oto-Principal" in text and "require_snapshot" in text and "expires_at" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 30." in e2e and "X-Oto-Principal" in e2e and "--ttl" in e2e
