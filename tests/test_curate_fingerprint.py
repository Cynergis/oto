"""The fact-level diff and the confirmation (docs/plans/graph-journeys.md, phase 1).

A change confirmed in a session is bound to what the person saw by a fingerprint over the canonical
fact-level diff: the same whether taken between a live graph and its candidate on a laptop or between
two graph files in CI, as long as the facts are the same. `oto curate apply --confirm` records it in
the ledger entry, with who and when."""
import contextlib
import io
import json
import os
import tempfile

from oto.cli import main
from oto.curate import diff, ledger, session

from test_curate import _graph, _node, _project


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _with_candidate(root, extra_node=None):
    project = _project(root)
    session.start(project)
    candidate = session.candidate(project)
    candidate["nodes"].append(extra_node or _node("c.2", summary="a second claim", sources=["memo"], source_doc="memo"))
    candidate["edges"].append({"from": "c.2", "rel": "filed_by", "to": "p.1"})
    with open(session.candidate_path(project), "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    return project, candidate


def test_the_fingerprint_is_over_facts_not_bytes():
    live = _graph()
    changed = {"nodes": live["nodes"] + [_node("c.2", summary="a second claim")], "edges": live["edges"] + [{"from": "c.2", "rel": "filed_by", "to": "p.1"}]}
    one = diff.fingerprint(diff.canonical(live, changed))
    assert len(one) == 64 and one == diff.fingerprint(diff.canonical(live, changed)), "stable"
    # the same facts in another order, with the keys of a node in another order: the same fingerprint
    reordered = {"nodes": list(reversed(changed["nodes"])), "edges": list(reversed(changed["edges"]))}
    reordered["nodes"] = [dict(reversed(list(n.items()))) for n in reordered["nodes"]]
    assert diff.fingerprint(diff.canonical(live, reordered)) == one
    # the same text with other whitespace in the file: the same fingerprint (the diff is of facts, not bytes)
    assert diff.fingerprint(diff.canonical(json.loads(json.dumps(live, indent=4)), json.loads(json.dumps(changed, separators=(",", ":"))))) == one
    # one fact different: another fingerprint
    other = json.loads(json.dumps(changed))
    other["nodes"][-1]["summary"] = "a third claim"
    assert diff.fingerprint(diff.canonical(live, other)) != one
    # nothing changed: a fingerprint still, of the empty diff, and it says so
    empty = diff.canonical(live, live)
    assert empty["nodes_added"] == [] and empty["edges_added"] == [] and diff.fingerprint(empty)


def test_the_canonical_diff_carries_the_facts_added_the_ids_removed_and_the_fields_changed():
    live = _graph()
    changed = json.loads(json.dumps(live))
    changed["nodes"] = [n for n in changed["nodes"] if n["id"] != "p.1"] + [_node("c.2")]
    changed["nodes"][0]["summary"] = "renamed"
    changed["edges"] = [{"from": "c.2", "rel": "filed_by", "to": "c.1"}]
    canon = diff.canonical(live, changed)
    assert [n["id"] for n in canon["nodes_added"]] == ["c.2"] and canon["nodes_added"][0]["summary"] == "a summary"
    assert canon["nodes_removed"] == ["p.1"]
    assert canon["nodes_changed"] == [{"id": "c.1", "fields": ["summary"], "node": canon["nodes_changed"][0]["node"]}]
    assert canon["nodes_changed"][0]["node"]["summary"] == "renamed"
    assert canon["edges_added"] == [["c.2", "filed_by", "c.1"]] and canon["edges_removed"] == [["c.1", "filed_by", "p.1"]]
    assert json.dumps(canon, sort_keys=True), "plain JSON"


def test_diff_json_prints_the_canonical_diff_and_its_fingerprint_from_a_candidate_or_two_graph_files():
    with tempfile.TemporaryDirectory() as root:
        project, candidate = _with_candidate(root)
        code, out = _cli("curate", "diff", "--json", "--project", root)
        assert code == 0, out
        printed = json.loads(out)
        expected = diff.fingerprint(diff.canonical(session.live(project), candidate))
        assert printed["fingerprint"] == expected and [n["id"] for n in printed["nodes_added"]] == ["c.2"]
        # the same diff between two graph files, no candidate needed: what CI does from base and head
        base, head = os.path.join(root, "base.json"), os.path.join(root, "head.json")
        with open(base, "w", encoding="utf-8") as f:
            json.dump(session.live(project), f, indent=2)
        with open(head, "w", encoding="utf-8") as f:
            json.dump(candidate, f, separators=(",", ":"))
        session.abort(project)
        code, out = _cli("curate", "diff", "--from-graph", base, "--to-graph", head, "--json", "--project", root)
        assert code == 0 and json.loads(out)["fingerprint"] == expected, out
        code, out = _cli("curate", "diff", "--from-graph", base, "--to-graph", head, "--project", root)
        assert code == 0 and "nodes: +1" in out and expected[:12] in out, "the plain form says the fingerprint too: " + out
        code, out = _cli("curate", "diff", "--from-graph", base, "--project", root)
        assert code == 1 and "--to-graph" in out, out
        code, out = _cli("curate", "diff", "--json", "--project", root)
        assert code == 1 and "no candidate" in out, out


def test_apply_confirm_records_who_confirmed_what_in_the_ledger():
    with tempfile.TemporaryDirectory() as root:
        project, candidate = _with_candidate(root)
        expected = diff.fingerprint(diff.canonical(session.live(project), candidate))
        code, out = _cli("curate", "apply", "--confirm", "--note", "the card", "--project", root)
        assert code == 1 and "--by" in out and "confirm" in out, "a confirmation names the person: " + out
        assert session.exists(project), "nothing applied"
        code, out = _cli("curate", "apply", "--confirm", "--by", "chiheb@cynergis.ai", "--note", "the card", "--project", root)
        assert code == 0, out
        assert "confirmed by chiheb@cynergis.ai" in out and expected[:12] in out, out
        [record] = ledger.read(project)
        confirmation = record["confirmation"]
        assert confirmation["by"] == "chiheb@cynergis.ai" and confirmation["fingerprint"] == expected and confirmation["shown"] == "diff"
        assert confirmation["at"][:4].isdigit() and "T" in confirmation["at"]
        assert record["by"] == "chiheb@cynergis.ai"
        code, out = _cli("curate", "log", "--project", root)
        assert code == 0 and "confirmed by chiheb@cynergis.ai" in out and expected[:12] in out, out
        # the fingerprint CI recomputes from the previous and the live graph is the one confirmed
        code, out = _cli("curate", "diff", "--from-graph", session.previous_path(project), "--to-graph", project.graph_path, "--json", "--project", root)
        assert code == 0 and json.loads(out)["fingerprint"] == expected


def test_apply_without_confirm_records_no_confirmation():
    with tempfile.TemporaryDirectory() as root:
        project, _candidate = _with_candidate(root)
        code, out = _cli("curate", "apply", "--by", "oto pipeline", "--note", "drafted from documents", "--project", root)
        assert code == 0, out
        [record] = ledger.read(project)
        assert "confirmation" not in record and "confirmed" not in out
