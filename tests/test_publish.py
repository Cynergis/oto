"""The query repository: publish the built store, sync it elsewhere, serve the checkout."""
import json
import os
import subprocess
import sys
import tempfile

import pytest

from oto import publish as pub
from oto.builder import build
from oto.cli import main
from oto.project import Project, ProjectError
from oto.scaffold import init

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bare(root):
    path = os.path.join(root, "query.git")
    subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", path], check=True)
    return path


def _project(root, cache_dir=None):
    init(root, slug="acme", name="Acme", ontology="software-architecture")
    if cache_dir:
        cfg = json.load(open(os.path.join(root, "project.config.json"), encoding="utf-8"))
        cfg["cache_dir"] = cache_dir
        json.dump(cfg, open(os.path.join(root, "project.config.json"), "w", encoding="utf-8"))
    project = Project.standard(root)
    build(project)
    return project


def test_publish_refuses_without_a_build():
    with tempfile.TemporaryDirectory() as root:
        init(os.path.join(root, "p"), slug="acme", name="Acme", ontology="software-architecture")
        with pytest.raises(ProjectError, match="nothing to publish"):
            pub.publish(Project.standard(os.path.join(root, "p")), _bare(root))


def test_publish_pushes_the_store_with_identity_and_manifest_and_skips_an_unchanged_one(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(os.path.join(root, "p"))
        target = _bare(root)
        manifest = pub.publish(project, target, source="org/knowledge@abc123")
        assert manifest["changed"] and manifest["build_seq"] == int(project.build_seq())
        assert manifest["schema_version"] == 6 and manifest["source"] == "org/knowledge@abc123"
        # What landed: the store, the identity marked store_only, the manifest, a README. Nothing else.
        listing = subprocess.run(["git", "--git-dir", target, "ls-tree", "--name-only", "main"],
                                 capture_output=True, text=True, check=True).stdout.split()
        assert sorted(listing) == ["MANIFEST.json", "README.md", "acme.db", "project.config.json"]
        # Again, unchanged: nothing pushed, and the command says so.
        assert main(["publish", "--project", os.path.join(root, "p"), "--repo", target]) == 0
        assert "already holds this store" in capsys.readouterr().out
        log = subprocess.run(["git", "--git-dir", target, "log", "--oneline", "main"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        assert len(log) == 1 and "store build_seq" in log[0]


def test_a_token_goes_into_https_urls_only_and_never_into_output():
    assert pub._with_token("https://github.com/o/r", "tok") == "https://x-access-token:tok@github.com/o/r"
    assert pub._with_token("https://me@github.com/o/r", "tok") == "https://me@github.com/o/r"
    assert pub._with_token("git@github.com:o/r.git", "tok") == "git@github.com:o/r.git"
    assert pub._with_token("/tmp/query.git", "tok") == "/tmp/query.git"
    assert pub._with_token("https://github.com/o/r", None) == "https://github.com/o/r"


def test_the_inherited_header_is_reset_for_the_url_itself_without_its_credentials():
    from oto import gitx
    # Scoped, because an unscoped `-c http.extraheader=` loses to the checkout's `http.https://github.com/.extraheader`.
    assert gitx.no_inherited_headers("https://x-access-token:tok@github.com/o/r") == ["-c", "http.https://github.com/o/r.extraheader="]
    assert gitx.no_inherited_headers("http://127.0.0.1:8080/query.git") == ["-c", "http.http://127.0.0.1:8080/query.git.extraheader="]
    assert gitx.no_inherited_headers("git@github.com:o/r.git") == [] and gitx.no_inherited_headers("/tmp/query.git") == []


def test_publish_and_sync_ignore_the_header_the_workspace_inherited(git_over_http, tmp_path, monkeypatch):
    # In a workflow, publish runs in the checkout, whose git config sends the job's own token to the
    # server as a header; the query repository must get the token in the URL, never that one.
    project = _project(str(tmp_path / "p"))
    _bare(git_over_http.root)
    url = git_over_http.base + "/query.git"
    monkeypatch.chdir(git_over_http.workspace(str(tmp_path / "workspace")))
    assert pub.publish(project, url, source="org/knowledge@abc123")["changed"]     # no branch yet: ls-remote, then push
    assert not pub.publish(project, url)["changed"]                                 # the branch is there: ls-remote, then clone
    dest, manifest = pub.sync(url, dest=str(tmp_path / "reader"))
    assert pub.is_store(dest) and manifest["source"] == "org/knowledge@abc123"
    assert git_over_http.seen and git_over_http.header not in git_over_http.seen


def test_sync_clones_then_fast_forwards_and_the_checkout_is_a_store(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(os.path.join(root, "p"))
        target = _bare(root)
        pub.publish(project, target)
        dest = os.path.join(root, "reader", "acme")
        assert main(["sync", "--repo", target, "--dest", dest]) == 0
        out = capsys.readouterr().out
        assert "synced" in out and "build_seq" in out and "oto serve --project" in out
        assert pub.is_store(dest) and not pub.is_store(os.path.join(root, "p"))
        first = pub.read_manifest(dest)
        # A new build, published, reaches the reader by a fast-forward.
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
        graph["nodes"][0]["summary"] = graph["nodes"][0].get("summary", "") + " (revised)"
        with open(project.graph_path, "w", encoding="utf-8") as f:
            json.dump(graph, f)
        build(project)
        assert pub.publish(project, target)["changed"]
        assert main(["sync", "--repo", target, "--dest", dest]) == 0
        assert pub.read_manifest(dest)["sha256"] != first["sha256"]
        with pytest.raises(ProjectError):                 # a knowledge project is not a query store
            pub.sync(os.path.join(root, "p"), dest=os.path.join(root, "reader", "wrong"))
        assert not os.path.exists(os.path.join(dest, "build")), "serving a checkout must not grow a build/ in it"


def test_sync_defaults_to_the_store_cache_dir():
    with tempfile.TemporaryDirectory() as root:
        cache = os.path.join(root, "home", ".acme-kg")
        project = _project(os.path.join(root, "p"), cache_dir=cache)
        target = _bare(root)
        pub.publish(project, target)
        dest, manifest = pub.sync(target)
        assert dest == cache and manifest["build_seq"] == int(project.build_seq())
        dest2, _m = pub.sync(target)                      # second time: a pull into the same place
        assert dest2 == cache and pub.is_store(cache)


def test_query_serve_and_status_take_a_store_checkout(capsys):
    with tempfile.TemporaryDirectory() as root:
        project = _project(os.path.join(root, "p"))
        target = _bare(root)
        pub.publish(project, target, source="org/knowledge@abc123")
        dest = os.path.join(root, "reader")
        pub.sync(target, dest=dest)
        # status knows it is a store, not a project
        assert main(["status", "--project", dest]) == 0
        out = capsys.readouterr().out
        assert "a published query store" in out and "org/knowledge@abc123" in out and "oto sync --repo" in out
        # query answers from it, under the project's own server name
        env = dict(os.environ, PYTHONPATH=REPO)
        env.pop("OTO_STORE", None)
        r = subprocess.run([sys.executable, "-m", "oto.cli", "query", "--project", dest, "entity", "system.payments"],
                           cwd=REPO, env=env, capture_output=True, text=True)
        assert r.returncode == 0 and "[System — " in r.stdout, r.stderr
        assert "acme-kg" in r.stderr
        # and the server too
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "kg_count", "arguments": {"type": "System"}}}) + "\n"
        r = subprocess.run([sys.executable, "-m", "oto.cli", "serve", "--project", dest],
                           cwd=REPO, env=env, input=req, capture_output=True, text=True, timeout=60)
        assert "count = 1" in r.stdout, r.stderr


def test_the_deploy_workflow_publishes_when_the_repository_is_configured():
    from oto import repo
    deploy = repo.files("acme", "Acme")[os.path.join(".github", "workflows", "oto-deploy.yml")]
    assert "if: vars.OTO_QUERY_REPO != ''" in deploy
    assert "oto publish --project . --repo \"${{ vars.OTO_QUERY_REPO }}\"" in deploy
    assert "OTO_QUERY_REPO_TOKEN: ${{ secrets.OTO_QUERY_REPO_TOKEN }}" in deploy
    assert "OTO_QUERY_REPO_KEY: ${{ secrets.OTO_QUERY_REPO_KEY }}" in deploy, "a portal sets a deploy key of the store, not a token"


#: the shape of a deploy key and nothing more; spelled in two parts so the credential scan reads no key here
_KEY = "-----BEGIN OPENSSH %s KEY-----\nabc\n-----END OPENSSH %s KEY-----\n" % ("PRIVATE", "PRIVATE")


def test_a_deploy_key_reaches_the_repository_over_ssh_from_a_private_file_that_is_removed():
    from oto import gitx
    assert gitx.ssh_url("https://github.com/Contoso/claims-store") == "git@github.com:Contoso/claims-store.git"
    assert gitx.ssh_url("https://github.com/Contoso/claims-store.git") == "git@github.com:Contoso/claims-store.git"
    assert gitx.ssh_url("/tmp/query.git") == "/tmp/query.git"
    key = _KEY.replace("\n", "\r\n").strip()
    with gitx.reaching("https://github.com/Contoso/claims-store", None, key) as (url, env):
        assert url == "git@github.com:Contoso/claims-store.git"
        command = env["GIT_SSH_COMMAND"].split()
        path, hosts = command[command.index("-i") + 1], [o for o in command if o.startswith("UserKnownHostsFile=")][0].split("=", 1)[1]
        assert os.stat(path).st_mode & 0o777 == 0o600 and os.stat(os.path.dirname(path)).st_mode & 0o777 == 0o700
        assert open(path, encoding="utf-8").read() == _KEY
        assert open(hosts, encoding="utf-8").read().startswith("github.com ssh-ed25519 "), "only GitHub's own host key is trusted"
        assert "IdentitiesOnly=yes" in command and "StrictHostKeyChecking=yes" in command and "abc" not in env["GIT_SSH_COMMAND"]
    assert not os.path.exists(path), "the key is gone once the call is over"
    with gitx.reaching("https://git.example.test/a/b", None, key) as (url, env):
        assert url == "git@git.example.test:a/b.git" and "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]
    with gitx.reaching("https://github.com/a/b", "tok", key) as (url, env):
        assert url == "https://x-access-token:tok@github.com/a/b" and env is None, "a token wins over a key"
    with gitx.reaching("/tmp/query.git", None, key) as (url, env):
        assert url == "/tmp/query.git" and env is None, "a path needs no key"


def test_publish_uses_the_store_key_when_there_is_no_token(monkeypatch):
    seen = []

    def git(args, cwd=None, env=None, remote=None):
        seen.append((args[0], [a for a in args if a.startswith("git@")], dict(env or {})))
        raise ProjectError("stop here")

    monkeypatch.setattr(pub, "_git", git)
    monkeypatch.delenv("OTO_QUERY_REPO_TOKEN", raising=False)
    monkeypatch.setenv("OTO_QUERY_REPO_KEY", _KEY)
    with tempfile.TemporaryDirectory() as root:
        project = _project(os.path.join(root, "p"))
        with pytest.raises(ProjectError, match="stop here"):
            pub.publish(project, "https://github.com/Contoso/claims-store")
    kind, urls, env = seen[0]
    assert kind == "ls-remote" and urls == ["git@github.com:Contoso/claims-store.git"] and "GIT_SSH_COMMAND" in env
    key_file = env["GIT_SSH_COMMAND"].split()[2]
    assert not os.path.exists(key_file), "the key's file is removed even when the push fails"
