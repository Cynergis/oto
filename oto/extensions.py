# -*- coding: utf-8 -*-
"""The pack seams (ADR-0006): what a pack provides beyond its vocabulary, and when the engine loads it.

A pack's manifest may carry `provides`, five kinds, each a list:

    "provides": {
      "stages":      [{"name": "policy", "module": "oto.targets.policy", "owns": ["policy"]}],
      "commands":    [{"name": "policy", "module": "oto.cli.policy", "label": "policy"}],
      "endpoints":   ["oto.serve.policy_api"],
      "write_hooks": ["oto_policy:enforce"],
      "read_hooks":  ["oto_policy:police_read"],
      "status":      ["oto_work:status"],
      "adapters":    [{"framework": "<name>", "module": "oto_<name>", "import": "read_model", "export": "write_model", "migrate": "migrate"}]
    }

A stage module exposes `run(project)` and runs after the core's targets, before the site, owning the
layout attributes it names, so a partial build stashes them. A command module exposes `register(sub)`
as the core's do. An endpoint module exposes `routes(project)`, {"/api/<path>": fn(args) -> (status,
object)}, served beside the core's routes. A write hook, `module:function`, is called as
`fn(project, action, by)` before `curate apply`, `decide` and `promote`, returns a note for the audit
record or None, and refuses by raising a ProjectError. A read hook, `module:function`, is called as
`fn(project, graph, caller, sql)` before the served native read and refuses by raising. A status hook,
`module:function`, is called as `fn(project)` when the project's status snapshot is built and returns
the keys it adds (the work pack's board under `work`). An adapter reads a framework's file into the
graph's shape (`import`: `fn(project, path, at, **options)`) and writes the graph back as that
framework (`export`: `fn(project)`), and may migrate a graph written with the framework's former attribute
names (`migrate`: `fn(project, by)`); `oto arch import --framework <name>` chooses it.

A pack from outside the engine carries its modules in its own `code/` folder (`carries: ["code", ...]`):
the engine puts that folder on the import path, once, when it loads anything the pack provides, so
nothing has to be installed on the machine for a pack to plug in. The engine's own packs carry no
`code/`; their modules import from the engine under the pack's own `code/`.

Stages, endpoints and write hooks are loaded only for the packs composed in the project: a pack is
composed when every class it declares itself is in the project's vocabulary, which is the same gate
the stages used before the seam. Commands and adapters are discovered from every pack the machine has
(the built-in ones, the user's directory, the installed packs), since a command must exist before a
project is named. The core names no pack: this module reads manifests and loads what they name.
"""
import importlib
import json
import os
import sys

from .model import ontologies as _ontologies
from .project import ProjectError

KINDS = ("stages", "commands", "endpoints", "write_hooks", "read_hooks", "status", "adapters")
BEFORE = "site"                     # contributed stages run before this core stage


class ExtensionError(ProjectError):
    pass


def provides(name):
    """The `provides` section of a pack's manifest, {} when it has none."""
    try:
        manifest = _ontologies.manifest_for(name)
    except (KeyError, _ontologies.OntologyError):
        return {}
    out = manifest.get("provides") or {}
    return out if isinstance(out, dict) else {}


def own_classes(name):
    """The classes a pack declares itself, uncomposed."""
    try:
        raw = _ontologies.load_raw(name)
    except (KeyError, _ontologies.OntologyError):
        return set()
    return set((raw.get("config") or {}).get("classes") or {})


def composed(project):
    """The packs composed in the project: every pack whose own classes are all in the vocabulary."""
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = set(json.load(f).get("classes") or {})
    out = []
    for name in _ontologies.available():
        own = own_classes(name)
        if own and own <= classes:
            out.append(name)
    return out


def code_dir(pack):
    """The pack's own code: `code/` inside the pack's directory, when it has one. The engine's own packs
    carry none; their modules import from the engine."""
    base = _ontologies.dir_for(pack)
    if not base:
        return None
    path = os.path.join(base, "code")
    return path if os.path.isdir(path) else None


def _on_path(pack):
    """Put the pack's code/ first on the import path, once, so what its manifest names imports from
    the pack itself: nothing has to be installed on the machine's Python path for a pack to plug in."""
    path = code_dir(pack)
    if path and path not in sys.path:
        sys.path.insert(0, path)
    return path


def _load(dotted, pack):
    _on_path(pack)
    try:
        return importlib.import_module(dotted)
    except ImportError as exc:
        raise ExtensionError("pack %r provides %s, which does not import: %s" % (pack, dotted, exc))


def _callable(spec, pack):
    module, _sep, name = str(spec).partition(":")
    mod = _load(module, pack)
    fn = getattr(mod, name, None)
    if not callable(fn):
        raise ExtensionError("pack %r provides %s, which names no function" % (pack, spec))
    return fn


# ---- stages ----

def contributed_stages(project):
    """[{name, module, owns, pack}] for the packs composed in the project, in pack then manifest order."""
    out = []
    for name in composed(project):
        for entry in provides(name).get("stages") or []:
            out.append({"name": entry["name"], "module": entry["module"], "owns": list(entry.get("owns") or []), "pack": name})
    return out


def stages(project):
    """The build's stages for the project: the core's, with the composed packs' before the site."""
    from . import builder
    core = list(builder.STAGES)
    extra = []
    for s in contributed_stages(project):
        _on_path(s["pack"])                                   # the pack's code/ on the path before the build imports its stage
        extra.append((s["name"], s["module"]))
    at = next((i for i, (n, _m) in enumerate(core) if n == BEFORE), len(core))
    return core[:at] + extra + core[at:]


# ---- commands ----

def commands():
    """[{name, module, label, pack}] from every pack the machine has."""
    out = []
    for name in _ontologies.available():
        for entry in provides(name).get("commands") or []:
            out.append({"name": entry["name"], "module": entry["module"], "label": entry.get("label") or name, "pack": name})
    return out


# ---- endpoints ----

def routes(project):
    """{"/api/<path>": fn(args) -> (status, object)} from the packs composed in the project."""
    out = {}
    for name in composed(project):
        for module in provides(name).get("endpoints") or []:
            mod = _load(module, name)
            found = getattr(mod, "routes", None)
            if callable(found):
                out.update(found(project) or {})
    return out


# ---- write hooks ----

def before_write(project, action, by):
    """Run every composed pack's write hook; the notes joined, or None. A hook refuses by raising."""
    notes = []
    for name in composed(project):
        for hook in provides(name).get("write_hooks") or []:
            note = _callable(hook, name)(project, action, by)
            if note:
                notes.append(str(note))
    return "; ".join(notes) or None


def read_hooks(project):
    """The composed packs' read hooks, as callables `fn(project, graph, caller, sql)`."""
    out = []
    for name in composed(project):
        for hook in provides(name).get("read_hooks") or []:
            out.append(_callable(hook, name))
    return out


def status_hooks(project):
    """The composed packs' status hooks, as callables `fn(project) -> dict`."""
    out = []
    for name in composed(project):
        for hook in provides(name).get("status") or []:
            out.append(_callable(hook, name))
    return out


# ---- framework adapters ----

def adapters():
    """{framework: {framework, module_name, import, export, pack}} from every pack the machine has."""
    out = {}
    for name in _ontologies.available():
        for entry in provides(name).get("adapters") or []:
            out[entry["framework"]] = {"framework": entry["framework"], "module_name": entry["module"], "import": entry.get("import"),
                                       "export": entry.get("export"), "migrate": entry.get("migrate"), "pack": name}
    return out


def adapter(framework):
    """The adapter for a framework, its module loaded: {..., module, read, write}. Refused by name otherwise."""
    known = adapters()
    entry = known.get(framework)
    if entry is None:
        raise ExtensionError("no adapter for framework %r: the packs on this machine provide %s" % (framework, ", ".join(sorted(known)) or "none"))
    mod = _load(entry["module_name"], entry["pack"])
    return dict(entry, module=mod, read=getattr(mod, entry["import"]) if entry.get("import") else None,
                write=getattr(mod, entry["export"]) if entry.get("export") else None,
                migrate=getattr(mod, entry["migrate"]) if entry.get("migrate") else None)


def only_adapter():
    """The one framework the machine's packs provide, or None when there are none or several."""
    known = sorted(adapters())
    return known[0] if len(known) == 1 else None
