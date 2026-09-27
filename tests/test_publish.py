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
        assert manifest["schema_version"] == 4 and manifest["source"] == "org/knowledge@abc123"
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
        assert r.returncode == 0 and "[System]" in r.stdout, r.stderr
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
