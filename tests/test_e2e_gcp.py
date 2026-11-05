"""The guide to OTO on Google Cloud (docs/E2E-GCP.md). Nothing here can run Google Cloud, so this holds what can be held: every `oto` command in it is one
the engine parses, every setting and workflow it names is one the workflows read, each identity gets the roles ADR-0015 says it needs, and the guide says
plainly what has never run. tests/test_server.py runs the deploy step and the server themselves, with stand-ins for Google."""
import os
import re
import shlex

import pytest

from oto import connections, repo
from oto.cli import build_parser
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "docs", "E2E-GCP.md")
WIDER = os.path.join(ROOT, "docs", "E2E-TESTING.md")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def guide():
    return _read(GUIDE)


def _commands(text):
    """Every command in the guide's shell blocks, as words: joined across backslashes, comments gone, split at &&, an environment setting in front dropped."""
    out = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            words = shlex.split(line, comments=True)
            part = []
            for word in words + ["&&"]:
                if word != "&&":
                    part.append(word)
                    continue
                while part and re.match(r"^[A-Z_]+=", part[0]):
                    part.pop(0)
                if part:
                    out.append(part)
                part = []
    return out


def test_every_oto_command_in_the_guide_is_one_the_engine_parses(guide):
    found = [c for c in _commands(guide) if c[0] == "oto"]
    assert len(found) > 15, "the guide's commands weren't found"
    for command in found:
        try:
            build_parser().parse_args(command[1:])
        except SystemExit:
            pytest.fail("the engine refuses: %s" % " ".join(command))


def test_the_guide_makes_a_new_pack_and_leaves_the_old_one_alone(guide):
    assert "export PACK=kanban-board" in guide
    commands = _commands(guide)
    assert ["oto", "pack", "add", "$PACK"] in commands, "the pack the guide publishes is the one it installs"
    assert any(c[:2] == ["oto", "pack"] and "publish" in c for c in commands)
    assert not re.search(r"(--pack|--name|pack add|init --pack) kanban\b(?!-)", guide), "a pack called kanban would replace the registry's as its next release"


def _set_in_guide(guide):
    return {c[3] for c in _commands(guide) if c[:3] == ["gh", "variable", "set"]}


def _read_by_workflows():
    deploy = repo.DEPLOY[repo.DEPLOY.index("Sign in to Google Cloud"):repo.DEPLOY.index("Keep the store")]
    return set(re.findall(r"vars\.(OTO_[A-Z_]+)", deploy + repo.SERVER_WORKFLOW))


def test_the_guide_sets_every_setting_the_workflows_read(guide):
    optional = {"OTO_ENGINE", "OTO_SERVER_MEMORY"}          # the engine's own repository, and the container's memory, each with a default
    assert _set_in_guide(guide) == _read_by_workflows() - optional


def test_the_guide_turns_off_the_copy_it_doesnt_use(guide):
    """`oto sandbox up --repo` names a store repository, and the deploy fails at the end without a token to write to it."""
    assert 'gh variable delete OTO_QUERY_REPO --repo "$ORG/$GRAPH"' in guide
    assert "OTO_QUERY_REPO" in _read(os.path.join(ROOT, "oto", "sandbox.py")) and "vars.OTO_QUERY_REPO != ''" in repo.DEPLOY


def test_the_workflows_it_runs_are_ones_a_graph_has(guide, tmp_path, capsys):
    named = {c[3] for c in _commands(guide) if c[:3] == ["gh", "workflow", "run"]}
    assert named == {"oto-deploy.yml", "oto-server.yml"}
    init(str(tmp_path), slug="team-board", name="Team Board", repo=True)
    for workflow in named:
        assert os.path.exists(tmp_path / ".github" / "workflows" / workflow)


def test_each_identity_gets_what_the_decision_says_it_needs(guide):
    adr = _read(os.path.join(ROOT, "docs", "adr", "0015-bigquery-holds-the-graph.md"))
    for role in ("roles/bigquery.dataViewer", "roles/bigquery.dataEditor", "roles/bigquery.jobUser"):
        assert role in adr, role
    assert re.search(r"GRANT \\`roles/bigquery\.dataEditor\\` ON SCHEMA .*serviceAccount:\$LOAD", guide)
    assert re.search(r"GRANT \\`roles/bigquery\.dataViewer\\` ON SCHEMA .*serviceAccount:\$READ", guide)
    assert re.search(r'--member="serviceAccount:\$LOAD" --role=roles/bigquery\.jobUser', guide)
    assert re.search(r'serviceAccount:\$READ.*dataEditor|serviceAccount:\$READ.*jobUser', guide) is None, "the server only reads"
    assert re.search(r"--role=roles/run\.builder", guide), "the build runs as the project's default identity, which Google says may need this granted"
    for variable, identity in (("OTO_GCP_SERVICE_ACCOUNT", "$DEPLOY"), ("OTO_GCP_LOAD_SERVICE_ACCOUNT", "$LOAD"), ("OTO_GCP_RUNTIME_SERVICE_ACCOUNT", "$READ")):
        assert any(c[:4] == ["gh", "variable", "set", variable] and c[c.index("--body") + 1] == identity for c in _commands(guide)), variable


def test_only_main_can_sign_in_to_google(guide):
    """A workflow on a branch can ask for an identity token too, so the provider admits only the environment that deploys from main alone, which both workflows use."""
    assert "assertion.environment == '%s'" % repo.MAIN_ENVIRONMENT in guide
    assert "assertion.repository == '$ORG/$GRAPH'" in guide
    for workflow in (repo.DEPLOY, repo.SERVER_WORKFLOW):
        assert "environment: {main_environment}" in workflow
    assert "deployment-branch-policies" in guide, "the guide checks that the environment really is held to main"
    assert "/attribute.repository/$ORG/$GRAPH" in guide and "/subject/" not in guide, "repositories made since July 2026 have a new default subject"


def test_it_signs_in_the_way_the_engine_says(guide):
    server = "$GRAPH-kg"
    assert connections.secret_command(server) in guide.replace('"mcp:$GRAPH-kg:client_secret"', "mcp:$GRAPH-kg:client_secret")
    assert connections.sign_in_command(server) in guide.replace('"$GRAPH-kg"', "$GRAPH-kg")
    assert "programmatic_clients" in guide and "Desktop app" in guide
    assert "--resource-type=cloud-run" in guide and "roles/iap.httpsResourceAccessor" in guide
    assert "gcloud beta iap web" not in guide and "gcloud beta iap web" not in _read(WIDER), "Google's docs use gcloud iap web"


def test_no_secret_goes_in_a_file_or_a_command(guide):
    assert "client_secret:" not in guide and "clientSecret" not in guide, "the settings file holds the client's id alone"
    assert not re.search(r"--password|--client-secret|GITHUB_TOKEN=[^\"]", guide)
    assert 'GITHUB_TOKEN="$(gh auth token)"' in guide, "the token is used inline, for one command"


def test_the_guide_says_what_has_never_run(guide):
    assert "## What has run, and what hasn't" in guide
    assert "It hasn't run on Google Cloud yet" in guide
    assert "## If it fails" in guide and "redirect_uri_mismatch" in guide, "the sign-in is the step most likely to need the fallback"
    assert "small proxy on the computer" in guide and "not built" in guide


def test_the_wider_guide_points_here():
    wider = _read(WIDER)
    assert "E2E-GCP.md" in wider
    assert "E2E-GCP.md" in _read(os.path.join(ROOT, "README.md"))
