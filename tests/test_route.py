"""The route of a pull request, and its gate (docs/plans/graph-journeys.md, phase 2).

A change enters main by one of three routes, derived from what the pull request carries: `session`
when the one ledger entry it adds carries a confirmation whose fingerprint equals the fact-level diff
between the two graph.json; `guardrailed` when the ingest runs it carries came from the transcripts
folder the project names; `reviewed` otherwise. `oto route check` is the gate: the GitHub-only facts
(the author, the reviews, the commit verification) come in as flags, so the engine never calls
GitHub, and a route only moves towards reviewed."""
import contextlib
import io
import json
import os
import subprocess
import tempfile

from oto import route
from oto.cli import main
from oto.curate import session

from test_curate import _node, _project


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, check=True).stdout.strip()


def _commit(root, message):
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _repository(root):
    """A knowledge project under git, its first commit the base of every pull request below."""
    project = _project(root)
    _git(root, "init", "-q", "-b", "main")
    return project, _commit(root, "the project")


def _change(project, by=None, confirm=False, node=None):
    session.start(project)
    candidate = session.candidate(project)
    candidate["nodes"].append(node or _node("c.2", summary="a second claim", sources=["memo"], source_doc="memo"))
    with open(session.candidate_path(project), "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    args = ["curate", "apply", "--project", project.data, "--note", "a change"] + (["--by", by] if by else []) + (["--confirm"] if confirm else [])
    code, out = _cli(*args)
    assert code == 0, out


def test_a_change_confirmed_in_a_session_takes_the_session_route_when_the_record_holds():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "the card")
        shown = route.show(root, base, head)
        assert shown["route"] == route.SESSION, shown
        assert shown["confirmation"]["by"] == "chiheb@cynergis.ai" and shown["fingerprint"] == shown["confirmation"]["fingerprint"]
        assert len(shown["entries"]) == 1 and any("confirm" in r for r in shown["reasons"])
        # the gate: the confirmer is the author and the commits are verified
        verdict = route.check(root, base, head, authors=["chihebdk", "chiheb@cynergis.ai"], verified=True)
        assert verdict["ok"] and verdict["route"] == route.SESSION, verdict
        # not verified: the record cannot be trusted, the route becomes reviewed and needs an approval
        verdict = route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=False)
        assert not verdict["ok"] and verdict["route"] == route.REVIEWED and verdict["proposed"] == route.SESSION
        assert any("verified" in r for r in verdict["reasons"]) and any("approving review" in r for r in verdict["reasons"]), verdict["reasons"]
        assert route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=False, approved=True)["ok"], "a person's approval carries it instead"
        # another author than the confirmer: the same
        verdict = route.check(root, base, head, authors=["someone-else"], verified=True)
        assert not verdict["ok"] and verdict["route"] == route.REVIEWED and any("the author" in r for r in verdict["reasons"]), verdict["reasons"]
        # the command line
        code, out = _cli("route", "show", "--base", base, "--head", head, "--project", root)
        assert code == 0 and "route: session" in out and shown["fingerprint"][:12] in out, out
        code, out = _cli("route", "check", "--base", base, "--head", head, "--author", "chiheb@cynergis.ai", "--verified", "--json", "--project", root)
        assert code == 0 and json.loads(out)["ok"] is True, out
        code, out = _cli("route", "check", "--base", base, "--head", head, "--author", "chiheb@cynergis.ai", "--project", root)
        assert code == 1 and "reviewed" in out and "verified" in out, out


def test_a_byte_changed_after_the_confirmation_breaks_the_record():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        [n for n in graph["nodes"] if n["id"] == "c.2"][0]["summary"] = "edited after the person confirmed"
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2)
        head = _commit(root, "the card, edited")
        shown = route.show(root, base, head)
        assert shown["route"] == route.REVIEWED and shown["proposed"] == route.SESSION
        assert any("does not match" in r for r in shown["reasons"]), shown["reasons"]
        assert not route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=True)["ok"]
        # the file written again with other whitespace, the facts the same: the record still holds
        _git(root, "checkout", "-q", base)
        _git(root, "checkout", "-q", "-b", "same-facts")
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=4, sort_keys=True)
        head = _commit(root, "the card, reformatted")
        assert route.show(root, base, head)["route"] == route.SESSION


def test_two_confirmed_applies_in_one_pull_request_and_a_rewritten_ledger_go_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        _change(project, by="chiheb@cynergis.ai", confirm=True, node=_node("c.3", summary="a third", sources=["memo"], source_doc="memo"))
        head = _commit(root, "two cards")
        shown = route.show(root, base, head)
        assert shown["route"] == route.REVIEWED and len(shown["entries"]) == 2
        assert any("one confirmed change per pull request" in r for r in shown["reasons"]), shown["reasons"]
        # the ledger rewritten (an entry the base holds dropped at the head): never a session change
        base = head
        with open(os.path.join(root, "changelog.jsonl"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(os.path.join(root, "changelog.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines[1:]) + "\n")
        head = _commit(root, "ledger rewritten")
        shown = route.show(root, base, head)
        assert shown["route"] == route.REVIEWED and any("rewritten" in r for r in shown["reasons"]), shown["reasons"]
        assert not route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=True)["ok"]


def test_a_change_drafted_from_documents_is_reviewed_and_needs_one_approval():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _change(project, by="oto pipeline")
        head = _commit(root, "oto author: run x")
        shown = route.show(root, base, head)
        assert shown["route"] == route.REVIEWED and shown["confirmation"] is None
        assert any("no confirmation" in r for r in shown["reasons"]), shown["reasons"]
        assert not route.check(root, base, head, authors=["oto pipeline"], verified=True)["ok"]
        verdict = route.check(root, base, head, authors=["oto pipeline"], verified=True, approved=True)
        assert verdict["ok"] and verdict["route"] == route.REVIEWED
        code, out = _cli("route", "check", "--base", base, "--head", head, "--approved", "--project", root)
        assert code == 0 and "route: reviewed" in out and "approved" in out, out


def test_a_run_from_the_transcripts_folder_takes_the_guardrailed_route_which_the_guardrails_then_judge():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        # the project names the folder; without it, transcripts are documents like any other. Attribution is
        # off here so a plain fact lands; the run below was not scanned strictly, so the clean guardrail fails
        # (tests/test_route_guardrails.py holds each guardrail on its own)
        with open(project.config_path, encoding="utf-8") as f:
            config = json.load(f)
        config["routes"] = {"guardrailed": {"from": "inbox/transcripts", "attributed": False}}
        with open(project.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.makedirs(project.layout.runs, exist_ok=True)
        with open(os.path.join(project.layout.runs, "20261102-1.json"), "w", encoding="utf-8") as f:
            json.dump({"run_id": "20261102-1", "started": "2026-11-02T10:00:00", "inbox": os.path.join(root, "inbox", "transcripts"),
                       "files": [{"file": "standup.md", "outcome": "extracted"}], "completed": False}, f)
        _change(project, by="oto pipeline")
        head = _commit(root, "oto author: the standup")
        shown = route.show(root, base, head)
        assert shown["route"] == route.GUARDRAILED and shown["runs"] == ["20261102-1"], shown
        verdict = route.check(root, base, head, authors=["oto pipeline"], verified=True)
        assert not verdict["ok"] and verdict["route"] == route.REVIEWED and verdict["proposed"] == route.GUARDRAILED
        assert any(r.startswith("guardrail clean:") and "strict-privacy" in r for r in verdict["reasons"]), verdict["reasons"]
        assert route.check(root, base, head, authors=["oto pipeline"], verified=True, approved=True)["ok"], "a person's approval carries it"
        # the same run from the plain inbox: reviewed
        _git(root, "checkout", "-q", base)
        _git(root, "checkout", "-q", "-b", "documents")
        with open(project.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.makedirs(project.layout.runs, exist_ok=True)
        with open(os.path.join(project.layout.runs, "20261102-2.json"), "w", encoding="utf-8") as f:
            json.dump({"run_id": "20261102-2", "started": "2026-11-02T11:00:00", "inbox": os.path.join(root, "inbox"),
                       "files": [{"file": "memo.md", "outcome": "extracted"}], "completed": False}, f)
        _change(project, by="oto pipeline")
        head = _commit(root, "oto author: the memo")
        assert route.show(root, base, head)["route"] == route.REVIEWED


def test_route_needs_a_base_and_says_so():
    with tempfile.TemporaryDirectory() as root:
        _repository(root)
        code, out = _cli("route", "show", "--project", root)
        assert code == 1 and "--base" in out, out


def test_rebase_reapplies_a_confirmed_change_onto_a_moved_main_and_the_record_holds():
    """For the merge queue: a pull request that fell behind re-applies its facts onto the new main
    through the gates; the fingerprint is over facts, so the confirmation still holds."""
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _git(root, "checkout", "-q", "-b", "card")
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "the card")
        _git(root, "checkout", "-q", "main")
        _change(project, by="oto pipeline", node=_node("c.9", summary="landed on main meanwhile", sources=["memo"], source_doc="memo"))
        moved = _commit(root, "another change on main")
        _git(root, "checkout", "-q", "card")
        code, out = _cli("route", "rebase", "--onto", "main", "--project", root)
        assert code == 0, out
        assert "re-applied" in out and "holds" in out, out
        with open(project.graph_path, encoding="utf-8") as f:
            ids = {n["id"] for n in json.load(f)["nodes"]}
        assert {"c.1", "p.1", "c.2", "c.9"} <= ids, ids
        with open(os.path.join(root, "changelog.jsonl"), encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert [e["by"] for e in entries] == ["oto pipeline", "chiheb@cynergis.ai"], "main's ledger, then the pull request's entry on top"
        assert entries[-1]["confirmation"]["by"] == "chiheb@cynergis.ai" and entries[-1]["rebased_onto"] == moved
        rebased = _commit(root, "the card, on the new main")
        shown = route.show(root, moved, rebased)
        assert shown["route"] == route.SESSION, shown["reasons"]
        assert route.check(root, moved, rebased, authors=["chiheb@cynergis.ai"], verified=True)["ok"]


def test_rebase_refuses_a_conflict_and_leaves_the_tree_as_it_was():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository(root)
        _git(root, "checkout", "-q", "-b", "card")
        _change(project, by="chiheb@cynergis.ai", confirm=True)
        _commit(root, "the card")
        _git(root, "checkout", "-q", "main")
        _change(project, by="oto pipeline", node=_node("c.2", summary="the same id, another fact, on main", sources=["memo"], source_doc="memo"))
        _commit(root, "c.2 on main too")
        _git(root, "checkout", "-q", "card")
        before = open(project.graph_path, encoding="utf-8").read()
        code, out = _cli("route", "rebase", "--onto", "main", "--project", root)
        assert code == 1 and "conflict" in out and "c.2" in out, out
        assert open(project.graph_path, encoding="utf-8").read() == before, "nothing written"
        assert _git(root, "status", "--porcelain") == ""
