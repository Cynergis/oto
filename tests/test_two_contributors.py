"""Two people confirm different facts on one graph, each on a branch, as on GitHub (docs/plans/people-and-graphs.md,
phase 0). Numbered assertion ids collided, `oto route rebase` lost one person's audit record, and the steps it printed
left the conflict. Now both merge: distinct ids, both audit records, both facts."""
import json
import os
import re
import subprocess
import tempfile

import pytest

from oto import audit, route
from oto.curate import assertions
from oto.project import Project

from test_curate import _node, _project
from test_route import _cli, _commit, _git

ANNA, BEN = "anna@example.org", "ben@example.org"
AT = "2026-11-04"


def _graph(root):
    with open(os.path.join(root, "graph.json"), encoding="utf-8") as f:
        return json.load(f)


def _jsonl(root, name):
    path = os.path.join(root, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _say(root, by, text):
    code, out = _cli("curate", "assert", "--by", by, "--at", AT, "--text", text, "--project", root)
    assert code == 0, out
    return out.split()[1]


def _confirm(root, by, nid, text):
    """What the curate skill does for a person: their statement, the fact citing it, their confirmation."""
    said = _say(root, by, text)
    project = Project.standard(root)
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "graph.candidate.json"), encoding="utf-8") as f:
        candidate = json.load(f)
    candidate["nodes"].append(_node(nid, summary=text, source_type="human_assertion", sources=[assertions.reference(said)],
                                    source_doc=assertions.reference(said)))
    with open(os.path.join(root, "graph.candidate.json"), "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    code, out = _cli("curate", "apply", "--project", project.data, "--by", by, "--note", text, "--confirm")
    assert code == 0, out
    return said


@pytest.fixture
def team(tmp_path):
    """One graph in a repository: its first commit on main, and an origin everyone clones."""
    first = str(tmp_path / "first")
    os.makedirs(first)
    _project(first)
    _git(first, "init", "-q", "-b", "main")
    _commit(first, "the graph")
    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    _git(first, "remote", "add", "origin", origin)
    _git(first, "push", "-q", "origin", "main")

    class Team(object):
        def __init__(self):
            self.origin, self.tmp = origin, tmp_path

        def clone(self, who):
            root = str(tmp_path / who)
            subprocess.run(["git", "clone", "-q", origin, root], check=True)
            return root

        def branch(self, who, by, nid, text):
            """A contributor's clone, on a branch, with one confirmed fact pushed."""
            root = self.clone(who)
            _git(root, "checkout", "-q", "-b", "add-" + who)
            said = _confirm(root, by, nid, text)
            _commit(root, text)
            _git(root, "push", "-q", "origin", "HEAD")
            return root, said

        def merge(self, who):
            """A pull request merged by someone else, from a clean clone of main. True when git merged it."""
            root = os.path.join(tempfile.mkdtemp(dir=str(tmp_path)), "merger")
            subprocess.run(["git", "clone", "-q", origin, root], check=True)
            done = subprocess.run(["git", "-C", root, "-c", "user.name=lead", "-c", "user.email=lead@example.org", "merge", "--no-ff", "-m", "merge",
                                   "origin/add-" + who], capture_output=True, text=True)
            if done.returncode != 0:
                return False
            _git(root, "push", "-q", "origin", "main")
            return True

        def main(self):
            root = str(tmp_path / "reader")
            if os.path.isdir(root):
                _git(root, "pull", "-q", "--ff-only")
            else:
                subprocess.run(["git", "clone", "-q", origin, root], check=True)
            return root

    return Team()


def _run_steps(root, steps):
    """The steps `oto route rebase` prints, as a person or their skill runs them."""
    for step in steps:
        done = subprocess.run(step, cwd=root, shell=True, capture_output=True, text=True,
                              env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org"))
        assert done.returncode == 0, "%s: %s%s" % (step, done.stdout, done.stderr)


def _rebase(root, onto="origin/main"):
    _git(root, "fetch", "-q", "origin")
    code, out = _cli("route", "rebase", "--onto", onto, "--project", root, "--json")
    return code, json.loads(out)


# ---- the whole of it ----

def test_two_contributors_confirm_different_facts_and_both_merge(team):
    anna, anna_said = team.branch("anna", ANNA, "c.anna", "The Anna claim was filed today.")
    ben, ben_said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    assert anna_said != ben_said, "two people's statements never share an id"

    assert team.merge("anna")
    assert not team.merge("ben"), "the append-only files both changed: git can't merge the second"

    code, result = _rebase(ben)
    assert code == 0 and result["ok"] and result["holds"] is True, result
    _run_steps(ben, result["steps"])
    assert _git(ben, "status", "--porcelain") == "", "the steps leave nothing behind"
    assert _git(ben, "merge-base", "HEAD", "origin/main") == _git(ben, "rev-parse", "origin/main"), "the branch now sits on the new main"
    assert route.check(ben, "origin/main", "HEAD", authors=[BEN], verified=True)["ok"], "and Ben's confirmation still passes the session route"
    assert team.merge("ben"), "and it merges with no conflict"

    main = team.main()
    nodes = {n["id"]: n for n in _graph(main)["nodes"]}
    assert nodes["c.anna"]["sources"] == [assertions.reference(anna_said)] and nodes["c.ben"]["sources"] == [assertions.reference(ben_said)]
    said = {e["id"]: e for e in _jsonl(main, "assertions.jsonl")}
    assert said[anna_said]["by"] == ANNA and said[ben_said]["by"] == BEN and len(said) == 2
    assert [e["by"] for e in _jsonl(main, "changelog.jsonl")][-2:] == [ANNA, BEN]

    project = Project.standard(main)
    records = audit.read(project)
    assert {r["principal"] for r in records} >= {ANNA, BEN}, "neither person's write is lost from the audit log"
    checked = audit.verify(project)
    assert checked["ok"], checked
    moved = [r for r in records if r["principal"] == BEN]
    assert moved and all(r["rebased_from"] and r["rebased_onto"] for r in moved), "a re-chained record says so"
    assert not any("rebased_onto" in r for r in records if r["principal"] == ANNA), "the record already on main stays exactly as it was"


# ---- assertion ids ----

def test_an_assertions_id_comes_from_who_when_and_what(tmp_path):
    project = _project(str(tmp_path))
    one = assertions.record(project, "The claim was filed.", ANNA, AT)
    two = assertions.record(project, "The claim was filed.", BEN, AT)
    three = assertions.record(project, "The claim was filed.", ANNA, "2026-11-05")
    four = assertions.record(project, "The claim was withdrawn.", ANNA, AT)
    assert len({one["id"], two["id"], three["id"], four["id"]}) == 4
    assert re.match(r"^a-[0-9a-f]{12}$", one["id"]), one["id"]


def test_the_same_id_on_any_machine_and_at_any_position_in_the_log(tmp_path):
    os.makedirs(str(tmp_path / "a"))
    os.makedirs(str(tmp_path / "b"))
    here, there = _project(str(tmp_path / "a")), _project(str(tmp_path / "b"))
    assertions.record(there, "Something said earlier.", BEN, AT)
    assert assertions.record(here, "The claim was filed.", ANNA, AT)["id"] == assertions.record(there, "The claim was filed.", ANNA, AT)["id"]


def test_saying_the_same_thing_again_is_one_assertion(tmp_path):
    project = _project(str(tmp_path))
    first = assertions.record(project, "The claim was filed.", ANNA, AT)
    assert assertions.record(project, "The claim was filed.", ANNA, AT)["id"] == first["id"]
    assert len(assertions.read(project)) == 1, "the log has no duplicate to refuse later"


def test_an_old_numbered_id_stays_valid(tmp_path):
    root = str(tmp_path)
    project = _project(root)
    with open(assertions.log_path(project), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "a-0001", "at": AT, "by": ANNA, "text": "Said long ago.", "about": [], "supersedes": []}) + "\n")
    assert "a-0001" in assertions.known_ids(project)
    assert assertions.check_nodes([_node("c.old", source_type="human_assertion", sources=["assertion:a-0001"])], assertions.known_ids(project)) == []
    assert assertions.record(project, "Said today.", ANNA, AT)["id"] != "a-0002", "new ones come from their content"
    assert len(assertions.known_ids(project)) == 2


def _collide(project):
    with open(assertions.log_path(project), "a", encoding="utf-8") as f:
        for by in (ANNA, BEN):
            f.write(json.dumps({"id": "a-0001", "at": AT, "by": by, "text": "What %s said." % by, "about": [], "supersedes": []}) + "\n")


def test_the_gates_refuse_a_log_where_one_id_names_two_statements(tmp_path):
    root = str(tmp_path)
    project = _project(root)
    _collide(project)
    assert assertions.duplicates(assertions.read(project)) == ["a-0001"]
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0, out
    code, out = _cli("curate", "check", "--project", root)
    assert code != 0 and "a-0001" in out, out


def test_the_route_gate_refuses_a_duplicate_a_pull_request_brings_even_when_approved(team):
    root = team.clone("anna")
    _git(root, "checkout", "-q", "-b", "add-anna")
    project = Project.standard(root)
    _collide(project)
    _commit(root, "a merged log")
    result = route.check(root, "origin/main", "HEAD", approved=True)
    assert result["ok"] is False and any("a-0001" in r for r in result["reasons"]), result["reasons"]


def test_the_route_gate_does_not_blame_a_pull_request_for_a_duplicate_already_on_main(team):
    root = team.clone("anna")
    _collide(Project.standard(root))
    _commit(root, "history")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", "add-anna")
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("a change\n")
    _commit(root, "something else")
    assert route.check(root, "origin/main", "HEAD", approved=True)["ok"] is True


# ---- rebase ----

def test_rebase_refuses_two_statements_under_one_old_id(team):
    root = team.clone("old")
    with open(os.path.join(root, "assertions.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "a-0001", "at": AT, "by": ANNA, "text": "What Anna said."}) + "\n")
    _commit(root, "on main, from an older engine")
    _git(root, "push", "-q", "origin", "main")
    ben = team.clone("ben")
    _git(ben, "checkout", "-q", "-b", "add-ben", "HEAD~1")
    with open(os.path.join(ben, "assertions.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "a-0001", "at": AT, "by": BEN, "text": "What Ben said."}) + "\n")
    _commit(ben, "on a branch, from an older engine")
    code, result = _rebase(ben)
    assert code != 0 and not result["ok"] and any("a-0001" in c for c in result["conflicts"]), result
    assert _git(ben, "status", "--porcelain") == "", "nothing written"


def test_rebase_keeps_one_copy_of_a_statement_both_sides_recorded(team):
    text = "The same thing, said once."
    anna = team.clone("anna")
    said = assertions.record(Project.standard(anna), text, ANNA, AT)["id"]
    _commit(anna, "on main")
    _git(anna, "push", "-q", "origin", "main")
    ben = team.clone("ben")
    _git(ben, "checkout", "-q", "-b", "add-ben", "HEAD~1")
    assert assertions.record(Project.standard(ben), text, ANNA, AT)["id"] == said
    _confirm(ben, BEN, "c.ben", "The Ben claim was filed today.")
    _commit(ben, "on a branch")
    code, result = _rebase(ben)
    assert code == 0, result
    assert [e["id"] for e in _jsonl(ben, "assertions.jsonl")].count(said) == 1


def test_the_steps_never_undo_what_main_changed_meanwhile(team):
    ben, _said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    with open(os.path.join(ben, "ben.txt"), "w", encoding="utf-8") as f:
        f.write("the branch's own file\n")
    _commit(ben, "a file of the branch's")

    anna = team.clone("anna")
    with open(os.path.join(anna, "main.txt"), "w", encoding="utf-8") as f:
        f.write("new on main\n")
    with open(os.path.join(anna, "ontology.config.json"), encoding="utf-8") as f:
        vocabulary = json.load(f)
    vocabulary["_note"] = "changed on main"
    with open(os.path.join(anna, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(vocabulary, f)
    _confirm(anna, ANNA, "c.anna", "The Anna claim was filed today.")
    _commit(anna, "main moves")
    _git(anna, "push", "-q", "origin", "main")

    code, result = _rebase(ben)
    assert code == 0, result
    _run_steps(ben, result["steps"])
    assert _git(ben, "status", "--porcelain") == ""
    assert open(os.path.join(ben, "main.txt"), encoding="utf-8").read() == "new on main\n", "a file main added is there"
    with open(os.path.join(ben, "ontology.config.json"), encoding="utf-8") as f:
        assert json.load(f)["_note"] == "changed on main", "and a file main changed keeps main's change"
    assert open(os.path.join(ben, "ben.txt"), encoding="utf-8").read() == "the branch's own file\n", "and the branch's own file stays"
    changed = set(_git(ben, "diff", "--name-only", "origin/main", "HEAD").split())
    assert "ben.txt" in changed and "main.txt" not in changed and "ontology.config.json" not in changed


def test_rebase_stops_at_a_file_both_sides_changed(team):
    ben, _said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    with open(os.path.join(ben, "shared.txt"), "w", encoding="utf-8") as f:
        f.write("ben's\n")
    _commit(ben, "a file")
    anna = team.clone("anna")
    with open(os.path.join(anna, "shared.txt"), "w", encoding="utf-8") as f:
        f.write("anna's\n")
    _commit(anna, "the same file")
    _git(anna, "push", "-q", "origin", "main")
    before = _graph(ben)
    code, result = _rebase(ben)
    assert code != 0 and any("shared.txt" in c for c in result["conflicts"]), result
    assert _graph(ben) == before and _git(ben, "status", "--porcelain") == "", "nothing written"


def test_rebase_waits_for_a_clean_tree(team):
    ben, _said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    anna = team.clone("anna")
    _confirm(anna, ANNA, "c.anna", "The Anna claim was filed today.")
    _commit(anna, "main moves")
    _git(anna, "push", "-q", "origin", "main")
    with open(os.path.join(ben, "ontology.config.json"), "a", encoding="utf-8") as f:
        f.write(" ")
    code, result = _rebase(ben)
    assert code != 0 and any("uncommitted" in c for c in result["conflicts"]), "the steps would throw that work away: %s" % result


def test_the_printed_steps_put_the_change_on_the_new_main(team):
    ben, _said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    anna = team.clone("anna")
    _confirm(anna, ANNA, "c.anna", "The Anna claim was filed today.")
    _commit(anna, "main moves")
    _git(anna, "push", "-q", "origin", "main")
    _git(ben, "fetch", "-q", "origin")
    code, out = _cli("route", "rebase", "--onto", "origin/main", "--project", ben)
    assert code == 0, out
    assert "git reset" in out and "--force-with-lease" in out and _git(ben, "rev-parse", "origin/main") in out, out
    assert "git add -A" not in out, out


def test_a_branch_already_on_main_has_no_steps(team):
    ben, _said = team.branch("ben", BEN, "c.ben", "The Ben claim was filed today.")
    code, result = _rebase(ben)
    assert code == 0 and result["steps"] == [], result


# ---- the file that conflicted on every merge ----

@pytest.mark.parametrize("repository", [False, True])
def test_the_previous_graph_is_kept_for_undo_and_never_tracked(tmp_path, repository):
    root = str(tmp_path / "kb")
    args = ["init", "--name", "KB", "--slug", "kb", "--project", root] + (["--repo"] if repository else [])
    code, out = _cli(*args)
    assert code == 0, out
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "the project")
    with open(os.path.join(root, "graph.previous.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    assert "graph.previous.json" not in _git(root, "status", "--porcelain")
    assert subprocess.run(["git", "-C", root, "check-ignore", "graph.previous.json"], capture_output=True).returncode == 0


def test_no_workflow_commits_the_previous_graph():
    from oto import repo
    for name, text in repo.files("kb", "KB", architecture=True).items():
        assert "git add -A graph.previous.json" not in text and " graph.previous.json " not in text, name


def test_the_curate_skill_gives_the_real_steps():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "skills", "curate", "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    assert "oto route rebase" in text and "--force-with-lease" in text and "steps" in text
