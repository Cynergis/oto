"""The audit log (roadmap F2, F3): one append-only, hash-chained record per write, keyed to the nodes
it touched, with who did it, through what, on which version of the graph, and what was decided.
`oto audit verify` proves the chain; `oto audit for <node>` answers "who did what to this".

Every path that changes what the project believes appends: the work pack's commits (set, notify,
reply, event) and their refusals, `curate apply` and `undo`, `ingest complete`, `publish` and the
promotions. A record edited, removed or reordered breaks the chain at that record and verify says
where."""
import contextlib
import io
import json
import os
import subprocess

import pytest

from oto import audit
from oto.cli import main
from oto.project import Project
from oto.scaffold import init


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


@pytest.fixture
def plan(tmp_path):
    root = str(tmp_path / "plan")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plan", name="The plan", ontology="communication")
    return root


def _records(root):
    return audit.read(Project.standard(root))


def _lines(root):
    with open(audit.path(Project.standard(root)), encoding="utf-8") as f:
        return [l for l in f.read().splitlines() if l.strip()]


def _rewrite(root, lines):
    with open(audit.path(Project.standard(root)), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))


# ---- the chain ----

def test_records_chain_and_verify_passes_on_an_untouched_log(plan):
    project = Project.standard(plan)
    first = audit.append(project, action="work set", principal="Chiheb Dkhil", nodes=["workitem.x"], decision="applied", detail="x: open -> blocked")
    second = audit.append(project, action="curate apply", principal="Sam Lee", nodes=["a", "b"], decision="applied")
    assert first["seq"] == 1 and second["seq"] == 2
    assert first["prev"] == "" and second["prev"] == first["hash"]
    assert len(first["hash"]) == 64 and first["hash"] != second["hash"]
    assert first["agent"].startswith("oto ") and first["graph"] and len(first["graph"]) == 16, "the graph's version is a hash of what it believes"
    assert first["trace_id"] is None, "tracing arrives with F1; the field is there for it"
    report = audit.verify(project)
    assert report == {"ok": True, "records": 2, "broken": None, "why": None}


def test_an_edited_removed_or_reordered_record_breaks_the_chain_where_it_happened(plan):
    project = Project.standard(plan)
    for n in range(4):
        audit.append(project, action="work set", principal="x", nodes=["n%d" % n], decision="applied")
    good = _lines(plan)
    edited = json.loads(good[1])
    edited["principal"] = "someone else"
    _rewrite(plan, good[:1] + [json.dumps(edited, sort_keys=True)] + good[2:])
    report = audit.verify(project)
    assert not report["ok"] and report["broken"] == 2 and "hash" in report["why"], report
    _rewrite(plan, good[:1] + good[2:])
    report = audit.verify(project)
    assert not report["ok"] and report["broken"] == 3 and "prev" in report["why"], "the record after the gap no longer chains"
    _rewrite(plan, [good[0], good[2], good[1], good[3]])
    assert audit.verify(project)["broken"] == 3
    _rewrite(plan, good + ['{"not": "a record"}'])
    report = audit.verify(project)
    assert not report["ok"] and report["broken"] == 5
    _rewrite(plan, good)
    assert audit.verify(project)["ok"]
    assert audit.verify(Project.standard(plan)) == {"ok": True, "records": 4, "broken": None, "why": None}


def test_the_log_is_keyed_to_nodes(plan):
    project = Project.standard(plan)
    audit.append(project, action="work set", principal="x", nodes=["workitem.a", "transition.a-1"], decision="applied")
    audit.append(project, action="work notify", principal="y", nodes=["workitem.a", "message.a-1"], decision="applied")
    audit.append(project, action="work set", principal="x", nodes=["workitem.b"], decision="refused", detail="a block carries its context")
    assert [r["action"] for r in audit.for_node(project, "workitem.a")] == ["work set", "work notify"]
    assert [r["decision"] for r in audit.for_node(project, "workitem.b")] == ["refused"]
    assert audit.for_node(project, "nothing") == []


def test_no_log_verifies_as_empty(plan):
    assert audit.verify(Project.standard(plan)) == {"ok": True, "records": 0, "broken": None, "why": None}
    code, out = _cli("audit", "verify", "--project", plan)
    assert code == 0 and "0 record" in out


# ---- every write path appends ----

def test_the_work_pack_records_what_it_applied_and_what_it_refused(plan):
    code, _ = _cli("work", "set", "workitem.s-settlement-batch", "--state", "blocked", "--reason", "r", "--waiting-on", "team.payments",
                   "--by", "Chiheb Dkhil", "--at", "2026-10-20", "--project", plan)
    assert code == 0
    code, _ = _cli("work", "set", "workitem.s-settlement-batch", "--state", "blocked", "--by", "Chiheb Dkhil", "--at", "2026-10-21", "--project", plan)
    assert code == 1
    code, _ = _cli("work", "notify", "workitem.s-settlement-batch", "--by", "Chiheb Dkhil", "--at", "2026-10-21", "--project", plan)
    assert code == 0
    code, _ = _cli("work", "event", "merged-pr", "--repo", "Cynergis/oto", "--number", "7", "--item", "workitem.s-evidence-retention",
                   "--environment", "prod", "--at", "2026-10-22", "--project", plan)
    assert code == 0
    records = _records(plan)
    assert [(r["action"], r["decision"]) for r in records] == [("work set", "applied"), ("work set", "refused"), ("work notify", "applied"), ("work event", "applied")]
    assert records[0]["principal"] == "Chiheb Dkhil" and "transition.s-settlement-batch-1" in records[0]["nodes"] and "workitem.s-settlement-batch" in records[0]["nodes"]
    assert records[1]["nodes"] == ["workitem.s-settlement-batch"] and "--reason" in records[1]["detail"]
    assert "message.t-ledger-replica-1" not in records[2]["nodes"] and any(n.startswith("message.") for n in records[2]["nodes"])
    assert records[3]["principal"] == "pull request Cynergis/oto#7 merged" and records[3]["detail"].startswith("github:")
    assert records[0]["graph"] != records[2]["graph"], "the graph's version moved between the two writes"
    assert records[1]["graph"] == records[0]["graph"], "a refusal changes nothing"
    assert audit.verify(Project.standard(plan))["ok"]
    code, out = _cli("audit", "for", "workitem.s-settlement-batch", "--project", plan)
    assert code == 0 and out.count("\n") >= 3 and "refused" in out and "Chiheb Dkhil" in out, out


def test_curate_apply_undo_and_ingest_complete_append(plan):
    project = Project.standard(plan)
    code, _ = _cli("curate", "start", "--project", plan)
    graph_path = os.path.join(plan, "graph.candidate.json")
    with open(graph_path, encoding="utf-8") as f:
        candidate = json.load(f)
    candidate["nodes"].append({"id": "team.audit", "type": "Team", "label": "Audit team", "summary": "Invented for the test.",
                               "status": "current", "as_of": "2026-10-20", "valid_from": "2026-10-20",
                               "source_type": "human_assertion", "sources": [], "aliases": [], "tags": []})
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    code, out = _cli("curate", "apply", "--by", "Sam Lee", "--note", "a team", "--force", "--project", plan)
    assert code == 0, out
    code, out = _cli("curate", "undo", "--project", plan)
    assert code == 0, out
    with open(os.path.join(plan, "inbox", "note.md"), "w", encoding="utf-8") as f:
        f.write("# A note\n\nThe audit team reads the log.\n")
    code, out = _cli("ingest", "--project", plan)
    assert code == 0, out
    run_id = [m["run_id"] for m in __import__("oto.intake.pipeline", fromlist=["open_runs"]).open_runs(project)][0]
    code, out = _cli("ingest", "complete", "--run", run_id, "--force", "--project", plan)
    assert code == 0, out
    actions = [(r["action"], r["decision"]) for r in _records(plan)]
    assert actions == [("curate apply", "applied"), ("curate undo", "applied"), ("ingest complete", "applied")], actions
    records = _records(plan)
    assert records[0]["principal"] == "Sam Lee" and records[0]["nodes"] == ["team.audit"]
    assert "note.md" in records[2]["detail"]
    assert audit.verify(project)["ok"]


def test_the_principal_is_the_git_identity_when_nobody_is_named(plan):
    subprocess.run(["git", "init", "-q"], cwd=plan, check=True)
    subprocess.run(["git", "config", "user.name", "Mina Okafor"], cwd=plan, check=True)
    subprocess.run(["git", "config", "user.email", "mina@example.com"], cwd=plan, check=True)
    code, out = _cli("work", "reply", "message.t-ledger-replica-1", "--body", "On it.", "--at", "2026-10-07", "--project", plan)
    assert code == 0, out
    assert _records(plan)[0]["principal"] == "Mina Okafor <mina@example.com>"


def test_the_cli_verifies_and_reads_the_log(plan):
    project = Project.standard(plan)
    audit.append(project, action="work set", principal="x", nodes=["workitem.a"], decision="applied", detail="a: open -> blocked")
    code, out = _cli("audit", "verify", "--project", plan)
    assert code == 0 and "1 record" in out and "intact" in out, out
    code, out = _cli("audit", "log", "--project", plan)
    assert code == 0 and "work set" in out and "workitem.a" in out
    good = _lines(plan)
    broken = json.loads(good[0])
    broken["decision"] = "refused"
    _rewrite(plan, [json.dumps(broken, sort_keys=True)])
    code, out = _cli("audit", "verify", "--project", plan)
    assert code == 1 and "record 1" in out and "hash" in out, out
