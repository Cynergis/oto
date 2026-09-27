# -*- coding: utf-8 -*-
"""The view contract: `app.json`, the data files it asks for, and where an app is found.

    {
      "name": "prd-site",
      "summary": "A PRD and an Architecture document, read as documents, from the graph.",
      "entry": "index.html",
      "engine": ">=0.1",
      "data": [
        {"file": "data.js", "format": "js-globals",
         "globals": {"__PRD__": {"$include": "projections/prd.json"}, "__ARCH__": {...}}},
        {"file": "data/decisions.json", "format": "json", "root": {"$nodes": "DecisionRecord", ...}}
      ],
      "adapter": "adapter.js",
      "requires": {"classes": ["System", "DecisionRecord"], "relations": ["decided_by"],
                   "attributes": {"DecisionRecord": ["status"]}}
    }

`format` is `js-globals` (`window.X = ...;` per global), `json` (one object: the globals keyed by
name, or `root`), or `js-module` (`export const X = ...;` per global). `overrides` names files the
app reads if present beside it, which a project (`<project>/views/<file>`) or a pack
(`views/<file>`) may supply without carrying the whole app: the explorer's `explorer.json`. An app with no `data`
entry gets nothing generated and calls the HTTP routes itself; the static site stage refuses it,
since a site needs its data on disk. `requires` is checked against the vocabulary before an app
is served or exported, so a project that lacks what the app expects is refused with the names.

An app is found by path, or by name under `<project>/views/<name>` (installed there from a pack
by `oto init --pack`), under `views/` of any pack on this machine, or shipped inside the engine
under `oto/ui/<name>`.
"""
import json
import os
import re

from ..project import ProjectError
from . import projection as _projection

MANIFEST_NAME = "app.json"
FORMATS = ("js-globals", "json", "js-module")
NAME_OK = re.compile(r"^[a-z][a-z0-9-]*$")
UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


class AppError(ProjectError):
    """A view that cannot be used; the message says what is wrong or missing."""


def read(directory):
    """The manifest, defaults filled in. A directory with an index.html and no manifest is an app
    that wants no data generated."""
    path = os.path.join(directory, MANIFEST_NAME)
    manifest = {"name": os.path.basename(os.path.normpath(directory)), "summary": "", "entry": "index.html",
                "engine": None, "data": [], "adapter": None, "requires": {}, "overrides": [], "_declared": False}
    if not os.path.exists(path):
        return manifest
    with open(path, encoding="utf-8") as f:
        declared = json.load(f)
    if not isinstance(declared, dict):
        raise AppError("%s must be a JSON object" % path)
    for key in ("name", "summary", "entry", "engine", "data", "adapter", "requires", "overrides"):
        if key in declared and declared[key] not in (None, ""):
            manifest[key] = declared[key]
    manifest["_declared"] = True
    return manifest


def problems(directory, vocabulary=None):
    """What is wrong with a view; with a vocabulary, what it names that is not declared."""
    out = []
    try:
        manifest = read(directory)
    except (ValueError, AppError) as exc:
        return ["app.json cannot be read: %s" % exc]
    if not NAME_OK.match(manifest["name"] or ""):
        out.append("app name %r must be lowercase letters, digits and hyphens" % manifest["name"])
    if not os.path.exists(os.path.join(directory, manifest["entry"])):
        out.append("entry %r is not in the app directory" % manifest["entry"])
    if manifest.get("engine"):
        from ..model import ontology_manifest as _tm
        ok = _tm.satisfies(manifest["engine"])
        if ok is None:
            out.append("engine %r is not a spec this engine reads" % manifest["engine"])
        elif not ok:
            out.append("app needs engine %s; upgrade the engine" % manifest["engine"])
    if manifest.get("adapter") and not os.path.exists(os.path.join(directory, manifest["adapter"])):
        out.append("adapter %r is not in the app directory" % manifest["adapter"])
    data = manifest.get("data")
    if not isinstance(data, list):
        return out + ["`data` must be a list of data files"]
    refs = {"classes": set(), "relations": set(), "attributes": set(), "includes": []}
    for number, entry in enumerate(data, 1):
        if not isinstance(entry, dict) or not entry.get("file"):
            out.append("data entry %d needs a `file`" % number); continue
        fmt = entry.get("format") or "json"
        if fmt not in FORMATS:
            out.append("data entry %r: format %r is not one of %s" % (entry["file"], fmt, ", ".join(FORMATS)))
        if fmt in ("js-globals", "js-module") and not isinstance(entry.get("globals"), dict):
            out.append("data entry %r: format %s needs `globals`" % (entry["file"], fmt))
        if fmt == "json" and "root" not in entry and not isinstance(entry.get("globals"), dict):
            out.append("data entry %r: format json needs `root` or `globals`" % entry["file"])
        if ".." in entry["file"].split("/") or entry["file"].startswith("/"):
            out.append("data entry %r must be a relative path inside the app" % entry["file"])
        for expr in ([entry["root"]] if "root" in entry else []) + list((entry.get("globals") or {}).values()):
            try:
                _projection.references(expr, refs, directory)
            except (ValueError, OSError) as exc:
                out.append("data entry %r: %s" % (entry["file"], exc))
    for inc in refs["includes"]:
        if not os.path.exists(os.path.join(directory, inc)):
            out.append("$include %r: no such file in the app" % inc)
    overrides = manifest.get("overrides") or []
    if not isinstance(overrides, list) or not all(isinstance(x, str) and x and "/" not in x and ".." not in x for x in overrides):
        out.append("`overrides` must be a list of file names")
    requires = manifest.get("requires") or {}
    if not isinstance(requires, dict):
        out.append("`requires` must be an object with classes, relations and attributes")
        requires = {}
    if vocabulary is not None:
        classes = set((vocabulary.get("classes") or {}))
        relations = set((vocabulary.get("properties") or {}))
        for c in sorted(refs["classes"] - classes):
            out.append("projection names class %r, which the vocabulary does not declare" % c)
        for r in sorted(refs["relations"] - relations):
            out.append("projection names relation %r, which the vocabulary does not declare" % r)
        out += missing(requires, vocabulary)
    return out


def missing(requires, vocabulary):
    """What `requires` asks for that the vocabulary lacks, as problem lines."""
    out = []
    classes = set((vocabulary.get("classes") or {}))
    relations = set((vocabulary.get("properties") or {}))
    attributes = vocabulary.get("attributes") or {}
    for c in sorted(set(requires.get("classes") or []) - classes):
        out.append("the app requires class %r, which this vocabulary does not declare" % c)
    for r in sorted(set(requires.get("relations") or []) - relations):
        out.append("the app requires relation %r, which this vocabulary does not declare" % r)
    for kind, names in sorted((requires.get("attributes") or {}).items()):
        declared = set((attributes.get(kind) or {}))
        if kind in classes and declared:
            for a in sorted(set(names) - declared):
                out.append("the app requires attribute %s.%s, which this vocabulary does not declare" % (kind, a))
    return out


# ---- generating the data files ----

def render(entry, payload, directory):
    """The text of one data file, from its entry and the payload."""
    fmt = entry.get("format") or "json"
    projector = _projection.Projector(payload, directory)
    if fmt == "json":
        if "root" in entry:
            value = projector.evaluate(entry["root"])
        else:
            value = {name: projector.evaluate(expr) for name, expr in (entry.get("globals") or {}).items()}
        return json.dumps(value, ensure_ascii=False, indent=None, separators=(",", ":")) + "\n"
    lines = ["/* generated by oto from the graph; do not edit: the projection lives in app.json */"]
    for name, expr in (entry.get("globals") or {}).items():
        value = json.dumps(projector.evaluate(expr), ensure_ascii=False, separators=(",", ":"))
        if fmt == "js-globals":
            lines.append("window.%s = %s;" % (name, value))
        else:
            lines.append("export const %s = %s;" % (name, value))
    return "\n".join(lines) + "\n"


def data_files(manifest, payload, directory):
    """{relative file path: text} for every data entry."""
    out = {}
    for entry in manifest.get("data") or []:
        out[entry["file"].lstrip("/")] = render(entry, payload, directory)
    return out


def override_files(manifest, project_root=None):
    """{file name: path} for each override the project or an ontology on this machine supplies."""
    out = {}
    for name in manifest.get("overrides") or []:
        places = []
        if project_root:
            places.append(os.path.join(project_root, "views", name))
        try:
            from ..model import packs as _packs
            for pack in _packs.available():
                places.append(os.path.join(_packs.dir_for(pack), "views", name))
        except Exception:                                               # noqa: BLE001
            pass
        for path in places:
            if os.path.isfile(path):
                out[name] = path
                break
    return out


def check_requires(manifest, vocabulary):
    """Raise AppError when the vocabulary lacks what the app requires."""
    lacking = missing(manifest.get("requires") or {}, vocabulary or {})
    if lacking:
        raise AppError("app %r cannot be served from this project:\n  - %s" % (manifest["name"], "\n  - ".join(lacking)))


# ---- finding an app ----

def candidates(name, project_root=None):
    """Directories a name may resolve to, in order."""
    out = []
    if project_root:
        out.append(os.path.join(project_root, "views", name))
    try:
        from ..model import packs as _packs
        for pack in _packs.available():
            out.append(os.path.join(_packs.dir_for(pack), "views", name))
    except Exception:                                                   # noqa: BLE001 - packs are optional here
        pass
    out.append(os.path.join(UI_DIR, name))
    return out


def resolve(app, project_root=None):
    """The directory of a view, from a path or a name. None when nothing was asked."""
    if not app:
        return None
    if os.sep in app or (os.altsep and os.altsep in app) or app.startswith(".") or app.startswith("~"):
        path = os.path.abspath(os.path.expanduser(app))
        if os.path.isdir(path):
            return path
        raise AppError("app %r is not a directory" % app)
    if os.path.isdir(os.path.abspath(app)) and os.path.exists(os.path.join(os.path.abspath(app), "index.html")):
        return os.path.abspath(app)
    for path in candidates(app, project_root):
        if os.path.isdir(path):
            return path
    looked = [p for p in candidates(app, project_root)]
    raise AppError("no view named %r (looked in %s); pass a directory path instead"
                   % (app, ", ".join(looked[:4]) + (", ..." if len(looked) > 4 else "")))


def available(project_root=None):
    """Every app on this machine: [(name, directory, where)]."""
    out, seen = [], set()
    places = []
    if project_root:
        places.append((os.path.join(project_root, "views"), "project"))
    try:
        from ..model import packs as _packs
        for pack in _packs.available():
            places.append((os.path.join(_packs.dir_for(pack), "views"), "pack %s" % pack))
    except Exception:                                                   # noqa: BLE001
        pass
    places.append((UI_DIR, "built-in"))
    for base, where in places:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            directory = os.path.join(base, name)
            if os.path.isdir(directory) and os.path.exists(os.path.join(directory, "index.html")) and name not in seen:
                seen.add(name)
                out.append((name, directory, where))
    return out
