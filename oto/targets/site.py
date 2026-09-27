# -*- coding: utf-8 -*-
"""Stage 7, optional. The static site: the graph as data, and a view to read it with.

Runs when the project targets it (`"targets": [..., "site"]`, or `oto build --target site`) and
writes `build/site/`:

    data.json           the graph payload (serve/payload.py), the same object `/api/graph` serves
    <the app's files>   copied as they are: `"site": {"view": "<name or path>"}` in project.config.json,
                        `oto build --target site --app <name or path>`, or the built-in explorer

Opening the app from disk or hosting the directory anywhere static gives a reader with no server
and no credentials. Passages are included unless `"site": {"passages": false}`; a large corpus
turns them off and the app's search says so. An app is named by path or by name (see
`apps/manifest.py`); its `app.json` says which data files to generate beside `data.json`, and an
app that declares none cannot be exported, since a static site needs its data on disk.
"""
import json
import os
import shutil

from ..apps import manifest as _apps
from ..project import ProjectError
from ..serve import payload as _payload
from ..serve.store import SqliteStore

DATA_NAME = "data.json"
SKIP = shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", "node_modules")


def configured(project):
    cfg = project.config()
    targets = cfg.get("targets") or ["sqlite"]
    forced = "site" in (getattr(project, "options", {}) or {}).get("targets", set())
    return "site" in targets or forced


def settings(project):
    cfg = project.config().get("site") or {}
    options = getattr(project, "options", {}) or {}
    return {"view": options.get("view") or cfg.get("view"), "passages": cfg.get("passages", True)}


def resolve_app(app, project_root=None):
    """The directory of a view, from a path or a name (see apps/manifest.py)."""
    return _apps.resolve(app, project_root)


def write(project, app_dir=None, passages=True):
    """Write build/site/. Returns (site directory, payload)."""
    layout = project.layout
    if not os.path.exists(layout.database):
        raise ProjectError("the site stage needs the SQLite store; run the sqlite stage first")
    if os.path.exists(layout.site):
        shutil.rmtree(layout.site)
    if app_dir:
        shutil.copytree(app_dir, layout.site, ignore=SKIP)
    else:
        os.makedirs(layout.site, exist_ok=True)
    store = SqliteStore(layout.database)
    try:
        payload = _payload.build(store, os.path.dirname(project.src), project.config(), passages=passages)
    finally:
        store.close()
    with open(os.path.join(layout.site, DATA_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    if app_dir:
        manifest = _apps.read(app_dir)
        problems = _apps.problems(app_dir)
        if problems:
            raise ProjectError("app %r is not usable:\n  - %s" % (manifest["name"], "\n  - ".join(problems)))
        _apps.check_requires(manifest, payload.get("vocabulary"))
        if manifest["_declared"] and not manifest.get("data"):
            raise ProjectError("app %r declares no data files; a static site needs its data on disk. Serve it live "
                               "with `oto serve --http --app`, or add a `data` entry to app.json" % manifest["name"])
        for rel, text in _apps.data_files(manifest, payload, app_dir).items():
            path = os.path.join(layout.site, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        for name, source in _apps.override_files(manifest, os.path.dirname(project.src)).items():
            shutil.copyfile(source, os.path.join(layout.site, name))
    return layout.site, payload


def run(project):
    if not configured(project):
        print("site: not targeted (add \"site\" to targets, or pass --target site); skipped")
        return
    conf = settings(project)
    app_dir = resolve_app(conf["view"] or "explorer", os.path.dirname(project.src))
    site, payload = write(project, app_dir=app_dir, passages=conf["passages"])
    print("site: %d nodes, %d edges%s -> %s%s"
          % (len(payload["nodes"]), len(payload["edges"]),
             (", %d passages" % len(payload["passages"])) if "passages" in payload else "",
             os.path.relpath(site, project.src), " with app %s" % os.path.basename(app_dir)))
