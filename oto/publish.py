# -*- coding: utf-8 -*-
"""The query repository: the built store, published on its own so readers never need the documents.

A knowledge repository holds the documents, the graph and the ledger, and access to it is access to
all of that. Many readers only need answers. `oto publish` pushes the built SQLite store, with the
project's identity and a manifest, to a second, read-only repository; `oto sync` pulls that
repository to a reader's machine; `oto serve` and `oto query` recognise such a checkout and serve
it. The deploy workflow publishes on every merge when the repository variable `OTO_QUERY_REPO`
names the target and the secret `OTO_QUERY_REPO_TOKEN` can write to it.

With Neo4j as the production store this is the offline and fallback path: a reader with no route
to the database, or a machine that must answer with the network down, serves the synced store.
The two stores answer alike, so nothing changes for the reader but the freshness.

Git does the transport, through the `git` on the PATH: no library, no second protocol. A token is
taken from the environment and put in the clone URL for the duration of the call; it is never
written to disk or printed.
"""
import datetime
import hashlib
import json
import os
import shutil
import tempfile

from .project import ProjectError

CONFIG_NAME = "project.config.json"
MANIFEST_NAME = "MANIFEST.json"
TOKEN_ENV = "OTO_QUERY_REPO_TOKEN"
IDENTITY_KEYS = ("slug", "name", "server_name", "db_name", "cache_dir")

README = """# {name}: the query store

This repository holds the built knowledge store of **{name}** and nothing else: no documents, no
graph source, no ledger. It is published by the knowledge repository's deploy workflow on every
merge; do not edit it by hand.

To use it, with [uv](https://docs.astral.sh/uv/) installed:

    uvx --from "oto-kg @ git+{engine}" oto sync --repo {repo}
    uvx --from "oto-kg @ git+{engine}" oto query --project ~/.{slug}-kg entity "<a label>"

or open this checkout in Claude Code with the OTO plugin: `oto serve --project .` serves it, and
`oto status --project .` says how fresh it is. `oto sync` again to update.
"""


from . import gitx as _gitx

_git = _gitx.run
_with_token = _gitx.with_token


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- a store checkout ----

def is_store(root):
    """True when `root` is a published query store: an identity config marked store_only, with the database beside it."""
    config = os.path.join(root, CONFIG_NAME)
    if not os.path.exists(config):
        return False
    try:
        with open(config, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return False
    return bool(cfg.get("store_only")) and os.path.exists(os.path.join(root, cfg.get("db_name") or "%s.db" % cfg.get("slug")))


def store_paths(root):
    """(database path, config path) of a store checkout."""
    with open(os.path.join(root, CONFIG_NAME), encoding="utf-8") as f:
        cfg = json.load(f)
    return os.path.join(root, cfg.get("db_name") or "%s.db" % cfg["slug"]), os.path.join(root, CONFIG_NAME)


def read_manifest(root):
    path = os.path.join(root, MANIFEST_NAME)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---- publish ----

def publish(project, repo, source=None, branch="main", token=None, engine=None, site=False):
    """Push the built store to the query repository, and with `site` the static site beside it.
    Returns the manifest written, with `changed`."""
    from .targets.sqlite import SCHEMA_VERSION

    database = project.layout.database
    if not os.path.exists(database):
        raise ProjectError("nothing to publish: no built store at %s (run `oto build`)" % database)
    identity = project.identity()
    cfg = project.config()
    token = token if token is not None else os.environ.get(TOKEN_ENV)
    engine = engine or "https://github.com/Cynergis/oto"

    work = tempfile.mkdtemp(prefix="oto-publish-")
    try:
        _git(["clone", "--quiet", "--depth", "1", "--branch", branch, _with_token(repo, token), work]) \
            if _remote_has_branch(repo, token, branch) else _init_empty(work, repo, token, branch)
        shutil.copyfile(database, os.path.join(work, identity["db_name"]))
        if site:
            if not os.path.isdir(project.layout.site):
                raise ProjectError("--site needs build/site/; run `oto build --target site` first")
            target = os.path.join(work, "site")
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(project.layout.site, target, ignore=shutil.ignore_patterns(".git"))
        with open(os.path.join(work, CONFIG_NAME), "w", encoding="utf-8") as f:
            out = {k: cfg[k] for k in IDENTITY_KEYS if cfg.get(k)}
            out.update({"slug": identity["slug"], "name": identity["name"], "db_name": identity["db_name"],
                        "server_name": identity["server_name"], "store_only": True})
            json.dump(out, f, indent=2)
            f.write("\n")
        manifest = {"build_seq": int(project.build_seq()), "schema_version": SCHEMA_VERSION,
                    "sha256": _sha256(database), "bytes": os.path.getsize(database),
                    "published_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
                    "source": source or "", "repo": repo}
        manifest["site"] = bool(site)
        previous = read_manifest(work)
        if previous.get("sha256") == manifest["sha256"] and bool(previous.get("site")) == bool(site) \
                and not (site and _git(["status", "--porcelain", "site"], cwd=work).strip()):
            manifest["changed"] = False
            return manifest
        with open(os.path.join(work, MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        with open(os.path.join(work, "README.md"), "w", encoding="utf-8") as f:
            f.write(README.format(name=identity["name"], slug=identity["slug"], repo=repo, engine=engine))
        _git(["add", "-A"], cwd=work)
        _git(["-c", "user.name=oto publish", "-c", "user.email=oto-publish@localhost", "commit", "--quiet",
              "-m", "store build_seq %d%s" % (manifest["build_seq"], (" from " + source) if source else "")], cwd=work)
        _git(["push", "--quiet", _with_token(repo, token), "HEAD:%s" % branch], cwd=work)
        manifest["changed"] = True
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _remote_has_branch(repo, token, branch):
    out = _git(["ls-remote", "--heads", _with_token(repo, token), branch])
    return bool(out.strip())


def _init_empty(work, repo, token, branch):
    """An empty query repository: start its history here."""
    _git(["init", "--quiet", "-b", branch, work])


# ---- sync ----

def sync(repo, dest=None, branch="main", token=None):
    """Clone or fast-forward the query repository into `dest` (default: the store's own cache dir,
    `~/.<slug>-kg`). Returns (dest, manifest)."""
    token = token if token is not None else os.environ.get(TOKEN_ENV)
    url = _with_token(repo, token)
    if dest is None:
        # The default lives under the slug, which is only known once the repository is read.
        probe = tempfile.mkdtemp(prefix="oto-sync-")
        try:
            _git(["clone", "--quiet", "--depth", "1", "--branch", branch, url, probe])
            if not is_store(probe):
                raise ProjectError("%s is not a published query store (no %s with store_only)" % (repo, CONFIG_NAME))
            with open(os.path.join(probe, CONFIG_NAME), encoding="utf-8") as f:
                cfg = json.load(f)
            dest = os.path.expanduser(cfg.get("cache_dir") or "~/.%s-kg" % cfg["slug"])
            if os.path.isdir(os.path.join(dest, ".git")):
                _git(["pull", "--quiet", "--ff-only", url, branch], cwd=dest)
            else:
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(probe, dest)
        finally:
            shutil.rmtree(probe, ignore_errors=True)
    elif os.path.isdir(os.path.join(dest, ".git")):
        _git(["pull", "--quiet", "--ff-only", url, branch], cwd=dest)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        _git(["clone", "--quiet", "--depth", "1", "--branch", branch, url, dest])
    if not is_store(dest):
        raise ProjectError("%s is not a published query store (no %s with store_only)" % (repo, CONFIG_NAME))
    return dest, read_manifest(dest)
