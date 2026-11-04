"""Permissions on a graph are a file, reviewed like code (docs/plans/people-and-graphs.md, phase 3). `.github/oto-access.json` says who holds
each role, `oto repo access --apply` sets GitHub to match, `--check` says when it drifted, and the gate counts only the reviewers it names at the
base. A verified commit doesn't need a key on the person's computer, and promotion is a pull request on a file stewards own."""
import json
import os
import re
import subprocess
import sys

import pytest

from oto import access, deploy, repo, route, sandbox
from oto.project import Project, ProjectError
from oto.scaffold import init

from test_gate_and_secrets import _review, _script, _step
from test_route import _cli, _commit, _git

FILE = {"stewards": ["team:acme/board-stewards", "dana"], "reviewers": ["team:acme/board-reviewers", "rita"],
        "contributors": ["team:acme/board-team", "anna"], "readers": ["team:acme/readers", "someone"], "store": "acme/board-store"}


# ---- the file ----

def test_a_new_repository_project_starts_with_an_empty_access_file(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    found = access.load(root)
    assert {found[role] and None or found[role] == [] for role in access.ROLES} == {True}
    assert access.problems(found) == ["no steward: name at least one, or nobody can change this file or approve a promotion"]


def test_a_good_file_has_no_problems():
    assert access.problems(FILE) == []


@pytest.mark.parametrize("change, says", [
    (lambda f: f.update(stewards="dana"), "stewards"),
    (lambda f: f.update(reviewers=["team:acme"]), "team:acme"),
    (lambda f: f.update(contributors=["not a login"]), "not a login"),
    (lambda f: f.update(mystery=["x"]), "mystery"),
    (lambda f: f.update(stewards=[]), "no steward"),
    (lambda f: f.update(store="not-a-repo"), "store"),
])
def test_every_mistake_in_the_file_is_named(change, says):
    found = json.loads(json.dumps(FILE))
    change(found)
    assert any(says in p for p in access.problems(found)), access.problems(found)


def test_what_each_role_gets_on_each_repository():
    wanted = access.wanted(FILE)
    assert wanted["users"] == {"dana": "admin", "rita": "push", "anna": "push"}, "readers get nothing on the repository: they hold a Neo4j login"
    assert wanted["teams"] == {"acme/board-stewards": "admin", "acme/board-reviewers": "push", "acme/board-team": "push"}
    store = access.wanted(FILE, store=True)
    assert store["users"] == {"dana": "admin", "rita": "pull", "anna": "pull"}, "only the deploy workflow writes to the store"
    both = dict(FILE, reviewers=["dana"])
    assert access.wanted(both)["users"]["dana"] == "admin", "someone in two roles gets the higher"


def test_the_code_owners_are_the_stewards():
    text = access.code_owners_text(FILE)
    for line in ("/.github/", "/oto.lock.json", "/oto.promote.json"):
        assert re.search(r"^%s\s+@acme/board-stewards @dana$" % re.escape(line), text, re.M), text


# ---- applying it, and the drift ----

FAKE_GH = r'''
import json, os, sys
args = sys.argv[1:]
path = os.environ["FAKE_GH_STATE"]
state = json.load(open(path))
state["calls"].append(args)
method = args[args.index("--method") + 1] if "--method" in args else "GET"
target = next((a for a in args[1:] if a.startswith(("repos/", "orgs/")) or a == "user"), "")
target = target.split("?")[0]
def answer(payload="", code=0):
    json.dump(state, open(path, "w"))
    sys.stdout.write(json.dumps(payload) if not isinstance(payload, str) else payload)
    sys.exit(code)
def field(name):
    for i, a in enumerate(args):
        if a == "-f" and args[i + 1].startswith(name + "="):
            return args[i + 1].split("=", 1)[1]
if target == "user":
    answer({"login": state.get("me", "dana")})
parts = target.split("/")
if parts[0] == "orgs" and len(parts) == 2:
    answer({"default_repository_permission": state.get("base", "none")})
if parts[0] == "orgs" and "repos" in parts:
    slug = "%s/%s" % (parts[1], parts[3])
    repo_name = "/".join(parts[parts.index("repos") + 1:])
    teams = state["repos"].setdefault(repo_name, {"users": {}, "teams": {}})["teams"]
    if method == "PUT":
        teams[slug] = field("permission")
    elif method == "DELETE":
        teams.pop(slug, None)
    answer("")
if parts[0] == "repos":
    repo_name = "/".join(parts[1:3])
    held = state["repos"].setdefault(repo_name, {"users": {}, "teams": {}})
    if parts[3:] == ["collaborators"]:
        answer([{"login": k, "role_name": {"pull": "read", "push": "write"}.get(v, v)} for k, v in sorted(held["users"].items())])
    if parts[3:] == ["teams"]:
        answer([{"slug": k.split("/")[1], "organization": {"login": k.split("/")[0]}, "permission": v} for k, v in sorted(held["teams"].items())])
    if parts[3] == "collaborators":
        if method == "PUT":
            held["users"][parts[4]] = field("permission")
        elif method == "DELETE":
            held["users"].pop(parts[4], None)
        answer("")
print("fake gh: not expected: %s" % args, file=sys.stderr)
json.dump(state, open(path, "w"))
sys.exit(2)
'''


@pytest.fixture
def github(tmp_path, monkeypatch):
    state_file = tmp_path / "gh.json"
    state_file.write_text(json.dumps({"calls": [], "repos": {}, "base": "none"}))
    bin_gh = tmp_path / "gh"
    _script(str(bin_gh), "#!%s\n%s" % (sys.executable, FAKE_GH))
    monkeypatch.setenv("OTO_GH", str(bin_gh))
    monkeypatch.setenv("FAKE_GH_STATE", str(state_file))

    class GitHub(object):
        def read(self):
            return json.loads(state_file.read_text())

        def write(self, **changes):
            state = self.read()
            state.update(changes)
            state_file.write_text(json.dumps(state))
    return GitHub()


@pytest.fixture
def graph(tmp_path):
    root = str(tmp_path / "board")
    init(root, slug="board", name="Board", repo=True)
    access.write(root, FILE)
    return root


def test_apply_sets_both_repositories_to_match_and_removes_who_is_gone(graph, github):
    github.write(repos={"acme/board": {"users": {"dana": "admin", "former": "push"}, "teams": {"acme/old-team": "push"}}})
    code, out = _cli("repo", "access", "--apply", "--repo", "acme/board", "--project", graph)
    assert code == 0, out
    held = github.read()["repos"]
    assert held["acme/board"]["users"] == {"dana": "admin", "rita": "push", "anna": "push"}, "the former contributor is gone"
    assert held["acme/board"]["teams"] == {"acme/board-stewards": "admin", "acme/board-reviewers": "push", "acme/board-team": "push"}
    assert held["acme/board-store"]["users"] == {"dana": "admin", "rita": "pull", "anna": "pull"}
    assert "former" in out and "old-team" in out, "it says who lost access"


def test_apply_never_removes_the_person_running_it(graph, github):
    github.write(me="platform-owner", repos={"acme/board": {"users": {"platform-owner": "admin"}, "teams": {}}})
    code, out = _cli("repo", "access", "--apply", "--repo", "acme/board", "--project", graph)
    assert code == 0, out
    assert "platform-owner" in github.read()["repos"]["acme/board"]["users"]
    assert "platform-owner" in out and "kept" in out, out


def test_apply_refuses_a_file_with_problems_and_changes_nothing(graph, github):
    access.write(graph, dict(FILE, stewards=[]))
    code, out = _cli("repo", "access", "--apply", "--repo", "acme/board", "--project", graph)
    assert code != 0 and "no steward" in out, out
    assert not [c for c in github.read()["calls"] if "--method" in c]


def _sync(graph, github):
    assert _cli("repo", "access", "--apply", "--repo", "acme/board", "--project", graph)[0] == 0
    assert _cli("repo", "access", "--owners", "--project", graph)[0] == 0


def test_check_finds_nothing_after_apply(graph, github):
    _sync(graph, github)
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code == 0 and "matches" in out, out


def test_removing_a_person_is_confirmed_by_the_drift_check(graph, github):
    _sync(graph, github)
    access.write(graph, dict(FILE, contributors=["team:acme/board-team"]))
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code != 0 and "anna" in out and "still" in out, "they still have access until the file is applied: %s" % out
    assert _cli("repo", "access", "--apply", "--repo", "acme/board", "--project", graph)[0] == 0
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code == 0 and "anna" not in out, out


def test_check_finds_someone_added_by_hand_and_a_wrong_permission(graph, github):
    _sync(graph, github)
    held = github.read()["repos"]
    held["acme/board"]["users"]["intruder"] = "push"
    held["acme/board"]["users"]["anna"] = "admin"
    github.write(repos=held)
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code != 0 and "intruder" in out and "anna" in out, out


def test_check_says_when_the_organisations_base_permission_defeats_the_file(graph, github):
    _sync(graph, github)
    github.write(base="read")
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code != 0 and "base permission" in out, "every member can read every repository, documents included: %s" % out


def test_check_says_when_the_code_owners_arent_the_stewards(graph, github):
    _sync(graph, github)
    access.write(graph, dict(FILE, stewards=["dana"]))
    code, out = _cli("repo", "access", "--check", "--repo", "acme/board", "--project", graph)
    assert code != 0 and "CODEOWNERS" in out and "--owners" in out, out


def test_the_workflow_applies_on_a_change_and_checks_on_a_schedule():
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-access.yml")]
    assert "oto repo access --apply" in text and "oto repo access --check" in text and "schedule:" in text
    assert "environment: oto-main" in text and "secrets.OTO_ACCESS_TOKEN" in text


# ---- the gate names its reviewers at the base ----

FAKE_ROUTE_GH = r'''
import json, os, sys
args = sys.argv[1:]
facts = json.load(open(os.environ["FAKE_GH_FACTS"]))
if args[:2] == ["pr", "view"]:
    print(" ".join(facts["authors"]))
elif args[0] == "api" and args[1].endswith("/commits"):
    print("false")
elif args[0] == "api" and "/reviews" in args[1]:
    print(json.dumps(facts["reviews"]))
elif args[0] == "api" and "/collaborators/" in args[1]:
    print(facts["permissions"].get(args[1].split("/collaborators/")[1].split("/")[0], "none"))
elif args[0] == "api" and "/memberships/" in args[1]:
    team = "/".join(args[1].split("/")[1:2] + args[1].split("/")[3:4])
    login = args[1].split("/memberships/")[1]
    if login in facts.get("teams", {}).get(team, []) and os.environ.get("GH_TOKEN") == "a-teams-token":
        print("active")
    else:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
else:
    print("fake gh: not expected: %s" % args, file=sys.stderr)
    sys.exit(2)
'''


@pytest.fixture
def gate(tmp_path):
    """The gate's own step, with an access file on main and `gh` faked."""
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    access.write(root, {"stewards": ["sam"], "reviewers": ["dana", "team:acme/reviewers"], "contributors": [], "readers": []})
    _git(root, "init", "-q", "-b", "main")
    head = _commit(root, "the project")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(str(bin_dir / "gh"), "#!%s\n%s" % (sys.executable, FAKE_ROUTE_GH))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _script(str(bin_dir / "oto"), '#!/bin/sh\nPYTHONPATH="%s" exec "%s" -m oto.cli "$@"\n' % (here, sys.executable))
    text = repo.files("kb", "KB")[os.path.join(".github", "workflows", "oto-route.yml")]
    script = _step(text, "What GitHub knows about the pull request").replace("${{ github.repository }}", "acme/board")

    def run(reviews, permissions, teams=None, authors=("anna",), teams_token="a-teams-token"):
        facts = tmp_path / "facts.json"
        facts.write_text(json.dumps({"authors": list(authors), "reviews": reviews, "permissions": permissions, "teams": teams or {}}))
        output = tmp_path / "output"
        output.write_text("")
        done = subprocess.run(["bash", "-e", "-c", script], cwd=root, capture_output=True, text=True,
                              env=dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ["PATH"]), PR="7", BASE="main", FAKE_GH_FACTS=str(facts), GITHUB_OUTPUT=str(output),
                                       GH_TOKEN="a-repo-token", OTO_TEAMS_TOKEN=teams_token))
        assert done.returncode == 0, done.stdout + done.stderr
        return output.read_text()
    return run, head


def test_a_reviewer_the_access_file_names_counts(gate):
    run, head = gate
    assert "--approved" in run([_review("dana", commit=head)], {"dana": "write"})


def test_a_steward_counts_as_a_reviewer(gate):
    run, head = gate
    assert "--approved" in run([_review("sam", commit=head)], {"sam": "admin"})


def test_someone_with_write_the_file_doesnt_name_does_not_count(gate):
    run, head = gate
    assert "--approved" not in run([_review("wes", commit=head)], {"wes": "write"})


def test_a_member_of_a_team_the_file_names_counts(gate):
    run, head = gate
    assert "--approved" in run([_review("tina", commit=head)], {"tina": "write"}, teams={"acme/reviewers": ["tina"]})


def test_with_no_token_for_teams_the_gate_fails_closed(gate):
    run, head = gate
    assert "--approved" not in run([_review("tina", commit=head)], {"tina": "write"}, teams={"acme/reviewers": ["tina"]}, teams_token="")


def test_someone_named_who_can_only_read_does_not_count(gate):
    run, head = gate
    assert "--approved" not in run([_review("dana", commit=head)], {"dana": "read"})


def test_a_pull_request_cannot_name_its_own_reviewer(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    access.write(root, {"stewards": ["sam"], "reviewers": ["dana"], "contributors": [], "readers": []})
    _git(root, "init", "-q", "-b", "main")
    base = _commit(root, "the project")
    _git(root, "checkout", "-q", "-b", "mine")
    access.write(root, {"stewards": ["sam"], "reviewers": ["dana", "my-friend"], "contributors": [], "readers": []})
    head = _commit(root, "name my friend")
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps([_review("my-friend", commit=head)]))
    code, out = _cli("route", "approvers", "--reviews", str(reviews), "--base", base, "--project", root)
    assert code == 0 and "my-friend" not in out, "the base's file decides: %s" % out


def test_with_no_access_file_at_the_base_the_gate_asks_only_for_write(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    _git(root, "init", "-q", "-b", "main")
    head = _commit(root, "the project")
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps([_review("dana", commit=head)]))
    code, out = _cli("route", "approvers", "--reviews", str(reviews), "--base", head, "--project", root)
    assert code == 0 and out.split() == ["dana"], out


def test_route_check_says_who_may_approve(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    access.write(root, {"stewards": ["sam"], "reviewers": ["dana"], "contributors": [], "readers": []})
    _git(root, "init", "-q", "-b", "main")
    base = _commit(root, "the project")
    _git(root, "checkout", "-q", "-b", "mine")
    with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    _commit(root, "a change")
    result = route.check(root, base, "HEAD")
    assert any("dana" in r and "sam" in r for r in result["reasons"]), result["reasons"]


# ---- a verified commit, with no key on the computer ----

FAKE_COMMIT_GH = r'''
import json, os, sys, subprocess
args = sys.argv[1:]
log = os.environ["FAKE_GH_LOG"]
body = None
if "--input" in args:
    body = json.load(open(args[args.index("--input") + 1]))
open(log, "a").write(json.dumps({"args": args, "body": body}) + "\n")
if args[:2] == ["api", "graphql"]:
    origin = os.environ["FAKE_ORIGIN"]
    change = body["variables"]["input"]
    branch = change["branch"]["branchName"]
    work = os.environ["FAKE_WORK"]
    env = dict(os.environ, GIT_AUTHOR_NAME="github", GIT_AUTHOR_EMAIL="noreply@github.com", GIT_COMMITTER_NAME="github", GIT_COMMITTER_EMAIL="noreply@github.com")
    subprocess.run(["git", "-C", work, "fetch", "-q", origin, branch], check=True)
    subprocess.run(["git", "-C", work, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    assert subprocess.run(["git", "-C", work, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() == change["expectedHeadOid"]
    import base64
    for item in change["fileChanges"].get("additions") or []:
        target = os.path.join(work, item["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "wb").write(base64.b64decode(item["contents"]))
    for item in change["fileChanges"].get("deletions") or []:
        os.remove(os.path.join(work, item["path"]))
    subprocess.run(["git", "-C", work, "add", "-A"], check=True)
    subprocess.run(["git", "-C", work, "commit", "-q", "-m", change["message"]["headline"]], check=True, env=env)
    subprocess.run(["git", "-C", work, "push", "-q", origin, "HEAD:refs/heads/%s" % branch], check=True)
    oid = subprocess.run(["git", "-C", work, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(json.dumps({"data": {"createCommitOnBranch": {"commit": {"oid": oid, "url": "https://github.com/x/y/commit/" + oid}}}}))
    sys.exit(0)
print("fake gh: not expected: %s" % args, file=sys.stderr)
sys.exit(2)
'''


@pytest.fixture
def signing(tmp_path, monkeypatch):
    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    root = str(tmp_path / "kb")
    os.makedirs(root)
    with open(os.path.join(root, "kept.txt"), "w", encoding="utf-8") as f:
        f.write("kept\n")
    with open(os.path.join(root, "gone.txt"), "w", encoding="utf-8") as f:
        f.write("gone\n")
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "first")
    _git(root, "remote", "add", "origin", origin)
    _git(root, "push", "-q", "origin", "main")
    work = str(tmp_path / "github-side")
    subprocess.run(["git", "clone", "-q", origin, work], check=True)
    log = tmp_path / "gh.log"
    bin_gh = tmp_path / "gh"
    _script(str(bin_gh), "#!%s\n%s" % (sys.executable, FAKE_COMMIT_GH))
    monkeypatch.setenv("OTO_GH", str(bin_gh))
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_ORIGIN", origin)
    monkeypatch.setenv("FAKE_WORK", work)

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return root, calls


def _stage(root):
    _git(root, "checkout", "-q", "-b", "add-fact")
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        f.write('{"nodes": []}\n')
    os.makedirs(os.path.join(root, "sub"))
    with open(os.path.join(root, "sub", "new.txt"), "w", encoding="utf-8") as f:
        f.write("new\n")
    os.remove(os.path.join(root, "gone.txt"))
    _git(root, "add", "-A")


def test_commit_through_github_carries_the_staged_change_and_leaves_the_tree_clean(signing):
    root, calls = signing
    _stage(root)
    head = _git(root, "rev-parse", "HEAD")
    code, out = _cli("repo", "commit", "--message", "A new fact", "--repo", "acme/board", "--project", root)
    assert code == 0, out
    assert _git(root, "status", "--porcelain") == "", "the local branch now holds that commit"
    assert _git(root, "rev-parse", "HEAD~1") == head and _git(root, "log", "-1", "--format=%s") == "A new fact"
    assert "graph.json" in _git(root, "show", "--name-only", "--format=", "HEAD") and "gone.txt" in _git(root, "show", "--name-only", "--format=", "HEAD")
    change = [c for c in calls() if c["args"][:2] == ["api", "graphql"]][0]["body"]["variables"]["input"]
    assert change["branch"] == {"repositoryNameWithOwner": "acme/board", "branchName": "add-fact"} and change["expectedHeadOid"] == head
    assert {a["path"] for a in change["fileChanges"]["additions"]} == {"graph.json", "sub/new.txt"}
    assert change["fileChanges"]["deletions"] == [{"path": "gone.txt"}]


def test_commit_refuses_the_default_branch_and_nothing_staged(signing):
    root, _calls = signing
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    _git(root, "add", "-A")
    code, out = _cli("repo", "commit", "--message", "m", "--repo", "acme/board", "--project", root)
    assert code != 0 and "main" in out, out
    _git(root, "checkout", "-q", "-b", "other")
    _git(root, "reset", "-q", "--hard")
    code, out = _cli("repo", "commit", "--message", "m", "--repo", "acme/board", "--project", root)
    assert code != 0 and "nothing" in out.lower(), out


def test_commit_refuses_when_the_branch_moved_on_github(signing):
    root, _calls = signing
    _stage(root)
    _git(root, "push", "-q", "origin", "HEAD")
    other = root + "-other"
    subprocess.run(["git", "clone", "-q", "-b", "add-fact", os.environ["FAKE_ORIGIN"], other], check=True)
    _commit(other, "moved on github")
    _git(other, "push", "-q", "origin", "HEAD")
    code, out = _cli("repo", "commit", "--message", "m", "--repo", "acme/board", "--project", root)
    assert code != 0 and "moved" in out, out


def test_replacing_moves_the_branch_straight_to_the_new_commit_and_cleans_up(signing):
    root, calls = signing
    origin = os.environ["FAKE_ORIGIN"]
    _git(root, "checkout", "-q", "-b", "add-fact")
    with open(os.path.join(root, "first.txt"), "w", encoding="utf-8") as f:
        f.write("on the branch\n")
    old = _commit(root, "the old commit")
    _git(root, "push", "-q", "origin", "HEAD")
    _git(root, "reset", "-q", "main")
    os.remove(os.path.join(root, "first.txt"))
    with open(os.path.join(root, "new.txt"), "w", encoding="utf-8") as f:
        f.write("on the new main\n")
    _git(root, "add", "-A")
    code, out = _cli("repo", "commit", "--replace", "--message", "Rebased", "--repo", "acme/board", "--project", root)
    assert code == 0, out
    heads = subprocess.run(["git", "ls-remote", "--heads", origin], capture_output=True, text=True).stdout
    assert "oto/commit-" not in heads, "the temporary branch is gone"
    theirs = [line.split()[0] for line in heads.splitlines() if line.endswith("refs/heads/add-fact")][0]
    assert theirs == _git(root, "rev-parse", "HEAD") and theirs != old
    assert _git(root, "status", "--porcelain") == ""
    assert _git(root, "rev-parse", "HEAD~1") == _git(root, "rev-parse", "main")
    change = [c for c in calls() if c["args"][:2] == ["api", "graphql"]][0]["body"]["variables"]["input"]
    assert change["branch"]["branchName"].startswith("oto/commit-"), "the branch itself never points at main"


def test_a_rebase_can_end_in_a_verified_commit(tmp_path):
    from test_curate import _node, _project
    from test_route import _change
    root = str(tmp_path / "kb")
    os.makedirs(root)
    project = _project(root)
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "the project")
    _git(root, "checkout", "-q", "-b", "card")
    _change(project, by="anna", confirm=True)
    _commit(root, "the card")
    _git(root, "checkout", "-q", "main")
    _change(project, by="oto pipeline", node=_node("c.9", summary="landed on main", sources=["memo"], source_doc="memo"))
    _commit(root, "main moves")
    _git(root, "checkout", "-q", "card")
    result = route.rebase(root, "main", verified=True)
    assert result["ok"], result
    joined = " ; ".join(result["steps"])
    assert "oto repo commit --replace" in joined and "git commit" not in joined, joined
    assert "git push" not in joined, "pointing the branch at main, even for a moment, closes its pull request for good: real GitHub did this"


# ---- promotion by pull request ----

def _config(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    project = Project.standard(root)
    deploy.write(project, deploy.starter("acme/kb", str(tmp_path / "store.git"), "kb"))
    return root, project


def test_the_promotion_file_is_validated(tmp_path):
    root, project = _config(tmp_path)
    for wanted, says in (({"nowhere": "a" * 40}, "nowhere"), ({"dev": "a" * 40}, "dev"), ({"test": "not a commit"}, "not a commit")):
        with open(os.path.join(root, deploy.PROMOTE_FILE), "w", encoding="utf-8") as f:
            json.dump(wanted, f)
        code, out = _cli("deploy", "check", "--project", root)
        assert code != 0 and says in out, out


def test_promote_moves_what_the_file_names_in_order_and_skips_what_is_held(tmp_path, monkeypatch):
    root, project = _config(tmp_path)
    with open(os.path.join(root, deploy.PROMOTE_FILE), "w", encoding="utf-8") as f:
        json.dump({"test": "a" * 40, "prod": "b" * 40}, f)
    moved = []
    monkeypatch.setattr(deploy, "status", lambda p, token=None: {"dev": {"source": "acme/kb@" + "b" * 40}, "test": {"source": "acme/kb@" + "a" * 40}, "prod": None})
    monkeypatch.setattr(deploy, "promote", lambda p, env, commit, by=None, kind="person", token=None: moved.append((env, commit, by, kind)) or {"environment": env, "from": "x", "source": commit, "sha256": "s"})
    code, out = _cli("deploy", "promote", "--by", "sam", "--project", root)
    assert code == 0, out
    assert moved == [("prod", "b" * 40, "sam", "pull-request")], "test already holds its commit"


def test_promote_needs_who_approved(tmp_path):
    root, project = _config(tmp_path)
    with open(os.path.join(root, deploy.PROMOTE_FILE), "w", encoding="utf-8") as f:
        json.dump({"test": "a" * 40}, f)
    code, out = _cli("deploy", "promote", "--project", root)
    assert code != 0 and "--by" in out, out


def test_promote_with_no_file_says_so(tmp_path):
    root, project = _config(tmp_path)
    code, out = _cli("deploy", "promote", "--by", "sam", "--project", root)
    assert code == 0 and deploy.PROMOTE_FILE in out, out


def test_the_promote_workflow_runs_on_the_file_from_the_environment_only_main_deploys_from():
    files = repo.files("acme", "Acme")
    text = files[os.path.join(".github", "workflows", "oto-promote.yml")]
    assert "oto.promote.json" in text and "environment: oto-main" in text and "oto deploy promote" in text
    assert "/reviews" in text, "the approver is whoever approved the pull request"


def test_a_merge_no_longer_promotes_on_its_own_on_a_plan_with_no_required_reviewers():
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-deploy.yml")]
    assert text.count("vars.OTO_PROMOTE_ON_MERGE == 'true'") == 2, "Team has no required reviewers on an environment, so these jobs would run unapproved"


def test_the_stewards_own_the_promotion_file():
    assert "/oto.promote.json" in repo.OWNED


# ---- the store, with the graph ----

def test_making_a_graph_names_its_steward_and_store(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    assert sandbox._name_the_creator(root, "acme/kb", "dana", "https://github.com/acme/kb-store.git")
    found = access.load(root)
    assert found["stewards"] == ["dana"] and found["store"] == "acme/kb-store"
    assert not sandbox._name_the_creator(root, "acme/kb", "someone-else", None), "a steward already named stays"
    assert access.load(root)["stewards"] == ["dana"]


def test_a_refusal_says_githubs_reason_not_just_the_status():
    body = json.dumps({"message": "Validation Failed", "errors": [{"code": "custom", "message": "seat_limit You must purchase at least one more seat to add this user as a collaborator."}]})
    assert "at least one more seat" in repo.gh_reason(body, "gh: Validation Failed (HTTP 422)")
    assert repo.gh_reason("", "gh: Not Found (HTTP 404)") == "gh: Not Found (HTTP 404)"

