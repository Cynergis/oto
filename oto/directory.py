# -*- coding: utf-8 -*-
"""The organisation's graphs, in one place (docs/plans/people-and-graphs.md, phase 4).

    oto registry graphs [<dir>] --org <org>   fill the registry's directory from repositories carrying the topic oto-graph
    oto registry fleet [<dir>] [--json]       every graph's versions, last deploy, stale pull requests and access drift
    oto repo retire --confirm <owner/name>    archive a graph and its store, take it off the directory, optionally empty Neo4j

The registry's `registry.json` gains a `graphs` section holding each graph's descriptor, the shape `oto graph describe` prints, with its
repositories and owners. A scheduled workflow in the registry fills it, so no graph needs a token that can write to the registry. Two graphs
with one slug are refused, because in one Neo4j database they would overwrite each other. The catalog site lists them, and `oto graphs add
<slug>` resolves through it.
"""
import base64
import datetime
import json
import os
import shutil
import tempfile

from . import __version__
from . import access as _access
from . import graphs as _graphs
from . import repo as _repo
from .project import ProjectError

TOPIC = "oto-graph"
STALE_DAYS = 14
WORKFLOW_PATH = os.path.join(".github", "workflows", "oto-graphs.yml")
WORKFLOW = """name: oto graphs

# The directory of this organisation's graphs, in registry.json, filled from the repositories carrying the topic oto-graph, so that no graph needs a token
# that can write here. OTO_DIRECTORY_TOKEN reads those repositories: a secret of this repository, and nothing else needs it.
on:
  schedule:
    - cron: "23 5 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  graphs:
    runs-on: ubuntu-latest
    env:
      GH_TOKEN: ${{ secrets.OTO_DIRECTORY_TOKEN }}
      OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
      - name: Install the engine
        run: python -m pip install "oto-kg @ git+https://github.com/Cynergis/oto@v{engine_version}"
      - name: Read the graphs
        run: oto registry graphs . --org "${{ github.repository_owner }}"
      - name: Keep what changed
        run: |
          git config user.name "oto graphs"
          git config user.email "oto-graphs@users.noreply.github.com"
          git add registry.json
          git diff --cached --quiet || { git commit -m "The directory of graphs" && git push; }
"""


def _file(run, repository, path):
    """A file's text on the repository's default branch, or None."""
    code, out, _err = run("api", "repos/%s/contents/%s" % (repository, path))
    if code != 0:
        return None
    content = (_repo._json(out, {}) or {}).get("content")
    if not content:
        return None
    try:
        return base64.b64decode(content).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _json_file(run, repository, path):
    text = _file(run, repository, path)
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def describe_repository(run, repository):
    """A directory entry from what a repository holds, or None when it holds no graph."""
    config = _json_file(run, repository, "project.config.json")
    if not config or not config.get("slug"):
        return None
    name = config.get("name") or config["slug"]
    said = (config.get("description") or "").strip()
    vocabulary = _json_file(run, repository, "ontology.config.json") or {}
    lock = _json_file(run, repository, "oto.lock.json") or {}
    named = _json_file(run, repository, _access.FILE.replace(os.sep, "/")) or {}
    ontology = config.get("ontology") or {}
    pack = ontology.get("pack") or {}
    entry = {"id": _graphs.node_id(config["slug"]), "slug": config["slug"], "label": name, "subject": ("%s: %s" % (name, said)) if said else name,
             "classes": _graphs.main_classes(vocabulary), "reach": config.get("server_name") or "%s-kg" % config["slug"],
             "repository": repository, "store": named.get("store"), "owners": [e for e in named.get("stewards") or [] if isinstance(e, str)],
             "pack": pack.get("name") or ontology.get("name"), "pack_release": pack.get("release") or ontology.get("release"),
             "engine": (lock.get("engine") or {}).get("version") or config.get("oto_version")}
    neo4j = config.get("neo4j") or {}
    if neo4j.get("uri"):
        entry["neo4j"] = {k: neo4j[k] for k in ("uri", "database") if neo4j.get(k)}
    return entry


def scan(org, topic=TOPIC, token=None, gh=None):
    """Every graph in the organisation, from the repositories carrying the topic, sorted by slug. Archived ones have left."""
    run = _repo._github(token, gh)
    code, out, err = run("api", "search/repositories?q=org:%s+topic:%s&per_page=100" % (org, topic))
    if code != 0:
        raise ProjectError("could not read the repositories of %s: %s" % (org, (err or out).strip()[-300:]))
    entries = []
    for item in (_repo._json(out, {}) or {}).get("items") or []:
        if item.get("archived"):
            continue
        entry = describe_repository(run, item.get("full_name"))
        if entry:
            entries.append(entry)
    return sorted(entries, key=lambda e: (e["slug"], e["repository"]))


def duplicate_slugs(entries):
    """{slug: [repositories]} for slugs more than one graph carries."""
    seen = {}
    for entry in entries:
        seen.setdefault(entry.get("slug"), []).append(entry.get("repository"))
    return {slug: repos for slug, repos in seen.items() if len(repos) > 1}


def write_directory(root, entries):
    """Hold the entries in the registry's index, and make sure the workflow that keeps them is beside it."""
    from .model import registry as _registry
    clashes = duplicate_slugs(entries)
    if clashes:
        raise ProjectError("two graphs with one slug would overwrite each other in one Neo4j database, so nothing was written:\n  - " +
                           "\n  - ".join("%s: %s" % (slug, ", ".join(repos)) for slug, repos in sorted(clashes.items())))
    index = _registry.read_index(root)
    index["graphs"] = entries
    with open(os.path.join(root, _registry.INDEX_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    path = os.path.join(root, WORKFLOW_PATH)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(WORKFLOW.replace("{engine_version}", __version__))
    return index


def lookup(slug):
    """A graph's entry from the registries this computer knows, or None."""
    from .model import registry as _registry
    for record in _registry.load_registries() or []:
        for entry in (record.get("index") or {}).get("graphs") or []:
            if isinstance(entry, dict) and entry.get("slug") == slug:
                return entry
    return None


# ---- the fleet ----

def _version(text):
    parts = []
    for piece in str(text or "").split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts) if parts else None


def _stamp(text):
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _drift_of(run, repository, token=None, gh=None):
    """What `oto repo access --check` would say of a repository, from the files on its default branch."""
    held = tempfile.mkdtemp(prefix="oto-fleet-")
    try:
        os.makedirs(os.path.join(held, ".github"))
        for relative in (_access.FILE, _repo.CODEOWNERS_FILE):
            text = _file(run, repository, relative.replace(os.sep, "/"))
            if text is not None:
                with open(os.path.join(held, relative), "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
        if not os.path.exists(os.path.join(held, _access.FILE)):
            return ["no access file: nothing says who should have access"]
        return _access.drift(held, repository, token=token, gh=gh)
    finally:
        shutil.rmtree(held, ignore_errors=True)


def fleet(index, token=None, gh=None, now=None, stale_days=STALE_DAYS):
    """One row per graph in the index, read fresh from GitHub: versions against the newest, the last deploy, stale pull requests, access drift. A graph that
    can't be read says so in `problem`, and the others still show."""
    run = _repo._github(token, gh)
    now = _stamp(now) if now else datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    newest = {p.get("name"): p.get("release") for p in index.get("packs") or [] if isinstance(p, dict)}
    mine = _version(__version__)
    rows = []
    for listed in index.get("graphs") or []:
        repository = listed.get("repository")
        row = {"slug": listed.get("slug"), "label": listed.get("label"), "repository": repository, "engine": listed.get("engine"), "engine_latest": __version__,
               "engine_behind": False, "pack": listed.get("pack"), "pack_release": listed.get("pack_release"), "pack_latest": newest.get(listed.get("pack")),
               "pack_behind": False, "last_deploy": None, "stale_pull_requests": [], "drift": [], "problem": None}
        try:
            entry = describe_repository(run, repository)
            if entry is None:
                row["problem"] = "%s can't be read, or holds no graph any more" % repository
                rows.append(row)
                continue
            row.update(engine=entry.get("engine"), pack=entry.get("pack"), pack_release=entry.get("pack_release"), pack_latest=newest.get(entry.get("pack")))
            held = _version(row["engine"])
            row["engine_behind"] = bool(held and mine and held < mine)
            row["pack_behind"] = bool(row["pack_latest"] and row["pack_release"] and int(row["pack_release"]) < int(row["pack_latest"]))
            code, out, _err = run("api", "repos/%s/actions/workflows/oto-deploy.yml/runs?per_page=1" % repository)
            runs = (_repo._json(out, {}) or {}).get("workflow_runs") or [] if code == 0 else []
            if runs:
                row["last_deploy"] = {"conclusion": runs[0].get("conclusion"), "at": runs[0].get("updated_at"), "commit": str(runs[0].get("head_sha") or "")[:12]}
            code, out, _err = run("api", "repos/%s/pulls?state=open&per_page=100" % repository)
            for pull in (_repo._json(out, []) or []) if code == 0 else []:
                opened = _stamp(pull.get("created_at"))
                if opened and (now - opened).days > stale_days:
                    row["stale_pull_requests"].append(pull.get("number"))
            row["drift"] = _drift_of(run, repository, token=token, gh=gh)
        except ProjectError as exc:
            row["problem"] = str(exc)
        rows.append(row)
    return rows


def render_fleet(rows):
    lines = ["%d graph(s):" % len(rows)]
    for row in rows:
        lines.append("  %-20s %s" % (row["slug"], row["repository"]))
        if row["problem"]:
            lines.append("      can't say: %s" % row["problem"])
            continue
        engine = "engine %s%s" % (row["engine"] or "unknown", (", behind %s" % row["engine_latest"]) if row["engine_behind"] else "")
        pack = "pack %s @%s%s" % (row["pack"], row["pack_release"], (", behind @%s" % row["pack_latest"]) if row["pack_behind"] else "") if row["pack"] else "no pack"
        deploy = row["last_deploy"]
        lines.append("      %s; %s; last deploy %s" % (engine, pack, ("%s, %s" % (deploy["conclusion"], deploy["at"])) if deploy else "none yet"))
        if row["stale_pull_requests"]:
            lines.append("      stale pull requests: %s" % ", ".join("#%s" % n for n in row["stale_pull_requests"]))
        for line in row["drift"]:
            lines.append("      drift: %s" % line)
    return "\n".join(lines)


# ---- retiring a graph ----

def retire(root, repository, confirm, neo4j=False, token=None, gh=None):
    """Take a graph out of service. Its repository and store are archived, never deleted, since the record is worth keeping, and it comes off the topic, so the
    directory drops it. With `neo4j`, its nodes go from Neo4j, using the login in this environment. Returns {archived, nodes_deleted, warnings}."""
    from .project import Project
    if confirm != repository:
        raise ProjectError("retiring archives %s and its store: pass --confirm %s to say so" % (repository, repository))
    run = _repo._github(token, gh)
    out = {"archived": [], "nodes_deleted": None, "warnings": []}
    if neo4j:
        from .targets import neo4j as _target
        project = Project.standard(root)
        conf = _target.settings(project)
        driver = _target.open_driver(conf)
        try:
            out["nodes_deleted"] = _target.delete_project(driver, conf["database"], project.identity()["slug"])
        finally:
            driver.close()
    code, said, _err = run("api", "repos/%s/topics" % repository)
    topics = [t for t in (_repo._json(said, {}) or {}).get("names") or [] if t != TOPIC] if code == 0 else []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"names": topics}, f)
        temp = f.name
    try:
        code, said, err = run("api", "--method", "PUT", "repos/%s/topics" % repository, "--input", temp)
    finally:
        os.unlink(temp)
    if code != 0:
        raise ProjectError("could not take %s off the topic %s: %s" % (repository, TOPIC, (err or said).strip()[-300:]))
    named = _access.load(root) or {}
    for target in [repository] + ([named["store"]] if isinstance(named.get("store"), str) else []):
        code, said, err = run("api", "--method", "PATCH", "repos/%s" % target, "-F", "archived=true")
        if code == 0:
            out["archived"].append(target)
        elif target == repository:
            raise ProjectError("could not archive %s: %s" % (target, (err or said).strip()[-300:]))
        else:
            out["warnings"].append("could not archive %s: %s" % (target, (err or said).strip()[-200:]))
    return out
