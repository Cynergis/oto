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
        assert server["command"] == "uvx" and "git+" + repo.ENGINE in " ".join(server["args"])
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
        assert 'pip install "oto-kg[intake] @ git+${ENGINE}"' in text
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
    assert "https://example.com/fork" in files[".mcp.json"]
    assert "https://example.com/fork" in files["CLAUDE.md"]
    assert "'https://example.com/fork'" in files[os.path.join(".github", "workflows", "oto-checks.yml")]


def test_the_plugin_runs_the_engine_through_uvx():
    mcp = json.load(open(os.path.join(ROOT, ".mcp.json"), encoding="utf-8"))
    server = mcp["mcpServers"]["oto"]
    assert server["command"] == "uvx" and server["args"][:2] == ["--from", "${OTO_SOURCE:-oto-kg @ git+" + repo.ENGINE + "}"], \
        "the published engine, unless OTO_SOURCE names a checkout"
    assert server["args"][2:] == ["oto", "serve", "--project", "${CLAUDE_PROJECT_DIR}"]
    hooks = json.load(open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8"))
    command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert command.startswith('uvx --from "${OTO_SOURCE:-oto-kg @ git+' + repo.ENGINE + '}"') and "oto status" in command


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
log.append({"args": sys.argv[1:], "token": os.environ.get("GH_TOKEN")})
json.dump(log, open(path, "w"))
if "--method" not in sys.argv:
    sys.stdout.write(os.environ.get("FAKE_GH_LIST", "[]")); sys.exit(0)
sys.stdout.write('{"id": 7, "name": "oto main"}'); sys.exit(0)
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
        assert any(a["actor_type"] == "Integration" for a in rules["bypass_actors"]), "the ingest workflow pushes its run commit"
        checks = open(os.path.join(root, ".github", "workflows", "oto-checks.yml"), encoding="utf-8").read()
        assert "name: oto checks" in checks.split("jobs:")[1], "the job carries the name the rules require"
        guide = open(os.path.join(root, "CLAUDE.md"), encoding="utf-8").read()
        assert "route" in guide


def test_repo_rules_apply_sets_the_rules_through_the_github_cli(tmp_path, monkeypatch, capsys):
    root = str(tmp_path / "board")
    assert main(["init", "--name", "Board", "--project", root, "--repo"]) == 0
    gh = tmp_path / "gh"
    gh.write_text("#!/usr/bin/env python3\n" + FAKE_GH_API)
    gh.chmod(0o755)
    log = tmp_path / "gh.json"
    monkeypatch.setenv("OTO_GH", str(gh))
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    capsys.readouterr()
    assert main(["repo", "rules", "--project", root]) == 0
    assert "oto main" in capsys.readouterr().out and not log.exists(), "without --apply it only shows the rules"
    result = repo.apply_rules(root, "acme/board", token="ghp-like-but-not")
    assert result == {"created": True, "id": 7}
    calls = json.load(open(log))
    assert calls[0]["args"][:2] == ["api", "repos/acme/board/rulesets"]
    assert calls[1]["args"][:4] == ["api", "--method", "POST", "repos/acme/board/rulesets"] and "--input" in calls[1]["args"]
    assert all(c["token"] == "ghp-like-but-not" for c in calls), "the token reaches the CLI through its environment, never a file"
    # an existing ruleset of that name is replaced, not duplicated
    monkeypatch.setenv("FAKE_GH_LIST", '[{"id": 7, "name": "oto main"}]')
    assert repo.apply_rules(root, "acme/board") == {"created": False, "id": 7}
    assert json.load(open(log))[-1]["args"][:4] == ["api", "--method", "PUT", "repos/acme/board/rulesets/7"]
    assert main(["repo", "rules", "--apply", "--repo", "acme/board", "--project", root]) == 0
    assert "replaced" in capsys.readouterr().out
