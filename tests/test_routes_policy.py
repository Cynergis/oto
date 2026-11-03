"""The routes' policy comes from the pack and is derived into the project (docs/plans/graph-journeys.md, phase 6).

A pack's manifest may carry `routes`: which routes a project on it may use (`allowed`), the classes a
session may touch without review (`session.classes`), and the guardrailed settings. `oto init --pack`
derives it into project.config.json and records which keys came from the pack (`routes_from`); a project
overrides a key by writing it, and `oto ontology update` rewrites only the keys still the pack's. The
gate reads the policy; which route a change takes stays derived from the pull request (ADR-0013)."""
import contextlib
import io
import json
import os
import tempfile

from oto import route
from oto.cli import main
from oto.curate import session
from oto.model import packs

from test_curate import _node, _project
from test_packs import home                      # noqa: F401 - a machine with the fixture packs installed as plugins
from test_route import _commit, _git

POLICY = {"allowed": ["session", "reviewed", "guardrailed"],
          "session": {"classes": ["System", "Component"]},
          "guardrailed": {"from": "inbox/transcripts", "classes": ["Decision"], "max_facts": 20, "additive_only": True, "attributed": True}}


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _pack_with_routes(routes=POLICY, name="fleet"):
    code, out = _cli("pack", "new", name, "--ontology", "software-architecture", "--domain", "software")
    assert code == 0, out
    directory = packs.dir_for(name)
    manifest = json.load(open(packs.path_for(directory), encoding="utf-8"))
    manifest["routes"] = routes
    with open(packs.path_for(directory), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return directory


def _read(root):
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _write(root, config):
    with open(os.path.join(root, "project.config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ---- the manifest ----

def test_a_pack_declares_the_routes_policy_and_the_check_holds_its_shape(home, capsys):
    directory = _pack_with_routes()
    assert packs.check(directory) == []
    assert main(["pack", "show", "fleet"]) == 0
    out = capsys.readouterr().out
    assert "routes:" in out and "session, reviewed, guardrailed" in out and "System, Component" in out and "inbox/transcripts" in out, out
    bad = {"allowed": ["session", "express"], "session": {"classes": ["Starship"]},
           "guardrailed": {"from": "/abs", "classes": "Decision", "max_facts": 0, "additive_only": "yes"}, "fast": {}}
    _pack_with_routes(bad, name="loose")
    text = "\n".join(packs.check(packs.dir_for("loose")))
    assert "express" in text and "Starship" in text and "max_facts" in text and "additive_only" in text and "fast" in text and "from" in text, text
    assert "Decision" in text, "classes must be a list"
    _pack_with_routes({"allowed": ["session"]}, name="narrow")
    assert any("reviewed" in p for p in packs.check(packs.dir_for("narrow"))), "reviewed is always allowed, so a list without it is wrong"


# ---- derived into the project ----

def test_init_from_a_pack_derives_the_routes_and_records_which_keys_are_the_packs(home, capsys):
    _pack_with_routes()
    root = os.path.join(home, "board")
    assert main(["init", "--name", "Board", "--project", root, "--pack", "fleet"]) == 0
    config = _read(root)
    assert config["routes"] == POLICY
    assert config["routes_from"] == [{"pack": "fleet", "release": 1, "keys": ["allowed", "guardrailed", "session"],
                                      "derived": {k: POLICY[k] for k in ("allowed", "guardrailed", "session")}}]
    capsys.readouterr()
    assert main(["status", "--project", root]) == 0
    out = capsys.readouterr().out
    assert "routes" in out and "from the pack fleet @1" in out and "allowed, guardrailed, session" in out, out
    # a pack without routes: nothing derived, nothing said
    plain = os.path.join(home, "plain")
    assert main(["pack", "new", "plainpack", "--ontology", "software-architecture", "--domain", "software"]) == 0
    assert main(["init", "--name", "Plain", "--project", plain, "--pack", "plainpack"]) == 0
    assert "routes" not in _read(plain) and "routes_from" not in _read(plain)


def test_a_project_overrides_a_key_by_writing_it_and_update_rewrites_only_the_packs_keys(home, capsys):
    directory = _pack_with_routes()
    root = os.path.join(home, "board")
    assert main(["init", "--name", "Board", "--project", root, "--pack", "fleet"]) == 0
    config = _read(root)
    config["routes"]["guardrailed"]["max_facts"] = 5                     # the project is stricter than its pack
    _write(root, config)
    capsys.readouterr()
    assert main(["status", "--project", root]) == 0
    [line] = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("routes ")]
    assert "from the pack fleet @1: allowed, session" in line and "guardrailed set here" in line, \
        "a key the project rewrote is its own at once, not only after the next update: " + line
    # the pack moves on: a second release with other settings
    manifest = json.load(open(packs.path_for(directory), encoding="utf-8"))
    manifest["release"] = 2
    manifest["routes"] = {"allowed": ["session", "reviewed"], "session": {"classes": ["System"]},
                          "guardrailed": {"from": "inbox/transcripts", "classes": ["Decision"], "max_facts": 50}}
    with open(packs.path_for(directory), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    capsys.readouterr()
    code, out = _cli("ontology", "update", "--project", root)
    assert code == 0, out
    assert "routes" in out and "fleet @2" in out and "guardrailed" in out and "kept" in out, "it says what moved and what the project kept: " + out
    config = _read(root)
    assert config["routes"]["guardrailed"]["max_facts"] == 5, "the project's key stays"
    assert config["routes"]["allowed"] == ["session", "reviewed"] and config["routes"]["session"] == {"classes": ["System"]}, "the pack's keys moved"
    [record] = config["routes_from"]
    assert record["release"] == 2 and record["keys"] == ["allowed", "session"], record
    assert main(["status", "--project", root]) == 0
    out = capsys.readouterr().out
    assert "from the pack fleet @2" in out and "guardrailed" in out and "here" in out, "status says which keys are the project's: " + out


# ---- the gate reads the policy ----

def _repository_with(root, routes):
    project = _project(root)
    config = json.load(open(project.config_path, encoding="utf-8"))
    config["routes"] = routes
    with open(project.config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    _git(root, "init", "-q", "-b", "main")
    return project, _commit(root, "the project")


def _apply(project, nodes, by, confirm):
    session.start(project)
    candidate = session.candidate(project)
    candidate["nodes"].extend(nodes)
    with open(session.candidate_path(project), "w", encoding="utf-8") as f:
        json.dump(candidate, f)
    code, out = _cli("curate", "apply", "--project", project.data, "--by", by, "--note", "a change", "--force", *(["--confirm"] if confirm else []))
    assert code == 0, out


def test_a_route_the_policy_does_not_allow_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository_with(root, {"allowed": ["session", "reviewed"], "guardrailed": {"from": "inbox/transcripts", "attributed": False}})
        os.makedirs(project.layout.runs, exist_ok=True)
        with open(os.path.join(project.layout.runs, "20261102-1.json"), "w", encoding="utf-8") as f:
            json.dump({"run_id": "20261102-1", "started": "2026-11-02T10:00:00", "inbox": os.path.join(root, "inbox", "transcripts"),
                       "strict_privacy": True, "files": [{"file": "standup.md", "sha256": "abc", "outcome": "extracted", "slug": "standup"}], "completed": False}, f)
        _apply(project, [_node("c.2", sources=["standup"], source_doc="standup")], by="oto pipeline", confirm=False)
        head = _commit(root, "the standup")
        shown = route.show(root, base, head)
        assert shown["proposed"] == route.GUARDRAILED and shown["route"] == route.REVIEWED
        assert any("not allowed" in r and "guardrailed" in r for r in shown["reasons"]), shown["reasons"]
        assert not route.check(root, base, head, authors=["oto pipeline"], verified=True)["ok"]
        assert route.check(root, base, head, authors=["oto pipeline"], verified=True, approved=True)["ok"]


def test_a_session_change_outside_the_classes_the_policy_names_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository_with(root, {"allowed": ["session", "reviewed", "guardrailed"], "session": {"classes": ["Claim"]}})
        _git(root, "checkout", "-q", "-b", "claim")
        _apply(project, [_node("c.2")], by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "a claim")
        assert route.show(root, base, head)["route"] == route.SESSION, "a Claim is a class a session may change"
        _git(root, "checkout", "-q", "main")
        _apply(project, [_node("p.2", "Party")], by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "a party")
        shown = route.show(root, base, head)
        assert shown["proposed"] == route.SESSION and shown["route"] == route.REVIEWED
        assert any("Party" in r and "Claim" in r for r in shown["reasons"]), shown["reasons"]
        assert not route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=True)["ok"]


def _rewrite_routes(project, change):
    config = json.load(open(project.config_path, encoding="utf-8"))
    change(config["routes"])
    with open(project.config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def test_a_pull_request_is_held_to_the_policy_of_its_base_and_one_that_rewrites_the_policy_goes_to_a_person():
    with tempfile.TemporaryDirectory() as root:
        project, base = _repository_with(root, {"allowed": ["session", "reviewed"], "session": {"classes": ["Claim"]}})
        _git(root, "checkout", "-q", "-b", "widen")
        _rewrite_routes(project, lambda routes: routes["session"]["classes"].append("Party"))
        _apply(project, [_node("p.2", "Party")], by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "a party, and a policy that lets it through")
        shown = route.show(root, base, head)
        assert shown["proposed"] == route.SESSION and shown["route"] == route.REVIEWED, shown
        assert any("Party" in r and "Claim" in r for r in shown["reasons"]), "the base's policy decides: " + str(shown["reasons"])
        assert any("routes" in r and "policy" in r for r in shown["reasons"]), "rewriting the policy is a person's to approve: " + str(shown["reasons"])
        assert not route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=True)["ok"]
        # a change to the policy that does not touch this change's classes is still the policy's change
        _git(root, "checkout", "-q", "main")
        _git(root, "checkout", "-q", "-b", "transcripts")
        _rewrite_routes(project, lambda routes: routes.update(guardrailed={"from": "inbox/transcripts", "classes": ["Claim"]}))
        _apply(project, [_node("c.3")], by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "a claim, and a transcripts folder")
        shown = route.show(root, base, head)
        assert shown["route"] == route.REVIEWED and any("policy" in r for r in shown["reasons"]), shown["reasons"]


def test_a_stale_branch_is_not_taken_for_a_change_to_the_policy():
    with tempfile.TemporaryDirectory() as root:
        project, first = _repository_with(root, {"allowed": ["session", "reviewed"], "session": {"classes": ["Claim"]}})
        _git(root, "checkout", "-q", "-b", "claim")
        _apply(project, [_node("c.2")], by="chiheb@cynergis.ai", confirm=True)
        head = _commit(root, "a claim")
        _git(root, "checkout", "-q", "main")
        _rewrite_routes(project, lambda routes: routes["session"]["classes"].append("Party"))
        base = _commit(root, "main widens the policy, after the branch was cut")
        shown = route.show(root, base, head)
        assert not any("policy" in r for r in shown["reasons"]), "the branch did not touch the policy: " + str(shown["reasons"])


def test_a_change_that_touches_the_lock_or_the_workflows_goes_to_a_person():
    for path in ("oto.lock.json", os.path.join(".github", "workflows", "oto-route.yml"), os.path.join(".github", "oto-rules.json")):
        with tempfile.TemporaryDirectory() as root:
            project, base = _repository_with(root, {"allowed": ["session", "reviewed"]})
            _git(root, "checkout", "-q", "-b", "change")
            _apply(project, [_node("c.2")], by="chiheb@cynergis.ai", confirm=True)
            target = os.path.join(root, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write("# edited by the pull request\n")
            head = _commit(root, "a claim, and what the gate itself runs on")
            shown = route.show(root, base, head)
            assert shown["proposed"] == route.SESSION and shown["route"] == route.REVIEWED, (path, shown)
            assert any(path.replace(os.sep, "/") in r for r in shown["reasons"]), (path, shown["reasons"])
            assert not route.check(root, base, head, authors=["chiheb@cynergis.ai"], verified=True)["ok"]
