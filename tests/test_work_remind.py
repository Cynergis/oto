"""Phase 6 closes (roadmap N2, N5): the inbox is read under a principal's identity, so a user sees
only the messages addressed to them; `oto work remind` sends a reminder for every pending message
past its due date, once per day, as a message of its own that is never a reply, and a scheduled
workflow runs it for people who are not in a session; the phase 6 milestone is reached."""
import contextlib
import io
import json
import os

import pytest

from oto.cli import main
from oto.model import ontologies
from oto.project import Project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(ROOT, "oto", "ontologies", "communication")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _graph(root):
    with open(Project.standard(root).graph_path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def comms(tmp_path, monkeypatch):
    from oto.scaffold import init
    root = str(tmp_path / "comms")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="comms", name="Comms", ontology="communication")
    monkeypatch.delenv("OTO_PRINCIPAL", raising=False)
    return root


# ---- the inbox under a principal's identity (N2) ----

def test_the_inbox_is_read_under_the_principal_s_identity_and_nobody_else_s(comms, monkeypatch):
    monkeypatch.setenv("OTO_PRINCIPAL", "Mina Okafor")
    code, out = _cli("work", "inbox", "--project", comms)
    assert code == 0 and "1 pending for Mina Okafor" in out and "message.t-ledger-replica-1" in out, out
    code, out = _cli("work", "inbox", "--as", "Mina Okafor", "--project", comms)
    assert code == 0 and "1 pending for Mina Okafor" in out, "naming yourself is allowed\n" + out
    code, out = _cli("work", "inbox", "--as", "Payments team", "--project", comms)
    assert code == 1 and "only" in out and "Mina Okafor" in out and "Payments team" in out, "a user sees only messages addressed to them\n" + out
    code, out = _cli("work", "inbox", "--as", "Payments team", "--hook", "--project", comms)
    assert code == 0 and out.strip() == "", "the hook never fails and says nothing it may not"
    monkeypatch.setenv("OTO_PRINCIPAL", "nobody@nowhere.example")
    code, out = _cli("work", "inbox", "--project", comms)
    assert code == 1 and "nobody@nowhere.example" in out and "Person" in out, out
    code, out = _cli("work", "inbox", "--hook", "--project", comms)
    assert code == 0 and out.strip() == ""
    monkeypatch.delenv("OTO_PRINCIPAL")
    code, out = _cli("work", "inbox", "--principal", "Mina Okafor", "--project", comms)
    assert code == 0 and "1 pending for Mina Okafor" in out, "the flag says what the environment would\n" + out
    code, out = _cli("work", "inbox", "--as", "Payments team", "--project", comms)
    assert code == 0 and "nothing pending for Payments team" in out, "with no principal established, --as reads any inbox, as before"


# ---- the reminder (N5) ----

def test_a_pending_message_past_due_gets_one_reminder_a_day_that_is_never_a_reply(comms):
    code, out = _cli("work", "notify", "workitem.t-ledger-replica", "--by", "Chiheb Dkhil", "--at", "2026-10-26",
                     "--due", "2026-10-30", "--body", "Can you decide the budget this week?", "--project", comms)
    assert code == 0, out
    code, out = _cli("work", "remind", "--at", "2026-10-29", "--project", comms)
    assert code == 0 and "nothing" in out and "0 reminder(s)" in out, "not due yet\n" + out
    code, out = _cli("work", "remind", "--at", "2026-10-30", "--dry-run", "--project", comms)
    assert code == 0 and "message.t-ledger-replica-2" in out and "would send" in out, out
    assert not any(n["id"] == "message.t-ledger-replica-3" for n in _graph(comms)["nodes"]), "a dry run writes nothing"
    code, out = _cli("work", "remind", "--at", "2026-10-30", "--project", comms)
    assert code == 0 and "1 reminder(s) sent" in out and "message.t-ledger-replica-3" in out and "Mina Okafor" in out, out
    graph = _graph(comms)
    reminder = next(n for n in graph["nodes"] if n["id"] == "message.t-ledger-replica-3")
    a = reminder["attributes"]
    assert a["from"] == "oto work remind" and a["sent"] == "2026-10-30" and "due" not in a and "status" not in a
    assert a["body"].startswith("Reminder:") and "2026-10-30" in a["body"] and "since 2026-10-26" in a["body"] and "Can you decide the budget this week?" in a["body"]
    edges = {(e["rel"], e["to"]) for e in graph["edges"] if e["from"] == reminder["id"]}
    assert ("reminder_of", "message.t-ledger-replica-2") in edges and ("sent_to", "person.m-okafor") in edges and ("regarding", "workitem.t-ledger-replica") in edges
    assert not any(rel == "in_reply_to" for rel, _t in edges), "a reminder answers nothing: the original stays pending"
    code, out = _cli("work", "remind", "--at", "2026-10-30", "--project", comms)
    assert code == 0 and "0 reminder(s) sent" in out and "1 already" in out, "once a day\n" + out
    code, out = _cli("work", "remind", "--at", "2026-10-31", "--project", comms)
    assert code == 0 and "1 reminder(s) sent" in out and "message.t-ledger-replica-4" in out, "the next day, another\n" + out
    code, out = _cli("work", "remind", "--at", "2026-11-01", "--by", "The scheduler", "--project", comms)
    assert code == 0 and "1 reminder(s)" in out
    assert next(n for n in _graph(comms)["nodes"] if n["id"] == "message.t-ledger-replica-5")["attributes"]["from"] == "The scheduler"
    code, out = _cli("work", "inbox", "--as", "Mina Okafor", "--project", comms)
    assert code == 0 and "5 pending for Mina Okafor" in out and "reminder of message.t-ledger-replica-2" in out, out
    code, out = _cli("build", "--project", comms)
    assert code == 0, out
    code, out = _cli("query", "--project", comms, "ask", "CM4", "MESSAGE=message.t-ledger-replica-2")
    assert code == 0 and "status: answered" in out and "message.t-ledger-replica-3" in out and "message.t-ledger-replica-5" in out, out
    code, out = _cli("query", "--project", comms, "ask", "CM3")
    assert code == 0 and "message.t-ledger-replica-3" not in out and "message.t-ledger-replica-4" not in out, \
        "a reminder carries no due date, so it is never overdue itself (CM3 reads the clock, so the original is listed only once its day has passed)\n" + out
    code, out = _cli("work", "reply", "message.t-ledger-replica-2", "--body", "Decided: approved.", "--by", "Mina Okafor", "--at", "2026-11-02", "--resolve", "--project", comms)
    assert code == 0, out
    code, out = _cli("work", "remind", "--at", "2026-11-03", "--project", comms)
    assert code == 0 and "0 reminder(s) sent" in out, "a resolved message is reminded no more\n" + out
    code, out = _cli("work", "remind", "--project", comms)
    assert code == 1 and "--at" in out, "the date is never defaulted"


def test_the_communication_pack_knows_a_reminder():
    manifest = ontologies.manifest_for("communication")
    assert manifest["release"] == 3
    assert ontologies.self_check("communication") == [], ontologies.self_check("communication")
    with open(os.path.join(PACK, "ontology.config.json"), encoding="utf-8") as f:
        own = json.load(f)
    rel = own["properties"]["reminder_of"]
    assert rel["domain"] == "Message" and rel["range"] == "Message" and rel.get("max") == 1
    questions = ontologies.questions_for("communication")
    assert "MESSAGE" in questions["CM4"]["params"] and "remind" in questions["CM4"]["question"].lower()


def test_a_scheduled_workflow_nudges_people_who_are_not_in_a_session():
    with open(os.path.join(ROOT, ".github", "workflows", "oto-remind.yml"), encoding="utf-8") as f:
        text = f.read()
    assert "schedule:" in text and "cron:" in text and "workflow_dispatch:" in text
    assert "oto work remind" in text and "--project roadmap" in text and "gh pr create" in text
    assert "pull-requests: write" in text and "contents: write" in text


# ---- phase 6 closes ----

def test_the_phase_6_milestone_is_reached_and_the_docs_close_the_phase():
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    phase6 = next(n for n in graph["nodes"] if n["id"] == "milestone.phase-6")
    assert phase6["attributes"]["state"] == "reached" and any(s.startswith("assertion:") for s in phase6.get("sources") or []), \
        "a named person decided it, under the gates"
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 31." in e2e and "oto work remind" in e2e and "OTO_PRINCIPAL" in e2e and "phase 6" in e2e.lower()
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto work remind" in text and "OTO_PRINCIPAL" in text
    with open(os.path.join(ROOT, "skills", "work", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    assert "oto work remind" in skill
