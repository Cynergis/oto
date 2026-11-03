"""A project laid out for GitHub, and a plugin that installs the engine on demand."""
import json
import os
import tempfile

from oto import repo
from oto.cli import main
from oto.project import Project

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_init_repo_writes_the_repository_files(capsys):
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--name", "Acme Claims", "--project", root, "--ontology", "auto-claims", "--repo"]) == 0
        out = capsys.readouterr().out
        assert "laid out to live in a GitHub repository" in out
        for relative in (".mcp.json", "CLAUDE.md", ".gitignore",
                         ".github/workflows/oto-ingest.yml", ".github/workflows/oto-checks.yml",
                         ".github/workflows/oto-deploy.yml", ".github/workflows/oto-author.yml",
                         ".github/workflows/oto-review.yml"):
            assert os.path.exists(os.path.join(root, relative)), relative
        mcp = json.load(open(os.path.join(root, ".mcp.json"), encoding="utf-8"))
        server = mcp["mcpServers"]["acme-claims-kg"]
        assert server == {"command": "oto", "args": ["serve", "--project", "."]}, "the installed engine serves (ADR-0014)"
        assert server["args"][-2:] == ["--project", "."]
        gitignore = open(os.path.join(root, ".gitignore"), encoding="utf-8").read()
        assert "build/*" in gitignore and "!build/documents/" in gitignore, "the corpus is committed"
        claude = open(os.path.join(root, "CLAUDE.md"), encoding="utf-8").read()
        assert "Acme Claims" in claude and "pull request" in claude
        # The project still builds as a normal project.
        assert main(["build", "--project", root]) == 0
        assert os.path.exists(Project.standard(root).layout.database)


def test_workflows_install_the_engine_from_its_repository_and_run_the_gates():
    files = repo.files("acme", "Acme")
    ingest = files[os.path.join(".github", "workflows", "oto-ingest.yml")]
    checks = files[os.path.join(".github", "workflows", "oto-checks.yml")]
    deploy = files[os.path.join(".github", "workflows", "oto-deploy.yml")]
    author = files[os.path.join(".github", "workflows", "oto-author.yml")]
    review = files[os.path.join(".github", "workflows", "oto-review.yml")]
    for text in (ingest, checks, deploy, author, review):
        assert 'pip install "oto-kg[intake] @ git+${ENGINE}${ENGINE_REF}"' in text, "the engine at the ref the lock records (phase 4)"
        assert "vars.OTO_ENGINE || '%s'" % repo.ENGINE in text
        assert 'OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}' in text, "a private engine repository needs a token"
        assert 'insteadOf "https://github.com/"' in text
    assert 'paths: [ "inbox/**" ]' in ingest and "oto ingest --project ." in ingest
    assert "git add -A inbox processing errors runs build/documents" in ingest
    assert "gh issue create" in ingest
    assert "on:\n  pull_request:" in checks
    for gate in ("oto curate check", "oto build --project .", "oto ontology check --project . --strict",
                 "oto bench validate", "oto vet"):
        assert gate in checks, gate
    assert "upload-artifact" in deploy and "build/acme.db" in deploy
    assert "query repository" in deploy and 'if: vars.OTO_QUERY_REPO != \'\'' in deploy
    assert "oto build --project . --only site --target site --view \"${{ vars.OTO_SITE_VIEW }}\"" in deploy
    assert "vars.OTO_SITE_VIEW != '' && '--site' || ''" in deploy, "the site goes beside the store only when an app is named"
    assert '"oto author" workflow follows' in ingest, "the authoring workflow follows the ingest"


def test_engine_url_can_be_overridden():
    files = repo.files("x", "X", engine="https://example.com/fork")
    assert json.loads(files[".mcp.json"])["mcpServers"]["x-kg"]["command"] == "oto", "the installed engine serves (ADR-0014)"
    assert "https://example.com/fork" in files["CLAUDE.md"]
    assert "'https://example.com/fork'" in files[os.path.join(".github", "workflows", "oto-checks.yml")]


def test_init_repo_is_idempotent_and_keeps_edits(capsys):
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--name", "Kept", "--project", root, "--repo"]) == 0
        path = os.path.join(root, "CLAUDE.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\nMy own note.\n")
        assert main(["init", "--name", "Kept", "--project", root, "--repo"]) == 0
        assert "My own note." in open(path, encoding="utf-8").read(), "a second init must not overwrite edits"


def test_the_author_workflow_runs_the_agent_with_the_plugin_and_opens_the_pull_request():
    files = repo.files("acme", "Acme")
    author = files[os.path.join(".github", "workflows", "oto-author.yml")]
    assert 'workflows: [ "oto ingest" ]' in author and "workflow_dispatch" in author
    assert "oto ingest runs --project . --open" in author, "the run is found from the manifests"
    assert 'git checkout -b "oto/run-${{ steps.run.outputs.id }}"' in author
    assert "uses: anthropics/claude-code-action@v1" in author
    assert "anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}" in author
    assert "plugin_marketplaces:" in author and "oto@cynergis-engine" in author, "the pipeline agent gets the same skills"
    assert '--allowedTools "Bash(oto:*)' in author and "Bash(git:*)" not in author.split("prompt:")[0].split("claude_args")[1], \
        "the authoring agent never commits; the workflow does"
    assert "references/pipeline-run.md" in author and "BLOCKED:" in author
    assert "A transcripts run" in author, "a transcripts run follows the reference's section, where its rules are written"
    assert 'gh pr create --base main --head "oto/run-${RUN_ID}"' in author and "--body-file" in author
    assert "oto-run,blocked" in author, "a blocked run still opens a pull request, labelled"
    assert "git add -A" in author and "git push -u origin" in author
    assert "vars.OTO_MODEL || 'claude-opus-5'" in author
    assert "concurrency:\n  group: oto-author" in author


def test_the_review_workflow_answers_claude_mentions_on_pull_requests():
    files = repo.files("acme", "Acme")
    review = files[os.path.join(".github", "workflows", "oto-review.yml")]
    assert "issue_comment:" in review and "pull_request_review_comment:" in review
    assert "contains(github.event.comment.body, '@claude')" in review
    assert "github.event.issue.pull_request" in review, "only pull requests, not plain issues"
    assert "oto@cynergis-engine" in review and "prompt:" not in review, "the mention is the prompt"
    assert "Bash(git:*)" in review, "the action pushes the revision itself"


def test_the_repository_guide_describes_the_pull_request_gate():
    files = repo.files("acme", "Acme")
    guide = files["CLAUDE.md"]
    for phrase in ("oto/run-<id>", "runs/<id>.report.md", "@claude", "status checks"):
        assert phrase in guide, phrase
    ingest = files[os.path.join(".github", "workflows", "oto-ingest.yml")]
    assert '"oto author" workflow follows' in ingest


# ---- the route gate and the branch rules (docs/plans/graph-journeys.md, phase 2) ----

FAKE_GH_API = r'''
import json, os, sys
path = os.environ["FAKE_GH_LOG"]
log = json.load(open(path)) if os.path.exists(path) else []
args = sys.argv[1:]
stdin = sys.stdin.read() if args[:2] == ["secret", "set"] else None
log.append({"args": args, "token": os.environ.get("GH_TOKEN"), "stdin": stdin})
json.dump(log, open(path, "w"))
method = args[args.index("--method") + 1] if "--method" in args else "GET"
target = [a for a in args[1:] if a.startswith("repos/") or a == "user"][:1]
target = target[0] if target else ""
def answer(text, code=0):
    sys.stdout.write(text); sys.exit(code)
if args[:2] == ["secret", "set"]:
    answer("")
if target == "user":
    answer('{"login": "dana"}')
if target.endswith("/rulesets") and method == "GET":
    answer(os.environ.get("FAKE_GH_LIST", "[]"))
if "/rulesets" in target:
    answer('{"id": 7, "name": "oto main"}')
if "/contents/.github/CODEOWNERS" in target:
    if os.environ.get("FAKE_GH_NO_CODEOWNERS"):
        sys.stderr.write("gh: Not Found (HTTP 404)\n"); sys.exit(1)
    answer('{"path": ".github/CODEOWNERS"}')
if target.endswith("/codeowners/errors"):
    answer('{"errors": []}')
if target.endswith("/keys") and method == "GET":
    answer(os.environ.get("FAKE_GH_KEYS", "[]"))
if target.endswith("/keys"):
    answer('{"id": 11}')
if target.endswith("/deployment-branch-policies") and method == "GET":
    answer(os.environ.get("FAKE_GH_POLICIES", '{"branch_policies": []}'))
if method in ("DELETE", "PUT", "POST"):
    answer("{}")
if target.count("/") == 2:
    answer('{"default_branch": "main"}')
answer("{}")
'''

FAKE_KEYGEN = r'''
import sys
path = sys.argv[sys.argv.index("-f") + 1]
open(path, "w").write("a fake key: private-key-material\n")
open(path + ".pub", "w").write("ssh-ed25519 AAAAC3fake oto main pushes\n")
'''


def test_init_repo_writes_the_route_gate_and_the_branch_rules():
    with tempfile.TemporaryDirectory() as root:
        assert main(["init", "--name", "Board", "--project", root, "--repo"]) == 0
        workflow = open(os.path.join(root, ".github", "workflows", "oto-route.yml"), encoding="utf-8").read()
        assert "name: oto route" in workflow and "pull_request_review" in workflow, "runs on the pull request and on every review"
        assert "oto route check" in workflow and "--author" in workflow and "--verified" in workflow and "--approved" in workflow
        assert "oto-route:reviewed" in workflow, "a failing session record or guardrail labels the pull request"
        assert "fetch-depth: 0" in workflow, "both trees are needed"
        rules = json.load(open(os.path.join(root, ".github", "oto-rules.json"), encoding="utf-8"))
        assert rules["name"] == repo.RULES_NAME == "oto main" and rules["target"] == "branch" and rules["enforcement"] == "active"
        kinds = {r["type"]: r for r in rules["rules"]}
        assert kinds["pull_request"]["parameters"]["required_approving_review_count"] == 0, "approvals are the route gate's, per route"
        contexts = {c["context"] for c in kinds["required_status_checks"]["parameters"]["required_status_checks"]}
        assert contexts == {"oto checks", "oto route"}
        assert "merge_queue" in kinds, "graph.json merges one pull request at a time"
        actors = {(a["actor_type"], a.get("actor_id"), a["bypass_mode"]) for a in rules["bypass_actors"]}
        assert actors == {("DeployKey", None, "always"), ("RepositoryRole", 5, "pull_request")}, \
            "only the deploy key kept for main pushes past the rules, and an administrator by a pull request; never GitHub Actions, " \
            "whose token any workflow on any branch can ask for: " + str(actors)
        assert kinds["pull_request"]["parameters"]["require_code_owner_review"] is True, \
            "a change to what the gate runs on (.github/, the lock) needs a code owner's approval, which GitHub holds, not the gate"
        checks = open(os.path.join(root, ".github", "workflows", "oto-checks.yml"), encoding="utf-8").read()
        assert "name: oto checks" in checks.split("jobs:")[1], "the job carries the name the rules require"
        guide = open(os.path.join(root, "CLAUDE.md"), encoding="utf-8").read()
        assert "route" in guide


def _fake_github(tmp_path, monkeypatch):
    gh = tmp_path / "gh"
    gh.write_text("#!/usr/bin/env python3\n" + FAKE_GH_API)
    gh.chmod(0o755)
    keygen = tmp_path / "ssh-keygen"
    keygen.write_text("#!/usr/bin/env python3\n" + FAKE_KEYGEN)
    keygen.chmod(0o755)
    log = tmp_path / "gh.json"
    monkeypatch.setenv("OTO_GH", str(gh))
    monkeypatch.setenv("OTO_SSH_KEYGEN", str(keygen))
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    return lambda: json.load(open(log)) if log.exists() else []


def test_repo_rules_apply_sets_the_code_owners_the_deploy_key_for_main_and_the_rules(tmp_path, monkeypatch, capsys):
    root = str(tmp_path / "board")
    assert main(["init", "--name", "Board", "--project", root, "--repo"]) == 0
    calls = _fake_github(tmp_path, monkeypatch)
    capsys.readouterr()
    assert main(["repo", "rules", "--project", root]) == 0
    assert "oto main" in capsys.readouterr().out and not calls(), "without --apply it only shows the rules"

    # the code owners must be on main before the rules ask for them: written here, then a stop
    monkeypatch.setenv("FAKE_GH_NO_CODEOWNERS", "1")
    try:
        repo.apply_rules(root, "acme/board", token="ghp-like-but-not")
        raise AssertionError("the rules were set before the code owners were on main")
    except Exception as exc:                          # ProjectError
        assert "CODEOWNERS" in str(exc) and "main" in str(exc) and "push" in str(exc), exc
    owners = open(os.path.join(root, ".github", "CODEOWNERS"), encoding="utf-8").read()
    assert "/.github/ @dana" in " ".join(owners.split()) and "/oto.lock.json @dana" in " ".join(owners.split()), \
        "the signed-in person owns the gate's own files: " + owners
    assert not [c for c in calls() if "/rulesets" in " ".join(c["args"])], "no rules without the code owners"

    # with the code owners on main: the environment, the key, the secret, then the rules
    monkeypatch.delenv("FAKE_GH_NO_CODEOWNERS")
    monkeypatch.setenv("FAKE_GH_KEYS", '[{"id": 4, "title": "oto main pushes"}, {"id": 5, "title": "someone else\'s key"}]')
    monkeypatch.setenv("FAKE_GH_POLICIES", '{"branch_policies": [{"id": 9, "name": "*"}]}')
    result = repo.apply_rules(root, "acme/board", token="ghp-like-but-not")
    assert result["created"] is True and result["id"] == 7 and result["code_owner"] == "@dana" and result["environment"] == "oto-main", result
    log = calls()
    flat = [" ".join(c["args"]) for c in log]
    assert any(f.startswith("api --method DELETE repos/acme/board/keys/4") for f in flat), "the earlier key for main is replaced"
    assert not any("keys/5" in f for f in flat), "a key OTO did not make is left alone"
    added = [c["args"] for c in log if c["args"][:4] == ["api", "--method", "POST", "repos/acme/board/keys"]]
    assert added and "read_only=false" in added[0] and "key=ssh-ed25519 AAAAC3fake oto main pushes" in added[0], added
    assert any(f.startswith("api --method PUT repos/acme/board/environments/oto-main") for f in flat)
    assert any(f.startswith("api --method DELETE repos/acme/board/environments/oto-main/deployment-branch-policies/9") for f in flat), \
        "the environment deploys from main alone"
    assert any(f.startswith("api --method POST repos/acme/board/environments/oto-main/deployment-branch-policies") and "name=main" in f for f in flat)
    [secret] = [c for c in log if c["args"][:2] == ["secret", "set"]]
    assert secret["args"][2] == "OTO_MAIN_DEPLOY_KEY" and "--env" in secret["args"] and "oto-main" in secret["args"], secret["args"]
    assert "private-key-material" in secret["stdin"] and not any("private-key-material" in a for c in log for a in c["args"]), \
        "the private half reaches the secret on stdin, never as an argument"
    for folder, _dirs, names in os.walk(str(tmp_path)):
        for name in names:
            if name not in ("gh.json", "gh", "ssh-keygen"):     # the log and the two fakes themselves
                assert "private-key-material" not in open(os.path.join(folder, name), encoding="utf-8", errors="replace").read(), \
                    "the private half is left in no file: " + os.path.join(folder, name)
    order = [i for i, f in enumerate(flat) if "rulesets" in f and "--method" in f]
    assert order and order[0] > max(i for i, f in enumerate(flat) if f.startswith("secret set")), "the rules last, once main's key is in place"
    assert all(c["token"] == "ghp-like-but-not" for c in log), "the token reaches the CLI through its environment, never a file"

    # an existing ruleset of that name is replaced, not duplicated; the command says what it set
    monkeypatch.setenv("FAKE_GH_LIST", '[{"id": 7, "name": "oto main"}]')
    assert repo.apply_rules(root, "acme/board")["created"] is False
    assert calls()[-1]["args"][:4] == ["api", "--method", "PUT", "repos/acme/board/rulesets/7"]
    capsys.readouterr()
    assert main(["repo", "rules", "--apply", "--repo", "acme/board", "--project", root]) == 0
    out = capsys.readouterr().out
    assert "replaced" in out and "@dana" in out and "oto-main" in out and "deploy key" in out, out


def test_repo_rules_apply_takes_the_code_owner_it_is_given(tmp_path, monkeypatch):
    root = str(tmp_path / "board")
    assert main(["init", "--name", "Board", "--project", root, "--repo"]) == 0
    _fake_github(tmp_path, monkeypatch)
    result = repo.apply_rules(root, "acme/board", code_owner="acme/maintainers")
    assert result["code_owner"] == "@acme/maintainers"
    assert "@acme/maintainers" in open(os.path.join(root, ".github", "CODEOWNERS"), encoding="utf-8").read()


def test_the_workflows_that_push_to_main_use_the_deploy_key_kept_for_main_and_trigger_nothing():
    files = repo.files("acme", "Acme", architecture=True)
    for name in ("oto-ingest.yml", "oto-architecture.yml"):
        text = files[os.path.join(".github", "workflows", name)]
        assert "environment: oto-main" in text, "%s: the key is in an environment only main may deploy from" % name
        assert "ssh-key: ${{ secrets.OTO_MAIN_DEPLOY_KEY }}" in text, name
        # its own token may still write, so a repository without the rules works; once they are set, that token
        # cannot reach main (GitHub Actions is no bypass actor) and only the key can
        assert "[skip ci]" in text, "%s: its commit starts no workflow, as a commit by the workflow's token never did" % name
    for relative, text in files.items():
        if relative.endswith(".yml") and "environment: oto-main" not in text:
            for line in text.splitlines():
                if "git push" in line and "--delete" not in line:
                    assert "origin \"oto/" in line or "-u origin" in line, "%s pushes to main without the key: %s" % (relative, line.strip())


# ---- the preview per pull request and the pinned engine (docs/plans/graph-journeys.md, phase 4) ----

def test_every_workflow_pins_the_engine_to_the_lock_and_the_checks_hold_the_machine_to_it():
    files = repo.files("acme", "Acme")
    for relative, text in files.items():
        if not relative.endswith(".yml"):
            continue
        installs = text.count("Install the engine from its repository")
        assert installs, relative
        assert text.count("Pin the engine to the lock") == installs, "%s: every install is preceded by the pin" % relative
        assert text.index("Pin the engine to the lock") < text.index("Install the engine from its repository"), relative
        assert "oto.lock.json" in text and "ENGINE_REF" in text, relative
    checks = files[os.path.join(".github", "workflows", "oto-checks.yml")]
    assert "oto lock --check --project ." in checks, "drift between the lock and the installed engine fails the pull request"
    assert "if [ -f oto.lock.json ]" in checks, "a project without a lock is not failed for it"


def test_a_preview_is_built_for_every_pull_request_and_cleaned_up_when_it_closes():
    files = repo.files("acme", "Acme")
    preview = files[os.path.join(".github", "workflows", "oto-preview.yml")]
    assert "name: oto preview" in preview and "types: [opened, synchronize, reopened, closed]" in preview
    assert "oto build --project ." in preview
    assert 'oto publish --project . --repo "${{ vars.OTO_QUERY_REPO }}" --branch "preview/pr-${PR}"' in preview, "the store at the head, on a branch of the query repository"
    assert "vars.OTO_SITE_VIEW != '' && '--site' || ''" in preview, "the workbench beside it when an app is named"
    assert "upload-artifact" in preview and "build/acme.db" in preview, "without a query repository the store is kept as an artifact"
    assert "gh pr comment" in preview and "--edit-last" in preview, "one comment per pull request, edited on every push"
    assert "github.event.action == 'closed'" in preview and '--delete "preview/pr-${PR}"' in preview, "the branch goes when the pull request closes"
    guide = files["CLAUDE.md"]
    assert "preview" in guide.lower()
