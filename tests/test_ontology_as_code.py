"""An ontology designed together, like code (docs/plans/people-and-graphs.md, phase 2). Two authors added unrelated terms and
conflicted in all 6 files. Canonical files, an untracked trial and a term-level rebase mean both merge with nothing resolved by
hand, and a real clash, one term defined two ways, is the only thing that stops."""
import json
import os
import subprocess

import pytest

from oto import repo, sandbox
from oto.model import pack_merge, packs

from test_pack_workspace import _cli, _fill
from test_route import _commit, _git
from test_sandbox import fake  # noqa: F401  (a fixture: the sandbox tool, faked)


def _own(root, filename, name="garage"):
    return os.path.join(root, "ontology", name, filename)


def _load(root, filename):
    with open(_own(root, filename), encoding="utf-8") as f:
        return json.load(f)


def _save(root, filename, payload):
    with open(_own(root, filename), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _add_term(root, cls, prop, qid, who="Test Driver"):
    """What the interview writes for one new topic, hand-written: a class, a relation, their reasons, a question and a sample."""
    config = _load(root, "ontology.config.json")
    config["classes"][cls] = {"definition": "A %s of the fleet." % cls.lower()}
    config["properties"][prop] = {"domain": "Bus", "range": cls, "inverse": prop + "_of", "definition": "The %s of this bus." % cls.lower()}
    _save(root, "ontology.config.json", config)
    rationale = _load(root, "ontology.rationale.json")
    rationale["classes"][cls] = {"question": "Which %s applies to a bus?" % cls.lower(), "why": "Dispatch reads this before assigning a bus each morning, so it is a fact of its own.",
                                 "alternatives": "An attribute of the bus: rejected, because it has a life of its own over time.", "validated_by": who}
    rationale["properties"][prop] = {"question": "Which %s is this bus on?" % cls.lower(), "why": "Dispatch follows this link from a bus every morning before it assigns the day's work.",
                                     "alternatives": "A free-text note on the bus: rejected, because nobody could ask a question of it.", "validated_by": who}
    _save(root, "ontology.rationale.json", rationale)
    questions = _load(root, "questions.json")
    questions["questions"][qid] = {"who": "a dispatcher", "question": "Which %s applies to $BUS?" % cls.lower(), "why": "Dispatch reads it first.", "validated_by": who,
                                   "params": {"BUS": {"type": "Bus"}}, "ask": {"when": [{"edge": ["$BUS", prop, "x"]}, {"node": "x", "type": cls}], "select": ["x.label"]},
                                   "gate": "any", "gaps": {"when": [{"node": "$BUS", "type": "Bus"}], "say": "no %s is recorded for this bus" % cls.lower()}}
    _save(root, "questions.json", questions)
    sample = _load(root, "sample.graph.json")
    node = dict(sample["nodes"][0], id="%s.one" % cls.lower(), type=cls, label="%s one" % cls, attributes={})
    sample["nodes"].append(node)
    sample["edges"].append({"from": "bus.nw-101", "rel": prop, "to": "%s.one" % cls.lower()})
    _save(root, "sample.graph.json", sample)


@pytest.fixture
def team(tmp_path):
    """A pack workspace with a first vocabulary, on a shared origin."""
    code, out = _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")
    assert code == 0, out
    first = str(tmp_path / "garage")
    _fill(first)
    packs.format_(first)
    code, out = _cli("pack", "check", first, "--strict")
    assert code == 0, out
    code, out = _cli("pack", "try", first)
    assert code == 0, out
    _git(first, "init", "-q", "-b", "main")
    _commit(first, "The first vocabulary")
    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    _git(first, "remote", "add", "origin", origin)
    _git(first, "push", "-q", "origin", "main")

    class Team(object):
        def author(self, who, branch, cls, prop, qid):
            """Clone, branch, add a topic, hold it to the gates, push: the workflow as for code."""
            root = str(tmp_path / who)
            subprocess.run(["git", "clone", "-q", origin, root], check=True)
            _git(root, "checkout", "-q", "-b", branch)
            code, out = _cli("pack", "check", root, "--strict")
            assert code == 0, "a fresh clone passes: %s" % out
            _add_term(root, cls, prop, qid)
            code, out = _cli("pack", "format", root)
            assert code == 0, out
            code, out = _cli("pack", "check", root, "--strict")
            assert code == 0, out
            code, out = _cli("pack", "try", root)
            assert code == 0, out
            _commit(root, "Add %s" % cls)
            _git(root, "push", "-q", "origin", branch)
            return root

        def merge(self, branch):
            root = str(tmp_path / ("merger-" + branch))
            if not os.path.isdir(root):
                subprocess.run(["git", "clone", "-q", origin, root], check=True)
            _git(root, "fetch", "-q", "origin")
            _git(root, "reset", "-q", "--hard", "origin/main")
            done = subprocess.run(["git", "-C", root, "-c", "user.name=lead", "-c", "user.email=lead@example.org", "merge", "--no-ff", "-m", "merge",
                                   "origin/" + branch], capture_output=True, text=True)
            if done.returncode != 0:
                _git(root, "merge", "--abort")
                return root, False
            _git(root, "push", "-q", "origin", "main")
            return root, True

    return Team()


def _rebase(root, onto="origin/main"):
    _git(root, "fetch", "-q", "origin")
    code, out = _cli("pack", "rebase", root, "--onto", onto, "--json")
    return code, json.loads(out)


def _run_steps(root, steps):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.org", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.org")
    for step in steps:
        done = subprocess.run(step, cwd=root, shell=True, capture_output=True, text=True, env=env)
        assert done.returncode == 0, "%s: %s%s" % (step, done.stdout, done.stderr)


# ---- the whole of it ----

def test_two_authors_add_unrelated_terms_and_both_merge_with_nothing_resolved_by_hand(team):
    anna = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    ben = team.author("ben", "add-inspection", "Inspection", "last_inspected", "inspection-of-a-bus")
    assert "trial/ontology.config.json" not in _git(anna, "ls-files"), "what `oto pack try` writes isn't tracked"
    _root, merged = team.merge("add-route")
    assert merged
    merged_at, _merged = team.merge("add-inspection")
    code, result = _rebase(ben)
    assert code == 0 and result["ok"] and not result["conflicts"], result
    _run_steps(ben, result["steps"])
    assert _git(ben, "status", "--porcelain") == ""
    merged_at, merged = team.merge("add-inspection")
    assert merged, "and it merges with no conflict"
    config = _load(merged_at, "ontology.config.json")
    assert {"Route", "Inspection", "Bus"} <= set(config["classes"]) and {"runs_on", "last_inspected"} <= set(config["properties"])
    assert {"route-of-a-bus", "inspection-of-a-bus"} <= set(_load(merged_at, "questions.json")["questions"])
    assert {"route.one", "inspection.one"} <= {n["id"] for n in _load(merged_at, "sample.graph.json")["nodes"]}
    code, out = _cli("pack", "check", merged_at, "--strict")
    assert code == 0, out
    code, out = _cli("pack", "try", merged_at)
    assert code == 0, out


def test_one_term_defined_two_ways_is_a_real_clash_and_nothing_is_written(team):
    anna = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    ben = team.author("ben", "add-route-too", "Route", "follows", "route-followed")
    config = _load(ben, "ontology.config.json")
    config["classes"]["Route"]["definition"] = "Something else entirely."
    _save(ben, "ontology.config.json", config)
    assert _cli("pack", "format", ben)[0] == 0
    _commit(ben, "Route, my way")
    assert team.merge("add-route")[1]
    before = _load(ben, "ontology.config.json")
    code, result = _rebase(ben)
    assert code != 0 and not result["ok"], result
    assert any("classes.Route" in c for c in result["conflicts"]), result["conflicts"]
    assert _load(ben, "ontology.config.json") == before and _git(ben, "status", "--porcelain") == "", "nothing written"
    assert anna


def test_rebase_keeps_a_term_one_side_removed_and_the_other_left_alone(team):
    anna = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    root = str(os.path.dirname(anna))
    ben = team.author("ben", "drop-capacity", "Depot", "kept_at", "depot-of-a-bus")
    config = _load(ben, "ontology.config.json")
    del config["attributes"]["Bus"]["capacity"]
    _save(ben, "ontology.config.json", config)
    assert _cli("pack", "format", ben)[0] == 0
    _commit(ben, "Capacity goes")
    assert team.merge("add-route")[1]
    code, result = _rebase(ben)
    assert code == 0, result
    merged = _load(ben, "ontology.config.json")
    assert "capacity" not in merged["attributes"]["Bus"] and "Route" in merged["classes"] and "Depot" in merged["classes"]
    assert root


def test_rebase_waits_for_a_clean_tree_and_has_no_steps_when_already_on_main(team):
    ben = team.author("ben", "add-route", "Route", "runs_on", "route-of-a-bus")
    code, result = _rebase(ben)
    assert code == 0 and result["steps"] == [], result
    anna = team.author("anna", "add-depot", "Depot", "kept_at", "depot-of-a-bus")
    assert team.merge("add-depot")[1] and anna
    with open(_own(ben, "README.md"), "a", encoding="utf-8") as f:
        f.write("uncommitted\n")
    code, result = _rebase(ben)
    assert code != 0 and any("uncommitted" in c for c in result["conflicts"]), result


# ---- canonical files ----

def test_the_files_are_canonical_and_the_check_holds_them_to_it(tmp_path, team):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    with open(_own(author, "ontology.config.json"), encoding="utf-8") as f:
        text = f.read()
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    sample = _load(author, "sample.graph.json")
    assert [n["id"] for n in sample["nodes"]] == sorted(n["id"] for n in sample["nodes"])
    keys = [(e["from"], e["rel"], e["to"]) for e in sample["edges"]]
    assert keys == sorted(keys)
    config = _load(author, "ontology.config.json")
    with open(_own(author, "ontology.config.json"), "w", encoding="utf-8") as f:
        json.dump(dict(reversed(list(config.items()))), f, indent=4)
    code, out = _cli("pack", "check", author, "--strict")
    assert code != 0 and "oto pack format" in out and "ontology.config.json" in out, out
    code, out = _cli("pack", "check", author)
    assert "oto pack format" not in out, "an installed pack made before this isn't refused for its layout"
    assert _cli("pack", "format", author)[0] == 0
    assert _cli("pack", "check", author, "--strict")[0] == 0


def test_a_new_workspace_starts_canonical(tmp_path):
    assert _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")[0] == 0
    assert pack_merge.not_canonical(str(tmp_path / "garage")) == []


# ---- what a workspace tracks, and declares ----

def test_a_workspace_ignores_what_try_writes_and_the_trials_documents(tmp_path):
    assert _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")[0] == 0
    root = str(tmp_path / "garage")
    with open(os.path.join(root, ".gitignore"), encoding="utf-8") as f:
        text = f.read()
    for path in ("trial/ontology.config.json", "trial/questions.json", "trial/rules.json", "trial/inbox/"):
        assert path in text, path


def test_a_workspace_declares_the_plugin_at_its_root_and_a_release_leaves_it_behind(tmp_path):
    assert _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")[0] == 0
    root = str(tmp_path / "garage")
    from oto.model import lock
    assert lock.declared(root) is not None, "an author who opens the workspace is offered the engine plugin"
    for left in (".claude", ".gitignore", ".github", "trial"):
        assert left in packs.WORKSPACE_ONLY, left


# ---- what a reviewer reads ----

def test_diff_says_what_changed_term_by_term(team):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    config = _load(author, "ontology.config.json")
    del config["classes"]["Mechanic"]
    config["classes"]["Garage"]["definition"] = "A place buses come back to."
    _save(author, "ontology.config.json", config)
    code, out = _cli("pack", "diff", author, "--base", "origin/main")
    assert code == 0, out
    assert "Route" in out and "runs_on" in out and "route-of-a-bus" in out
    assert "Garage" in out and "Mechanic" in out
    assert "**Breaking**" in out and "class Mechanic" in out.split("**Breaking**")[1], out


def test_a_diff_with_no_change_says_so(team):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    code, out = _cli("pack", "diff", author, "--base", "HEAD")
    assert code == 0 and "No term changed" in out, out


@pytest.mark.parametrize("change, says", [
    (lambda c: c["classes"].pop("Mechanic"), "class Mechanic"),
    (lambda c: c["properties"].pop("works_at"), "relation works_at"),
    (lambda c: c["properties"]["parked_at"].update(range="Mechanic"), "relation parked_at"),
    (lambda c: c["attributes"]["Bus"].pop("capacity"), "attribute Bus.capacity"),
    (lambda c: c["attributes"]["Bus"]["capacity"].update(type="string"), "attribute Bus.capacity"),
    (lambda c: c["attributes"]["Bus"]["capacity"].update(required=True), "attribute Bus.capacity"),
])
def test_check_against_a_release_names_what_is_breaking(team, change, says):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    _git(author, "tag", "v1", "HEAD")
    config = _load(author, "ontology.config.json")
    change(config)
    _save(author, "ontology.config.json", config)
    assert _cli("pack", "format", author)[0] == 0
    code, out = _cli("pack", "check", author, "--against", "1")
    assert code != 0 and "breaking" in out and says in out, out


def test_check_against_a_release_passes_what_only_adds(team):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    _git(author, "tag", "v1", "HEAD")
    _add_term(author, "Depot", "kept_at", "depot-of-a-bus")
    assert _cli("pack", "format", author)[0] == 0
    code, out = _cli("pack", "check", author, "--against", "v1")
    assert code == 0 and "nothing breaking" in out, out


def test_check_against_something_that_isnt_there_says_so(team):
    author = team.author("anna", "add-route", "Route", "runs_on", "route-of-a-bus")
    code, out = _cli("pack", "check", author, "--against", "99")
    assert code != 0 and "99" in out, out


# ---- the workflows ----

def _workflow(tmp_path, name):
    assert _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")[0] == 0
    with open(tmp_path / "garage" / ".github" / "workflows" / name, encoding="utf-8") as f:
        return f.read()


def test_the_check_workflow_pins_the_engine_tries_the_pack_and_posts_the_diff(tmp_path):
    from oto import __version__
    text = _workflow(tmp_path, "pack-check.yml")
    assert "name: pack check" in text.split("jobs:")[1], "the job carries the name the rules require"
    assert "@v%s" % __version__ in text and "oto pack check . --strict" in text and "oto pack try ." in text
    assert "oto pack diff . --base" in text and "gh pr comment" in text and "fetch-depth: 0" in text and "pull-requests: write" in text


def test_the_publish_workflow_keeps_its_token_in_an_environment_only_release_tags_deploy_from(tmp_path):
    from oto import __version__
    text = _workflow(tmp_path, "pack-publish.yml")
    assert "environment: %s" % repo.RELEASE_ENVIRONMENT in text and "@v%s" % __version__ in text
    assert "workflow_dispatch" not in text, "a release is a tag, which the rules keep to maintainers"


# ---- the branch and tag rules of a workspace ----

def _workspace_with_rules(tmp_path, monkeypatch):
    from test_repo import _fake_github
    assert _cli("pack", "new", "garage", "--to", str(tmp_path), "--maintainer", "Test Driver")[0] == 0
    root = str(tmp_path / "garage")
    return root, _fake_github(tmp_path, monkeypatch)


def test_a_workspace_carries_its_own_rules(tmp_path, monkeypatch):
    root, _calls = _workspace_with_rules(tmp_path, monkeypatch)
    with open(os.path.join(root, repo.RULES_FILE), encoding="utf-8") as f:
        rules = json.load(f)
    kinds = {r["type"]: r for r in rules["rules"]}
    assert kinds["pull_request"]["parameters"]["required_approving_review_count"] == 1, "neither author merges unreviewed"
    assert kinds["pull_request"]["parameters"]["require_code_owner_review"] is True
    assert {c["context"] for c in kinds["required_status_checks"]["parameters"]["required_status_checks"]} == {"pack check"}
    with open(os.path.join(root, repo.TAG_RULES_FILE), encoding="utf-8") as f:
        tags = json.load(f)
    assert tags["target"] == "tag" and tags["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
    assert {r["type"] for r in tags["rules"]} == {"creation", "update", "deletion"}
    assert {a["actor_id"] for a in tags["bypass_actors"]} == {repo.ADMIN_ROLE, repo.MAINTAIN_ROLE}, "release tags are limited to maintainers"


def test_applying_a_workspaces_rules_sets_owners_the_release_environment_and_both_rulesets(tmp_path, monkeypatch, capsys):
    from oto.cli import main
    root, calls = _workspace_with_rules(tmp_path, monkeypatch)
    assert main(["repo", "rules", "--apply", "--repo", "acme/garage", "--code-owner", "dana", "--project", root]) == 0, capsys.readouterr().err
    with open(os.path.join(root, ".github", "CODEOWNERS"), encoding="utf-8") as f:
        owners = " ".join(f.read().split())
    for path in ("/ontology/ @dana", "/manifest.json @dana", "/.github/ @dana"):
        assert path in owners, owners
    flat = [" ".join(c["args"]) for c in calls()]
    assert any(f.startswith("api --method PUT repos/acme/garage/environments/%s" % repo.RELEASE_ENVIRONMENT) for f in flat), flat
    assert any("deployment-branch-policies" in f and "type=tag" in f and "name=v*" in f for f in flat), flat
    assert sum(1 for f in flat if "/rulesets" in f and "--method POST" in f) == 2, flat
    assert not any("/keys" in f for f in flat), "a workspace's workflows don't push to main: no deploy key"
    assert "pack check" in capsys.readouterr().out


# ---- a sandbox from an existing repository ----

@pytest.fixture
def sandbox_fake(fake, tmp_path):  # noqa: F811
    """The sandbox tool faked, and a real repository on disk to clone: a project someone else made."""
    work = tmp_path / "theirs"
    work.mkdir()
    (work / "manifest.json").write_text("{}\n")
    _git(str(work), "init", "-q", "-b", "main")
    _commit(str(work), "theirs")
    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "clone", "-q", "--bare", str(work), origin], check=True)

    class Holder(object):
        pass
    holder = Holder()
    holder.fake, holder.origin, holder.head = fake, origin, _git(origin, "rev-parse", "main")
    return holder


def test_up_clone_clones_into_an_empty_folder_and_never_pushes(sandbox_fake, tmp_path):
    origin = sandbox_fake.origin
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5, clone=origin)
    project = tmp_path / "box" / "project"
    assert (project / "manifest.json").exists(), "the repository's files are in the folder"
    assert _git(str(project), "remote", "get-url", "origin") == origin
    assert report["repository"] == origin
    assert _git(origin, "rev-parse", "main") == sandbox_fake.head, "nothing pushed"
    assert any("cloned" in line for line in report["done"])
    assert sandbox_fake.fake.calls("create")


def test_up_clone_stores_the_token_as_the_sandboxs_secret(sandbox_fake, tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "_clone", lambda project_dir, url, token=None: os.makedirs(project_dir, exist_ok=True))
    monkeypatch.setenv("MY_TOKEN", "ghp-like-but-not")
    sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5, clone="acme/garage", token_env="MY_TOKEN")
    secrets = sandbox_fake.fake.calls("secret")
    assert any(c[:2] == ["secret", "set"] and "--sandbox" in c and "box" in c for c in secrets), secrets


def test_up_clone_refuses_a_folder_holding_something_else(sandbox_fake, tmp_path):
    project = tmp_path / "box" / "project"
    project.mkdir(parents=True)
    (project / "notes.txt").write_text("mine")
    with pytest.raises(sandbox.SandboxError):
        sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5, clone=sandbox_fake.origin)
    assert (project / "notes.txt").read_text() == "mine"
    assert not sandbox_fake.fake.calls("create")


def test_up_clone_again_reuses_a_folder_already_cloned_from_there(sandbox_fake, tmp_path):
    first = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5, clone=sandbox_fake.origin)
    again = sandbox.up(name="box", directory=str(tmp_path / "box"), wait=5, clone=sandbox_fake.origin)
    assert first and any("reused" in line for line in again["done"])


def test_up_clone_takes_no_kind_or_repo(sandbox_fake, tmp_path):
    for other in ({"kind": "ontology"}, {"repo": "acme/x"}, {"no_repo": True}):
        with pytest.raises(sandbox.SandboxError):
            sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, clone=sandbox_fake.origin, **other)


def test_check_says_it_would_clone_and_changes_nothing(sandbox_fake, tmp_path):
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, check=True, clone=sandbox_fake.origin)
    assert any("would clone" in line for line in report["done"])
    assert not (tmp_path / "box").exists()


# ---- what the skill tells an author ----

def test_the_interview_skill_names_questions_by_topic_and_says_how_to_rebase():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "skills", "ontology-interview", "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    assert "by topic" in text and "oto pack format" in text and "oto pack rebase" in text
