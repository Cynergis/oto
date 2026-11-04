"""What a reviewer's approval is worth, what a branch's workflow can reach, and what the branch rules ask of a Team plan
(docs/plans/people-and-graphs.md, phase 0). GitHub lets anyone with read access review, gives repository secrets to
workflows on any branch, and refuses a merge queue on a private repository on Team."""
import json
import os
import re
import stat
import subprocess
import sys

import pytest

from oto import deploy, repo, route
from oto.scaffold import init

from test_deploy import GOOD
from test_route import _cli, _commit, _git

HEAD, OLD = "a" * 40, "b" * 40


def _review(login, state="APPROVED", commit=HEAD):
    return {"user": {"login": login}, "state": state, "commit_id": commit}


# ---- whose approval counts ----

def test_an_approval_of_the_head_commit_counts():
    assert route.qualified_reviewers([_review("dana")], HEAD) == ["dana"]


def test_an_approval_of_an_earlier_commit_does_not():
    assert route.qualified_reviewers([_review("dana", commit=OLD)], HEAD) == [], "what the reviewer read isn't what would merge"


def test_the_author_cannot_approve_their_own_change():
    assert route.qualified_reviewers([_review("Dana")], HEAD, authors=["dana", "dana@example.org"]) == []


def test_only_a_persons_latest_decision_stands():
    assert route.qualified_reviewers([_review("dana"), _review("dana", "CHANGES_REQUESTED")], HEAD) == []
    assert route.qualified_reviewers([_review("dana", "CHANGES_REQUESTED"), _review("dana")], HEAD) == ["dana"]
    assert route.qualified_reviewers([_review("dana"), _review("dana", "DISMISSED")], HEAD) == []


def test_a_comment_after_an_approval_leaves_it_standing():
    assert route.qualified_reviewers([_review("dana"), _review("dana", "COMMENTED")], HEAD) == ["dana"]


def test_a_review_with_no_user_is_ignored():
    assert route.qualified_reviewers([{"state": "APPROVED", "commit_id": HEAD, "user": None}, "nonsense"], HEAD) == []


# ---- the gate's step, run as the workflow runs it ----

FAKE_GH = r'''
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
    login = args[1].split("/collaborators/")[1].split("/")[0]
    if login not in facts["permissions"]:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    print(facts["permissions"][login])
else:
    print("fake gh: not expected: %s" % args, file=sys.stderr)
    sys.exit(2)
'''


def _step(text, name):
    """The shell of one step of a generated workflow."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: %s" % name)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    body = []
    for line in lines[run + 1:]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body)


def _script(path, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


@pytest.fixture
def workflow(tmp_path):
    """The gate's own step in a checkout, with `gh` faked and the real engine as `oto`."""
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB", repo=True)
    _git(root, "init", "-q", "-b", "main")
    head = _commit(root, "the project")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(str(bin_dir / "gh"), "#!%s\n%s" % (sys.executable, FAKE_GH))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _script(str(bin_dir / "oto"), '#!/bin/sh\nPYTHONPATH="%s" exec "%s" -m oto.cli "$@"\n' % (here, sys.executable))
    text = repo.files("kb", "KB")[os.path.join(".github", "workflows", "oto-route.yml")]
    script = _step(text, "What GitHub knows about the pull request").replace("${{ github.repository }}", "acme/board")

    def run(reviews, permissions, authors=("anna",)):
        facts = tmp_path / "facts.json"
        facts.write_text(json.dumps({"authors": list(authors), "reviews": reviews, "permissions": permissions}))
        output = tmp_path / "output"
        output.write_text("")
        done = subprocess.run(["bash", "-e", "-c", script], cwd=root, capture_output=True, text=True,
                              env=dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ["PATH"]), PR="7", BASE="main", FAKE_GH_FACTS=str(facts), GITHUB_OUTPUT=str(output)))
        assert done.returncode == 0, done.stdout + done.stderr
        return output.read_text()
    return run, head


def test_the_workflow_passes_an_approval_from_someone_who_may_write(workflow):
    run, head = workflow
    assert "--approved" in run([_review("dana", commit=head)], {"dana": "write"})
    assert "--approved" in run([_review("dana", commit=head)], {"dana": "admin"})


@pytest.mark.parametrize("permission", ["read", "none"])
def test_the_workflow_does_not_pass_an_approval_from_someone_who_only_reads(workflow, permission):
    run, head = workflow
    assert "--approved" not in run([_review("rita", commit=head)], {"rita": permission})


def test_the_workflow_does_not_pass_an_approval_from_someone_it_cannot_look_up(workflow):
    run, head = workflow
    assert "--approved" not in run([_review("stranger", commit=head)], {}), "a failed lookup is not a yes, and doesn't fail the step"


def test_the_workflow_does_not_pass_the_authors_own_or_a_stale_approval(workflow):
    run, head = workflow
    assert "--approved" not in run([_review("anna", commit=head)], {"anna": "admin"})
    assert "--approved" not in run([_review("dana", commit=OLD)], {"dana": "write"})


def test_one_qualified_approval_is_enough_among_others(workflow):
    run, head = workflow
    assert "--approved" in run([_review("rita", commit=head), _review("dana", commit=head)], {"rita": "read", "dana": "write"})


def test_the_engine_never_calls_github_for_this():
    with open(route.__file__, encoding="utf-8") as f:
        text = f.read()
    assert '"gh"' not in text, "the workflow gathers what GitHub knows and hands the engine the facts"


# ---- the branch rules ----

def test_the_rules_ask_for_no_merge_queue_and_still_for_up_to_date_checks():
    kinds = {r["type"]: r for r in repo.RULES["rules"]}
    assert "merge_queue" not in kinds, "GitHub's Team plan has none on a private repository, and it could refuse the whole ruleset"
    assert kinds["required_status_checks"]["parameters"]["strict_required_status_checks_policy"] is True, \
        "so graph.json still merges one pull request at a time: whoever is behind rebases"
    assert "merge queue" not in repo.RULES["_about"]


def test_nothing_still_says_the_merge_queue_is_on():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for relative in ("oto/repo.py", "oto/sandbox.py", "oto/cli/repo.py", "oto/route.py", "oto/cli/route.py", "skills/sandbox/SKILL.md"):
        with open(os.path.join(here, relative), encoding="utf-8") as f:
            text = f.read()
        assert "the merge queue" not in text and "merge queue on" not in text, relative


def test_applying_old_rules_a_plan_refuses_says_how_to_fix_them(tmp_path, monkeypatch):
    from oto.project import ProjectError
    from test_repo import _fake_github
    root = str(tmp_path / "board")
    init(root, slug="board", name="Board", repo=True)
    _fake_github(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_GH_REFUSE_RULES", "1")
    rules_path = os.path.join(root, repo.RULES_FILE)
    with open(rules_path, encoding="utf-8") as f:
        rules = json.load(f)
    rules["rules"].append({"type": "merge_queue", "parameters": {}})
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(rules, f)
    with pytest.raises(ProjectError) as caught:
        repo.apply_rules(root, "acme/board", code_owner="dana")
    assert "merge_queue" in str(caught.value) and repo.RULES_FILE in str(caught.value), str(caught.value)


# ---- who can reach the secrets ----

def _jobs(text):
    body = text.split("\njobs:\n", 1)[1]
    return re.split(r"\n(?=  [a-z][a-z0-9-]*:\n)", "\n" + body)


DEPLOY_SECRETS = ("secrets.NEO4J_PASSWORD", "secrets.OTO_QUERY_REPO_TOKEN")


def test_every_job_that_reads_a_deploy_secret_runs_in_an_environment():
    for relative, text in repo.files("acme", "Acme", architecture=True).items():
        if not relative.endswith(".yml") or "\njobs:\n" not in text:
            continue
        for job in _jobs(text):
            if any(secret in job for secret in DEPLOY_SECRETS):
                assert re.search(r"^    environment: ", job, re.M), "%s: a job with no environment reads repository secrets from any branch:\n%s" % (relative, job[:200])


def test_the_build_on_main_publishes_from_the_environment_only_main_deploys_from():
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-deploy.yml")]
    job = next(j for j in _jobs(text) if j.strip().startswith("build-and-publish:"))
    assert "    environment: %s" % repo.MAIN_ENVIRONMENT in job
    assert repo.MAIN_ENVIRONMENT in text.split("\non:", 1)[0], "the header says where the secrets go"


def test_a_preview_holds_no_token_and_keeps_the_store_as_an_artifact():
    text = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-preview.yml")]
    assert "OTO_QUERY_REPO_TOKEN" not in text.split("\non:", 1)[1], "it runs from any branch, so a store token here reaches every contributor"
    assert "oto publish" not in text and "--delete" not in text and "closed" not in text
    assert "upload-artifact" in text and "build/acme.db" in text and "retention-days" in text
    assert "gh run download" in text, "the comment says how to read it"
    assert "oto repo comment" in text


def test_the_project_guide_says_where_the_secrets_go():
    guide = repo.files("acme", "Acme")["CLAUDE.md"]
    assert "--env %s" % repo.MAIN_ENVIRONMENT in guide


# ---- settings that did nothing ----

def test_a_new_deploy_config_no_longer_says_require_pr():
    assert "require_pr" not in deploy.starter("o/r", "https://github.com/o/s", "g")["publish"]


def test_an_old_config_with_require_pr_still_validates_and_is_told_it_does_nothing():
    config = json.loads(json.dumps(GOOD))
    config["publish"]["require_pr"] = True
    assert not deploy.problems(config)
    assert any("require_pr" in note for note in deploy.notes(config))
    config["publish"].pop("require_pr")
    assert deploy.notes(config) == []


def test_deploy_check_says_so_and_never_claims_a_pull_request(tmp_path):
    root = str(tmp_path / "kb")
    init(root, slug="kb", name="KB")
    config = json.loads(json.dumps(GOOD))
    config["publish"]["require_pr"] = True
    with open(os.path.join(root, "oto.deploy.json"), "w", encoding="utf-8") as f:
        json.dump(config, f)
    code, out = _cli("deploy", "check", "--project", root)
    assert code == 0 and "through a pull request" not in out and "require_pr" in out, out


def _neo4j(secret):
    config = json.loads(json.dumps(GOOD))
    config.update(connector="neo4j", connection={"endpoint": "bolt://x", "auth": "basic", "secret": secret})
    return config


def test_a_neo4j_config_naming_a_variable_the_engine_never_reads_is_refused():
    problems = deploy.problems(_neo4j("MY_NEO4J_SECRET"))
    assert any("NEO4J_PASSWORD" in p and "MY_NEO4J_SECRET" in p for p in problems), problems


def test_a_neo4j_config_naming_the_variable_the_engine_reads_is_fine():
    assert not deploy.problems(_neo4j("NEO4J_PASSWORD"))


def test_an_overlay_still_names_its_own_variable_because_it_reads_it():
    config = json.loads(json.dumps(GOOD))
    config["overlay"] = {"connector": "postgres", "connection": {"endpoint": "postgresql://ledger@db.internal/kg", "auth": "basic", "secret": "LEDGER_PASSWORD"}}
    assert not any("LEDGER_PASSWORD" in p for p in deploy.problems(config))
