"""Deploy (roadmap Epic B, thin): one config says where a graph goes, and it validates before anything
publishes; the same build is promoted through named environments, never rebuilt, with who approved
each step on record. Git is the only path to a graph, and the agent holds no key to one."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import contextlib

import pytest

from oto import deploy, publish as pub
from oto.builder import build
from oto.cli import main
from oto.project import Project, ProjectError
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _bare(root, name="query.git"):
    path = os.path.join(root, name)
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", path], check=True)
    return path


def _git(bare, *args):
    return subprocess.run(["git", "--git-dir", bare] + list(args), capture_output=True, text=True, check=True).stdout


GOOD = {"repo": "cynergis/client-kg", "graph": "acme", "connector": "sqlite",
        "publish": {"to": "https://github.com/cynergis/client-kg-store", "require_pr": True},
        "environments": [{"name": "dev", "approvers": []}, {"name": "test", "approvers": ["kg-owners"]},
                         {"name": "prod", "approvers": ["kg-owners", "data-governance"]}],
        "promotion": "same-commit"}


@pytest.fixture
def project(tmp_path):
    root = str(tmp_path / "acme")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="acme", name="Acme", ontology="software-architecture")
        p = Project.standard(root)
        build(p)
    return p


def _write_config(project, config):
    with open(deploy.path(project), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ---- B1: the config ----

def test_a_good_config_has_no_problems_and_names_its_chain():
    assert deploy.problems(GOOD) == []
    assert deploy.chain(GOOD) == ["dev", "test", "prod"]
    assert deploy.approvers(GOOD, "prod") == ["kg-owners", "data-governance"]


@pytest.mark.parametrize("change, said", [
    (lambda c: c.pop("repo"), "`repo`"),
    (lambda c: c.update(connector="mongo"), "connector 'mongo'"),
    (lambda c: c.update(connector="neo4j"), "`connection`"),
    (lambda c: c.update(environments=[]), "at least one environment"),
    (lambda c: c["environments"].append({"name": "dev", "approvers": []}), "twice"),
    (lambda c: c["environments"].__setitem__(0, {"name": "Dev Env", "approvers": []}), "lowercase"),
    (lambda c: c["environments"][1].update(approvers="kg-owners"), "a list"),
    (lambda c: c.update(promotion="rebuild"), "same-commit"),
    (lambda c: c.update(connector="neo4j", connection={"endpoint": "bolt://x", "auth": "basic", "secret": "hunter2!"}), "name of an environment variable"),
    (lambda c: c.update(mystery=1), "unknown key"),
])
def test_every_mistake_in_the_config_is_named(change, said):
    config = json.loads(json.dumps(GOOD))
    change(config)
    problems = deploy.problems(config)
    assert problems and any(said in p for p in problems), problems


def test_a_secret_value_in_the_file_refuses_it_and_is_never_echoed():
    config = json.loads(json.dumps(GOOD))
    config["connection"] = {"endpoint": "bolt://x", "auth": "token", "secret": "NEO4J_TOKEN",
                            "note": "temporary: ghp_" + "a" * 36}
    problems = deploy.problems(config)
    assert any("credential: GitHub token" in p for p in problems) and "ghp_" not in " ".join(problems)


def test_deploy_check_reads_the_project_file_and_says_so(project):
    code, out = _cli("deploy", "check", "--project", project.data)
    assert code == 0 and "no oto.deploy.json" in out and "oto deploy init" in out
    code, out = _cli("deploy", "init", "--project", project.data, "--repo", "cynergis/acme", "--to", "https://github.com/cynergis/acme-store")
    assert code == 0 and os.path.exists(deploy.path(project))
    code, out = _cli("deploy", "check", "--project", project.data)
    assert code == 0 and "dev -> test -> prod" in out and "sqlite" in out, out
    bad = deploy.load(project)
    bad["environments"][1]["approvers"] = "kg-owners"
    _write_config(project, bad)
    code, out = _cli("deploy", "check", "--project", project.data)
    assert code == 1 and "a list" in out


# ---- B4: environments and promotion ----

def _published(project, tmp_path, source="org/knowledge@abc123"):
    target = _bare(str(tmp_path))
    config = dict(GOOD, publish={"to": target, "require_pr": False})
    _write_config(project, config)
    manifest = pub.publish(project, target, source=source, environment="dev")
    return target, manifest


def test_publishing_to_dev_lands_on_the_dev_branch_with_a_record(project, tmp_path):
    target, manifest = _published(project, tmp_path)
    assert manifest["changed"] and manifest["environment"] == "dev"
    branches = _git(target, "branch", "--format=%(refname:short)").split()
    assert branches == ["dev"], "an environment is a branch of the query repository; nothing on main"
    record = [json.loads(l) for l in _git(target, "show", "dev:PROMOTIONS.jsonl").splitlines()]
    assert len(record) == 1 and record[0]["environment"] == "dev" and record[0]["source"] == "org/knowledge@abc123"
    assert record[0]["sha256"] == manifest["sha256"] and record[0]["approved_by"] is None and record[0]["from"] is None


def test_promotion_copies_the_same_store_forward_and_records_who_approved(project, tmp_path):
    target, dev = _published(project, tmp_path)
    out = deploy.promote(project, "test", commit="abc123", by="Dana Reyes")
    assert out["environment"] == "test" and out["from"] == "dev" and out["sha256"] == dev["sha256"]
    assert out["approved_by"] == "Dana Reyes" and out["approver_kind"] == "person"
    record = [json.loads(l) for l in _git(target, "show", "test:PROMOTIONS.jsonl").splitlines()]
    assert [r["environment"] for r in record] == ["dev", "test"], "the record travels with the store"
    test_store = _git(target, "ls-tree", "--name-only", "test").split()
    assert "acme.db" in test_store and "MANIFEST.json" in test_store
    manifest = json.loads(_git(target, "show", "test:MANIFEST.json"))
    assert manifest["sha256"] == dev["sha256"] and manifest["environment"] == "test" and manifest["source"] == "org/knowledge@abc123"
    # a reader syncs the environment by name and status says what it holds and who approved it
    dest = str(tmp_path / "reader")
    pub.sync(target, dest=dest, branch="test")
    code, text = _cli("status", "--project", dest)
    assert code == 0 and "environment test" in text and "approved by Dana Reyes" in text and "abc123" in text


def test_promotion_refuses_to_skip_an_environment_rebuild_or_pass_without_an_approver(project, tmp_path):
    target, dev = _published(project, tmp_path)
    with pytest.raises(ProjectError, match="not around it"):
        deploy.promote(project, "prod", commit="abc123", by="Dana Reyes")
    with pytest.raises(ProjectError, match="approver"):
        deploy.promote(project, "test", commit="abc123", by=None)
    with pytest.raises(ProjectError, match="holds org/knowledge@abc123"):
        deploy.promote(project, "test", commit="def456", by="Dana Reyes")
    with pytest.raises(ProjectError, match="not an environment"):
        deploy.promote(project, "staging", commit="abc123", by="Dana Reyes")
    # a rebuilt graph changes the local store; promotion still moves what dev holds, not the rebuild
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    graph["nodes"][0]["summary"] = (graph["nodes"][0].get("summary") or "") + " Rebuilt."
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(graph, f)
    with contextlib.redirect_stdout(io.StringIO()):
        build(project)
    out = deploy.promote(project, "test", commit="abc123", by="Dana Reyes")
    assert out["sha256"] == dev["sha256"], "same commit means the artifact dev holds, never a rebuild"


def test_a_tampered_source_environment_is_refused(project, tmp_path):
    target, dev = _published(project, tmp_path)
    work = str(tmp_path / "tamper")
    subprocess.run(["git", "clone", "--quiet", "--branch", "dev", target, work], check=True)
    with open(os.path.join(work, "acme.db"), "ab") as f:
        f.write(b"\0")
    subprocess.run(["git", "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qam", "tamper"], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "origin", "dev"], cwd=work, check=True)
    with pytest.raises(ProjectError, match="does not match"):
        deploy.promote(project, "test", commit="abc123", by="Dana Reyes")


def test_the_cli_publishes_to_an_environment_and_promotes(project, tmp_path):
    target, dev = _published(project, tmp_path)
    code, out = _cli("publish", "--project", project.data, "--to", "test", "--promote", "abc123", "--by", "Dana Reyes")
    assert code == 0 and "promoted" in out and "test" in out and "abc123" in out, out
    code, out = _cli("publish", "--project", project.data, "--to", "prod", "--promote", "abc123")
    assert code == 1 and "approver" in out
    code, out = _cli("deploy", "status", "--project", project.data)
    assert code == 0 and "dev" in out and "test" in out and "Dana Reyes" in out and "prod" in out and "nothing" in out, out


def test_without_a_config_publish_works_as_before(project, tmp_path):
    target = _bare(str(tmp_path))
    manifest = pub.publish(project, target, source="org/knowledge@abc123")
    assert manifest["changed"] and "environment" not in manifest
    assert _git(target, "branch", "--format=%(refname:short)").split() == ["main"]
    with pytest.raises(ProjectError, match="no oto.deploy.json"):
        pub.publish(project, target, environment="dev")


def test_the_snapshot_and_the_deploy_station_know_the_config(project):
    from oto import snapshot
    s = snapshot.build(project)
    assert s["deploy"]["config"] is False and s["deploy"]["environments"] == []
    _write_config(project, GOOD)
    s = snapshot.build(project)
    assert s["deploy"]["config"] is True and s["deploy"]["environments"] == ["dev", "test", "prod"] and s["deploy"]["connector"] == "sqlite"
    station = next(st for st in s["stations"] if st["id"] == "deploy")
    assert "dev, test, prod" in station["line"]


def _workflow():
    from oto import repo
    return repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-deploy.yml")]


def _jobs(workflow):
    """The workflow's jobs by name, as text: the tests read it without a YAML library."""
    parts = re.split(r"^  ([a-z-]+):\n", workflow.split("\njobs:\n", 1)[1], flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def test_the_generated_workflow_publishes_to_the_first_environment_and_promotes_behind_github_environments():
    workflow = _workflow()
    jobs = _jobs(workflow)
    assert sorted(jobs) == ["build-and-publish", "promote-second", "promote-third"]
    assert "oto deploy check" in jobs["build-and-publish"]
    assert 'oto publish --project . --to "${{ steps.has-config.outputs.first }}"' in jobs["build-and-publish"]
    for position in ("second", "third"):
        job = jobs["promote-" + position]
        assert "if: needs.build-and-publish.outputs.%s != ''" % position in job, "skipped when the config declares no such environment"
        assert "environment: ${{ needs.build-and-publish.outputs.%s }}" % position in job
        assert '--to "${{ needs.build-and-publish.outputs.%s }}" --promote "${{ github.sha }}"' % position in job
        assert "      %s: ${{ steps.has-config.outputs.%s }}" % (position, position) in jobs["build-and-publish"]
    assert "needs: [ build-and-publish, promote-second ]" in jobs["promote-third"], "a job reads the outputs of the jobs it needs, only"
    assert "--to dev" not in workflow and "environment: test" not in workflow and "environment: prod" not in workflow
    assert "hashFiles('oto.deploy.json')" in workflow
    assert "github.actor" in workflow, "the approver is GitHub's reviewer, not a typed name"


def test_every_deploy_job_has_the_engine_for_all_its_steps_and_keeps_no_checkout_credential():
    from oto import repo
    jobs = _jobs(_workflow())
    for name, job in jobs.items():
        assert "\n    env:\n      ENGINE: ${{ vars.OTO_ENGINE || '%s' }}\n" % repo.ENGINE in job, name
        assert "\n          ENGINE:" not in job, "%s: ENGINE on one step leaves the others that install or name the engine without it" % name
        assert "- uses: actions/checkout@v4\n        with:\n          persist-credentials: false\n" in job, \
            "%s: no job pushes here, and git would send the checkout's token to the query repository" % name
    assert 'pip install "oto-kg[neo4j] @ git+${ENGINE}"' in jobs["build-and-publish"]
    assert '--engine "${ENGINE}"' in jobs["build-and-publish"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="the step runs under bash, as on GitHub's runners")
@pytest.mark.parametrize("names", [["dev", "test", "prod"], ["prod"], ["dev", "staging", "live"], ["dev", "test", "staging", "prod"]])
def test_the_workflow_names_the_environments_the_config_declares(project, tmp_path, names):
    step = _jobs(_workflow())["build-and-publish"].split("id: has-config\n        run: |\n", 1)[1].split("\n        env:\n", 1)[0]
    script = "\n".join(line[10:] for line in step.split("\n"))
    tools = tmp_path / "bin"
    tools.mkdir()
    (tools / "oto").write_text('#!/bin/sh\nexec "%s" -m oto.cli "$@"\n' % sys.executable)
    (tools / "oto").chmod(0o755)
    os.symlink(sys.executable, str(tools / "python"))
    outputs = tmp_path / "github_output"
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""), PYTHONPATH=REPO, GITHUB_OUTPUT=str(outputs))

    def run():
        outputs.write_text("")
        done = subprocess.run(["bash", "-e", "-c", script], cwd=project.data, env=env, capture_output=True, text=True)
        return done, dict(line.split("=", 1) for line in outputs.read_text().splitlines())

    done, said = run()
    assert done.returncode == 0 and said == {"deploy": "false"}, done.stdout + done.stderr
    _write_config(project, dict(GOOD, environments=[{"name": n, "approvers": []} for n in names]))
    done, said = run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert said == dict({"deploy": "true", "first": names[0]}, **dict(zip(("second", "third"), names[1:3])))
    assert ("::warning::" in done.stdout) == (len(names) > 3), "an environment past the third has no promote job, and the run says so"
    _write_config(project, dict(GOOD, environments=[]))
    done, said = run()
    assert done.returncode != 0 and said == {}, "a config that does not validate stops the deploy"


def test_promotion_and_status_ignore_the_header_the_workspace_inherited(project, git_over_http, tmp_path, monkeypatch):
    # The promote jobs run in a checkout too: every call to the query repository sends its own token.
    _bare(git_over_http.root)
    _write_config(project, dict(GOOD, publish={"to": git_over_http.base + "/query.git", "require_pr": False}))
    monkeypatch.chdir(git_over_http.workspace(str(tmp_path / "workspace")))
    pub.publish(project, source="org/knowledge@abc123", environment="dev")
    deploy.promote(project, "test", commit="abc123", by="Dana Reyes")
    held = deploy.status(project)
    assert held["test"]["approved_by"] == "Dana Reyes" and held["prod"] is None
    assert git_over_http.seen and git_over_http.header not in git_over_http.seen


# ---- F2, F4: the audit log records what left the project, and a node keeps its IRI through the chain ----
def test_publish_and_promotion_are_audited_and_a_node_keeps_its_iri_in_every_environment(project, tmp_path):
    import sqlite3
    from oto import audit
    from oto.model.namespaces import Terms
    target, dev = _published(project, tmp_path)
    deploy.promote(project, "test", commit="abc123", by="Dana Reyes")
    deploy.promote(project, "prod", commit="abc123", by="Dana Reyes")
    records = audit.read(project)
    assert [(r["action"], r["decision"]) for r in records] == [("publish", "published"), ("promote", "promoted"), ("promote", "promoted")], records
    assert records[1]["principal"] == "Dana Reyes" and "test" in records[1]["detail"] and dev["sha256"][:12] in records[1]["detail"]
    assert audit.verify(project)["ok"]
    with open(project.ontology_config_path, encoding="utf-8") as f:
        instances = Terms(json.load(f), project.identity()).instances
    iris = {}
    for environment in ("dev", "test", "prod"):
        dest = str(tmp_path / ("reader-" + environment))
        pub.sync(target, dest=dest, branch=environment)
        con = sqlite3.connect(os.path.join(dest, "acme.db"))
        try:
            iris[environment] = {instances + row[0] for row in con.execute("SELECT id FROM nodes")}
        finally:
            con.close()
        manifest = json.loads(_git(target, "show", "%s:MANIFEST.json" % environment))
        assert manifest["sha256"] == dev["sha256"], "the same store in every environment, so the same ids under one namespace"
    assert iris["dev"] and iris["dev"] == iris["test"] == iris["prod"], "a node keeps its IRI when promoted"
