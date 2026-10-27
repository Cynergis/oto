"""The version and diff view (roadmap D6): two vocabularies compared with the impact on the graph,
rendered as text, markdown or JSON; `oto ontology diff --from <ref>` reading the config at a git ref;
the versions model in the payload (current, accepted, what changed since); the same diff served at
/api/ontology/diff; the checks workflow posting it on pull requests; the workbench's Versions page."""
import contextlib
import copy
import io
import json
import os
import subprocess
import tempfile

import pytest

from oto.apps import manifest as apps
from oto.builder import build
from oto.cli import main
from oto.model import ontologies, vocabulary as vocab
from oto.project import Project
from oto.scaffold import init
from oto.serve import versions as _versions

from test_apps import _engine, _get

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKBENCH = os.path.join(ROOT, "oto", "ui", "workbench")
SRC = os.path.join(ROOT, "ui-src", "workbench")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _git(args, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def _config(name="software-architecture"):
    config, _s, _r = ontologies.load(name)
    return copy.deepcopy(config)


def _changed(config):
    """A breaking, an additive and a cosmetic change, with no version bump."""
    new = copy.deepcopy(config)
    del new["classes"]["Runbook"]
    new["properties"]["uses"] = {"domain": "Component", "range": "Interface", "inverse": "used_by", "definition": "Calls it."}
    new["classes"]["Component"]["definition"] = new["classes"]["Component"]["definition"] + " Deployed as one unit."
    return new


# ---- comparing two vocabularies ----

def test_two_configs_compare_with_the_impact_on_the_graph():
    old = _config()
    nodes = [{"id": "runbook.x", "type": "Runbook", "status": "current"}, {"id": "c", "type": "Component", "status": "current"}]
    result = _versions.compare(old, _changed(old), nodes, [])
    assert result["from"] == {"version": old["ontology_version"], "classes": len(old["classes"]), "relations": len(old["properties"]),
                              "attributes": sum(len(v) for v in old.get("attributes", {}).values())}
    assert result["to"]["version"] == old["ontology_version"] and result["to"]["relations"] == len(old["properties"]) + 1
    assert result["counts"] == {"changes": 3, "breaking": 1, "additive": 1, "cosmetic": 1} and result["bump_needed"] is True
    assert [(c["severity"], c["kind"], c["subject"]) for c in result["changes"]] == [
        ("breaking", "class removed", "Runbook"), ("additive", "relation added", "uses"), ("cosmetic", "class described", "Component")]
    assert result["changes"][0]["affected"] == 1 and result["changes"][0]["detail"].startswith("nodes of this type")
    same = _versions.compare(old, old)
    assert same["changes"] == [] and same["counts"]["changes"] == 0 and same["bump_needed"] is False
    bumped = _changed(old)
    bumped["ontology_version"] = old["ontology_version"] + 1
    assert _versions.compare(old, bumped)["bump_needed"] is False, "a breaking change acknowledged by the bump"


def test_rendered_as_text_and_as_markdown():
    old = _config()
    result = _versions.compare(old, _changed(old), [], [], labels=("v1 (HEAD)", "the working tree"))
    text = _versions.render(result, "text")
    assert text.startswith("ontology: 3 change(s) from v1 (HEAD) to the working tree") and "[breaking ] class removed" in text and "Runbook" in text
    assert "1 breaking change(s) with no version bump" in text
    md = _versions.render(result, "markdown")
    assert md.startswith("### Ontology: 3 changes from v1 (HEAD) to the working tree")
    assert "| Severity | Change | Subject | Detail |" in md and "| breaking | class removed | `Runbook` |" in md
    assert "**1 breaking change with no version bump**" in md
    none = _versions.render(_versions.compare(old, old, labels=("a", "b")), "markdown")
    assert none.startswith("### Ontology: no change from a to b")
    assert json.loads(_versions.render(result, "json"))["counts"]["breaking"] == 1


# ---- the command against a git ref ----

@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "estate")
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    _git(["init", "-q", "-b", "main"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "first"], root)
    project = Project.standard(root)
    build(project)                                        # built on the committed vocabulary; the working tree then moves on
    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    with open(project.ontology_config_path, "w", encoding="utf-8") as f:
        json.dump(_changed(config), f, indent=2)
    return root


def test_oto_ontology_diff_reads_the_config_at_a_git_ref(repo):
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--project", repo)
    assert code == 0, out
    assert "3 change(s) from HEAD to the working tree" in out and "class removed" in out and "Runbook" in out and "relation added" in out
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--to", "HEAD", "--project", repo)
    assert code == 0 and "no change from HEAD to HEAD" in out
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--project", repo, "--format", "json")
    assert code == 0 and json.loads(out)["counts"]["breaking"] == 1
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--project", repo, "--format", "markdown")
    assert code == 0 and out.startswith("### Ontology: 3 changes")
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--project", repo, "--strict")
    assert code == 1, "a breaking change with no bump fails --strict"
    code, out = _cli("ontology", "diff", "--from", "nowhere", "--project", repo)
    assert code == 1 and "nowhere" in out and "git" in out


def test_oto_ontology_diff_takes_a_file_in_the_repository(repo, monkeypatch):
    monkeypatch.chdir(repo)
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--file", "ontology.config.json")
    assert code == 0 and "3 change(s)" in out and "Runbook" in out
    code, out = _cli("ontology", "diff", "--from", "HEAD", "--file", "missing.json")
    assert code == 1 and "missing.json" in out


# ---- the versions model in the payload ----

def test_the_versions_model_says_what_changed_since_the_vocabulary_was_accepted(repo):
    project = Project.standard(repo)
    with open(project.ontology_config_path, encoding="utf-8") as f:
        current = json.load(f)
    m = _versions.model(current, repo, [], [])
    assert m["current"] == current["ontology_version"] and m["accepted"] is None and m["since_accepted"] is None
    assert m["git"] is True, "the project is in a git repository, so a ref can be compared"
    vocab.write_lock(project, vocab.Vocabulary.from_config(_config()))
    m = _versions.model(current, repo, [{"id": "r", "type": "Runbook", "status": "current"}], [])
    assert m["accepted"] == current["ontology_version"] and m["since_accepted"]["counts"]["breaking"] == 1
    assert m["since_accepted"]["changes"][0]["subject"] == "Runbook" and m["since_accepted"]["changes"][0]["affected"] == 1
    assert m["since_accepted"]["bump_needed"] is True
    with tempfile.TemporaryDirectory() as plain:
        assert _versions.model(current, plain, [], [])["git"] is False
    assert _versions.model(current, None, [], []) == {"current": current["ontology_version"], "accepted": None, "since_accepted": None, "git": False}


# ---- served ----

def test_served_at_api_ontology_diff_and_in_the_payload(repo):
    from oto.serve import http as _http
    project = Project.standard(repo)
    engine = _engine(project)
    server = _http.Server(engine, "127.0.0.1", 0, app_dir=apps.resolve("workbench", repo), project_root=repo, identity=project.config()).start()
    try:
        status, _c, text = _get(server.url + "/api/ontology/diff?from=HEAD")
        assert status == 200, text
        result = json.loads(text)
        assert result["counts"]["breaking"] == 1 and result["labels"] == ["HEAD", "the working tree"]
        status, _c, text = _get(server.url + "/api/ontology/diff?from=HEAD&to=HEAD")
        assert status == 200 and json.loads(text)["counts"]["changes"] == 0
        status, _c, text = _get(server.url + "/api/ontology/diff")
        assert status == 400 and "from" in text
        status, _c, text = _get(server.url + "/api/ontology/diff?from=nowhere")
        assert status == 400 and "nowhere" in text
        status, _c, text = _get(server.url + "/api/graph?passages=0")
        payload = json.loads(text)
        assert payload["ontology"]["versions"]["current"] == result["to"]["version"] and payload["ontology"]["versions"]["git"] is True
        status, _c, text = _get(server.url + "/api/tools")
        assert "/api/ontology/diff" in text
    finally:
        server.stop()


# ---- the workflow and the workbench ----

def test_the_checks_workflow_posts_the_ontology_diff_on_pull_requests():
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        ci = f.read()
    assert "ontology-diff:" in ci and "oto ontology diff --from" in ci and "--format markdown" in ci
    assert "pull-requests: write" in ci and "gh " in ci and "oto-ontology-diff" in ci, "one sticky comment, found again by its marker"
    assert "fetch-depth: 0" in ci.split("ontology-diff:")[1], "the base ref must be reachable"


def test_the_workbench_has_a_versions_page():
    with open(os.path.join(WORKBENCH, "workbench.js"), encoding="utf-8") as f:
        bundle = f.read()
    assert "#/ontology/versions" in bundle and "api/ontology/diff" in bundle
    assert os.path.exists(os.path.join(SRC, "views", "Versions.tsx"))
    with open(os.path.join(SRC, "types.ts"), encoding="utf-8") as f:
        types = f.read()
    assert "OntologyVersions" in types and "VersionDiff" in types
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "/api/ontology/diff" in text and "oto ontology diff" in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "## 27." in e2e and "oto ontology diff --from" in e2e
