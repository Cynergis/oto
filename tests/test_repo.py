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
    assert "oto build --project . --only site --target site --app \"${{ vars.OTO_SITE_VIEW }}\"" in deploy
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
    assert "plugin_marketplaces:" in author and "oto@oto" in author, "the pipeline agent gets the same skills"
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
    assert "oto@oto" in review and "prompt:" not in review, "the mention is the prompt"
    assert "Bash(git:*)" in review, "the action pushes the revision itself"


def test_the_repository_guide_describes_the_pull_request_gate():
    files = repo.files("acme", "Acme")
    guide = files["CLAUDE.md"]
    for phrase in ("oto/run-<id>", "runs/<id>.report.md", "@claude", "status checks"):
        assert phrase in guide, phrase
    ingest = files[os.path.join(".github", "workflows", "oto-ingest.yml")]
    assert '"oto author" workflow follows' in ingest
