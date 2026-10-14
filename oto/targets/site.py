# -*- coding: utf-8 -*-
"""Stage 7, optional. The static site: the graph as data, and a view to read it with.

Runs when the project targets it (`"targets": [..., "site"]`, or `oto build --target site`) and
writes `build/site/`:

    data.json           the graph payload (serve/payload.py), the same object `/api/graph` serves
    <the app's files>   copied as they are: `"site": {"view": "<name or path>"}` in project.config.json,
                        `oto build --target site --view <name or path>`, or the built-in explorer

With the view `all`, the default when the project has views of its own (installed from its packs),
the site is a home page (`index.html`, `views.json`) and each view in its own folder beside it,
`<name>/`, the built-in explorer among them: one site for every view the project's packs bring.

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
from ..apps import studio as _studio
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


def _payload_of(project, passages):
    layout = project.layout
    if not os.path.exists(layout.database):
        raise ProjectError("the site stage needs the SQLite store; run the sqlite stage first")
    store = SqliteStore(layout.database)
    try:
        return _payload.build(store, os.path.dirname(project.src), project.config(), passages=passages)
    finally:
        store.close()


def _write_data(dest, payload):
    with open(os.path.join(dest, DATA_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def _write_app(project, app_dir, dest, payload):
    """One view into `dest`: its files, the payload, the data files its app.json declares, its overrides."""
    shutil.copytree(app_dir, dest, ignore=SKIP)
    _write_data(dest, payload)
    manifest = _apps.read(app_dir)
    problems = _apps.problems(app_dir)
    if problems:
        raise ProjectError("app %r is not usable:\n  - %s" % (manifest["name"], "\n  - ".join(problems)))
    _apps.check_requires(manifest, payload.get("vocabulary"))
    if manifest["_declared"] and not manifest.get("data"):
        raise ProjectError("app %r declares no data files; a static site needs its data on disk. Serve it live "
                           "with `oto serve --http --view`, or add a `data` entry to app.json" % manifest["name"])
    for rel, text in _apps.data_files(manifest, payload, app_dir).items():
        path = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    for name, source in _apps.override_files(manifest, os.path.dirname(project.src)).items():
        shutil.copyfile(source, os.path.join(dest, name))


def _write_studio(project, site, views, payload):
    """The kit every view includes, beside them under `_studio/`, and the studio's data: the pages in
    reading order, which page shows each thing, and what is still open on each."""
    from ..reason import questions as _questions
    dest = os.path.join(site, _studio.KIT_PREFIX)
    shutil.copytree(_studio.KIT_DIR, dest, ignore=SKIP, dirs_exist_ok=True)
    rows = _studio.survey(_questions.load(project), payload)
    with open(os.path.join(dest, _studio.DATA_NAME), "w", encoding="utf-8", newline="\n") as f:
        f.write(_studio.script(_studio.data(views, payload, rows, project.config())))


def write(project, app_dir=None, passages=True):
    """Write build/site/ with one view at its root. Returns (site directory, payload)."""
    layout = project.layout
    payload = _payload_of(project, passages)
    if os.path.exists(layout.site):
        shutil.rmtree(layout.site)
    if app_dir:
        _write_app(project, app_dir, layout.site, payload)
        _write_studio(project, layout.site, [], payload)
    else:
        os.makedirs(layout.site, exist_ok=True)
        _write_data(layout.site, payload)
    return layout.site, payload


def write_all(project, views, passages=True):
    """Write build/site/ as a home page and every view in its own folder. Returns (site directory, payload)."""
    layout = project.layout
    payload = _payload_of(project, passages)
    if os.path.exists(layout.site):
        shutil.rmtree(layout.site)
    shutil.copytree(_apps.HOME_DIR, layout.site, ignore=SKIP)
    for name, app_dir in views:
        _write_app(project, app_dir, os.path.join(layout.site, name), payload)
    with open(os.path.join(layout.site, "views.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(_apps.catalog(views, project.config()), f, indent=1, ensure_ascii=False)
        f.write("\n")
    _write_studio(project, layout.site, views, payload)
    return layout.site, payload


def run(project):
    if not configured(project):
        print("site: not targeted (add \"site\" to targets, or pass --target site); skipped")
        return
    conf = settings(project)
    root = os.path.dirname(project.src)
    view = conf["view"] or _apps.default_view(root)
    if view == _apps.ALL:
        views = _apps.project_views(root)
        site, payload = write_all(project, views, passages=conf["passages"])
        shown = "a home page and %d views: %s" % (len(views), ", ".join(name for name, _d in views))
    else:
        app_dir = resolve_app(view, root)
        site, payload = write(project, app_dir=app_dir, passages=conf["passages"])
        shown = "app %s" % os.path.basename(app_dir)
    print("site: %d nodes, %d edges%s -> %s with %s"
          % (len(payload["nodes"]), len(payload["edges"]),
             (", %d passages" % len(payload["passages"])) if "passages" in payload else "",
             os.path.relpath(site, project.src), shown))
