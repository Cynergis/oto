# -*- coding: utf-8 -*-
"""Packs: the full extension a person installs into Claude Code.

A pack wraps one ontology with the skills that know how to use it, the views that show its graph,
and the plugin manifest Claude Code reads. The ontology inside is a copy, with where it came from
recorded, so a pack works with no network and the engine can still say when the registry holds a
newer release of it.

    manifest.json               name, release, domain, summary, the ontology it embeds (name,
                                release, registry, source, ref, path, commit, embedded_at),
                                engine, maintainer, license, changelog
    .claude-plugin/plugin.json  generated from the manifest: name, version "<release>.0.0",
                                description, author, dependencies ["oto"]
    skills/start/SKILL.md       the starter skill, generated; the author's own skills beside it
    ontology/<name>/            the embedded ontology, a copy, and beside it every ontology it
                                extends, so the pack composes with nothing else on the machine
    views/<view>/app.json       views, optional
    README.md                   generated once, then the author's

Packs come from two places:

    ~/.oto/packs/<name>/        yours, written by `oto pack new` (OTO_PACKS overrides), and the
                                ones `oto pack add` fetched, with provenance in the manifest
    any directory path          passed directly

Nothing here talks to a registry except `refresh` and the advisory `newer_ontology`; the registry
side lives in `registry.py`.
"""
import datetime
import json
import os
import re
import shutil

from .. import __version__
from . import ontologies as _ontologies
from . import ontology_manifest as _om

MANIFEST_NAME = "manifest.json"
USER_DIR_ENV = "OTO_PACKS"
ONTOLOGY_DIR = "ontology"
VIEWS_DIR = "views"
SKILLS_DIR = "skills"
PLUGIN_DIR = ".claude-plugin"
START_SKILL = "start"
ENGINE_PLUGIN = "oto"
NAME_OK = re.compile(r"^[a-z][a-z0-9-]*$")
DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ("name", "release", "domain", "summary", "ontology", "engine", "maintainer", "license", "changelog")
ONTOLOGY_FIELDS = ("name", "release", "registry", "source", "ref", "path", "commit", "embedded_at")
#: Written by `oto pack add`, never by an author: where a fetched pack came from.
PROVENANCE = ("registry", "source", "ref", "path", "commit", "fetched_at")
USER = "user"
FETCHED = "fetched"
PATH = "path"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _today():
    return datetime.date.today().isoformat()


# ---- where packs are ----

def user_dir():
    return os.path.expanduser(os.environ.get(USER_DIR_ENV) or os.path.join("~", ".oto", "packs"))


def _is_pack_dir(path):
    return os.path.isdir(path) and os.path.exists(os.path.join(path, MANIFEST_NAME)) \
        and os.path.isdir(os.path.join(path, ONTOLOGY_DIR))


def dir_for(name, roots=None):
    """The directory a pack name resolves to, or None. A name may be a path."""
    if os.sep in name or (os.altsep and os.altsep in name) or name.startswith(".") or name.startswith("~"):
        path = os.path.abspath(os.path.expanduser(name))
        return path if _is_pack_dir(path) else None
    for root in list(roots or []) + [user_dir()]:
        path = os.path.join(root, name)
        if _is_pack_dir(path):
            return path
    return None


def available():
    """Pack names on this machine, sorted."""
    root = user_dir()
    if not os.path.isdir(root):
        return []
    return sorted(name for name in os.listdir(root) if _is_pack_dir(os.path.join(root, name)))


def origin(name):
    path = dir_for(name)
    if path is None:
        return None
    if os.path.dirname(path) == os.path.normpath(user_dir()):
        return FETCHED if read(path).get("source") else USER
    return PATH


# ---- the manifest ----

def path_for(directory):
    return os.path.join(directory, MANIFEST_NAME)


def read(directory):
    """The manifest with defaults filled in. Never raises; `problems` reports a malformed file."""
    manifest = {"name": os.path.basename(os.path.normpath(directory)), "release": 1, "domain": None, "summary": "",
                "ontology": {}, "engine": None, "maintainer": "", "license": None, "changelog": [], "_declared": False}
    path = path_for(directory)
    if not os.path.exists(path):
        return manifest
    try:
        with open(path, encoding="utf-8") as f:
            declared = json.load(f)
    except (OSError, ValueError):
        return manifest
    if not isinstance(declared, dict):
        return manifest
    for key in FIELDS + PROVENANCE:
        if key in declared and declared[key] not in (None, ""):
            manifest[key] = declared[key]
    manifest["_declared"] = True
    return manifest


def write(directory, manifest):
    payload = {key: manifest[key] for key in FIELDS + PROVENANCE if manifest.get(key) not in (None, "", [])}
    payload["_about"] = ("The pack's identity: its release rises on every published change; `ontology` names "
                         "the ontology embedded under ontology/ and where it came from; `domain` is the "
                         "category it belongs to.")
    with open(path_for(directory), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path_for(directory)


def embedded_root(directory):
    """The directory the embedded ontology and its bases live under: a root `ontologies` resolves in."""
    return os.path.join(directory, ONTOLOGY_DIR)


def embedded_name(directory):
    """The embedded ontology's name: the manifest's, else the one directory under ontology/."""
    onto = read(directory).get("ontology") or {}
    if onto.get("name"):
        return onto["name"]
    root = embedded_root(directory)
    names = [n for n in sorted(os.listdir(root))] if os.path.isdir(root) else []
    return names[0] if len(names) == 1 else None


def embedded_dir(directory):
    """The embedded ontology's own directory, or None."""
    name = embedded_name(directory)
    path = os.path.join(embedded_root(directory), name) if name else None
    return path if path and os.path.exists(os.path.join(path, _ontologies.CONFIG_NAME)) else None


def views(directory):
    """The views a pack ships: {name: directory}."""
    base = os.path.join(directory, VIEWS_DIR)
    if not os.path.isdir(base):
        return {}
    return {name: os.path.join(base, name) for name in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, name)) and os.path.exists(os.path.join(base, name, "app.json"))}


def skills(directory):
    """The skills a pack ships: {name: SKILL.md path}."""
    base = os.path.join(directory, SKILLS_DIR)
    if not os.path.isdir(base):
        return {}
    return {name: os.path.join(base, name, "SKILL.md") for name in sorted(os.listdir(base))
            if os.path.isfile(os.path.join(base, name, "SKILL.md"))}


# ---- embedding the ontology ----

def _provenance_of(ontology_dir, given):
    """Where an ontology on this machine came from, for the pack's record."""
    manifest = _ontologies.manifest_dir(ontology_dir)
    where = _ontologies.origin(given) if os.sep not in given else PATH
    record = {"name": manifest["name"], "release": manifest["release"], "registry": manifest.get("registry"),
              "source": manifest.get("source"), "ref": manifest.get("ref"), "path": manifest.get("path"),
              "commit": manifest.get("commit"), "embedded_at": _today()}
    if not record["source"]:
        record["source"] = "built-in" if where == _ontologies.BUILTIN else ("user" if where == _ontologies.USER
                                                                             else ontology_dir)
    return record


def embed(directory, ontology):
    """Copy an ontology (a name on this machine, name@release, or a path) under ontology/ and
    record where it came from. Returns the record. Raises ValueError when it is not usable."""
    from . import registry as _registry
    given, release = _registry.split_release(ontology)
    src = _ontologies.dir_for(given)
    if src is None:
        raise ValueError("unknown ontology %r. Available: %s" % (given, ", ".join(_ontologies.available()) or "none"))
    manifest = _ontologies.manifest_dir(src)
    if release is not None and manifest["release"] != release:
        raise ValueError("ontology %r is at release %s on this machine, not %d: oto ontology add %s@%d"
                         % (given, manifest["release"], release, given, release))
    problems = _ontologies.self_check(given)
    if problems:
        raise ValueError("ontology %r is not usable: %s" % (given, "; ".join(problems[:5])))
    root = embedded_root(directory)
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)
    for part in _ontologies.parts(given):                       # bases first, the ontology last
        part_src = src if part == given or part == manifest["name"] else _ontologies.dir_for(part)
        shutil.copytree(part_src, os.path.join(root, _ontologies.manifest_dir(part_src)["name"]),
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", PLUGIN_DIR, SKILLS_DIR, VIEWS_DIR))
    return _provenance_of(src, given)


def embedded_config(directory):
    """The composed vocabulary of the embedded ontology, or None when it cannot be composed."""
    name = embedded_name(directory)
    try:
        return _ontologies.composed(name, roots=[embedded_root(directory)])["config"] if name else None
    except (KeyError, _ontologies.OntologyError):
        return None


# ---- what the engine generates ----

def plugin_files(directory, registry_name=None):
    """Write `.claude-plugin/plugin.json`, the starter skill and, once, a README, from the
    manifest and the embedded ontology. Returns the paths written."""
    manifest = read(directory)
    raw = _ontologies.load_raw(embedded_name(directory), roots=[embedded_root(directory)])
    title = (raw["config"].get("name") or manifest["name"]).strip()
    onto = manifest.get("ontology") or {}
    written = []

    plugin_dir = os.path.join(directory, PLUGIN_DIR)
    os.makedirs(plugin_dir, exist_ok=True)
    plugin = {"name": manifest["name"], "displayName": "%s (OTO pack)" % title,
              "description": (manifest.get("summary") or "").strip() or "An OTO pack: an ontology, its skills and its views.",
              "version": "%d.0.0" % int(manifest["release"]),
              "author": {"name": manifest.get("maintainer") or registry_name or "OTO"},
              "dependencies": [ENGINE_PLUGIN]}
    if manifest.get("license"):
        plugin["license"] = manifest["license"]
    if manifest.get("domain"):
        plugin["keywords"] = [manifest["domain"], "oto", "knowledge-graph"]
    path = os.path.join(plugin_dir, "plugin.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(plugin, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written.append(path)

    skill_dir = os.path.join(directory, SKILLS_DIR, START_SKILL)
    os.makedirs(skill_dir, exist_ok=True)
    classes = list((raw["config"].get("classes") or {}))
    summary = (manifest.get("summary") or "").strip().rstrip(".")
    lines = ["---", "name: %s" % START_SKILL,
             "description: >-",
             "  Start or extend an OTO knowledge project in this domain: %s. The pack %r (release %d) embeds the "
             "ontology %r (release %s), which declares %s. Use when someone wants a knowledge graph, a vocabulary "
             "or an interview for this domain."
             % (summary, manifest["name"], int(manifest["release"]), onto.get("name"), onto.get("release"),
                ", ".join(classes[:8]) + (" and more" if len(classes) > 8 else "")),
             "---", "",
             "# %s" % title, "",
             (manifest.get("summary") or "").strip(), "",
             "This skill comes with the `%s` pack. The ontology is inside the pack, so nothing is fetched."
             % manifest["name"], "",
             "1. **Start a project from this pack.**", "", "   ```bash",
             '   oto init --name "<project name>" --pack "${CLAUDE_PLUGIN_ROOT}" --project <root>',
             "   ```", "",
             "   `${CLAUDE_PLUGIN_ROOT}` is this pack's directory; Claude Code fills it in. Outside Claude Code,",
             "   with the pack on the machine (`oto pack add %s`%s), `oto init --pack %s` does the same."
             % (manifest["name"], (" from the %s registry" % registry_name) if registry_name else "", manifest["name"]),
             "   The project records the ontology's origin, so `oto status` says when a newer release exists and",
             "   `oto ontology diff` shows what changed.", "",
             "2. **Run the domain interview** with the ontology-interview skill. The project holds `INTERVIEW.md`"
             if raw["interview"] else
             "2. **Run the ontology-interview skill** to fit the vocabulary to the documents at hand.",
             "   with the questions a person who knows this domain asks first; ask them in order, record the"
             if raw["interview"] else None,
             "   answers in `ontology.rationale.json`, then `oto ontology check --strict` and `oto ontology accept`."
             if raw["interview"] else None,
             "",
             "3. **Hand over** to the build-knowledge-base skill for the documents, and to the query-knowledge",
             "   skill for questions. The engine plugin `oto` comes with this pack: the `kg_*` tools and the",
             "   generic skills are available once it is installed.", "",
             "## What the ontology declares", ""]
    for kind in classes:
        lines.append("- **%s**: %s" % (kind, (raw["config"]["classes"].get(kind) or "").strip()))
    if raw.get("actions"):
        lines += ["", "## The actions it ships", "", "OTO lists them; the caller invokes (the act skill):", ""]
        for action in raw["actions"]:
            lines.append("- `%s` on %s: %s" % (action["id"], action.get("subject"), (action.get("description") or "").strip()))
    shipped = views(directory)
    if shipped:
        lines += ["", "## The views it ships", ""]
        for view in shipped:
            lines.append("- `%s`: `oto serve --http <port> --view %s`, or `oto build --target site --view %s`" % (view, view, view))
    if raw.get("guide"):
        lines += ["", "## The guide", "", raw["guide"].strip()]
    if raw["interview"]:
        lines += ["", "## The interview", "", raw["interview"].strip()]
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(line for line in lines if line is not None) + "\n")
    written.append(path)

    readme = os.path.join(directory, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8", newline="\n") as f:
            f.write("# %s\n\n%s\n\nAn OTO pack%s: the ontology `%s` (release %s) under `ontology/`, the skill "
                    "`start` that begins a project from it, and the views under `views/`. Install it in Claude "
                    "Code from the registry's marketplace, or `oto pack add %s` on a machine.\n\n"
                    "`oto pack check` validates it; `oto pack refresh` re-embeds the ontology when the registry "
                    "holds a newer release; `oto pack publish --to <registry>` releases it.\n"
                    % (title, (manifest.get("summary") or "").strip(),
                       (" in the %s domain" % manifest["domain"]) if manifest.get("domain") else "",
                       onto.get("name"), onto.get("release"), manifest["name"]))
        written.append(readme)
    return written


# ---- making, refreshing ----

def new(name, ontology, domain=None, summary=None, view_dirs=(), to=None, force=False, maintainer=None):
    """Scaffold a pack. Returns (directory, problems)."""
    if not NAME_OK.match(name or ""):
        raise ValueError("a pack name is lowercase letters, digits and hyphens, not %r" % (name,))
    if domain and not NAME_OK.match(domain):
        raise ValueError("a domain is a lowercase slug, not %r" % (domain,))
    target = os.path.join(os.path.abspath(to) if to else user_dir(), name)
    if os.path.exists(target) and not force:
        raise FileExistsError(target)
    if os.path.exists(target):
        shutil.rmtree(target)
    os.makedirs(target)
    try:
        record = embed(target, ontology)
    except ValueError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    onto_manifest = _ontologies.manifest_dir(os.path.join(embedded_root(target), record["name"]))
    for source in view_dirs:
        src = os.path.abspath(os.path.expanduser(source))
        if not os.path.exists(os.path.join(src, "app.json")):
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError("%s is not a view: no app.json" % source)
        shutil.copytree(src, os.path.join(target, VIEWS_DIR, os.path.basename(os.path.normpath(src))),
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
    engine = ">=%s" % ".".join(str(x) for x in _om._version_tuple(__version__)[:2])
    write(target, {"name": name, "release": 1, "domain": domain or onto_manifest.get("domain"),
                   "summary": (summary or onto_manifest.get("summary") or "").strip(), "ontology": record,
                   "engine": engine, "maintainer": maintainer or "", "license": None,
                   "changelog": [{"release": 1, "at": _today(), "note": "Made from the ontology %s@%s."
                                  % (record["name"], record["release"])}]})
    plugin_files(target)
    return target, check(target)


def refresh(directory):
    """Re-embed the ontology at its registry's current release, or from this machine when it
    came from here, and regenerate the plugin files. Returns (old release, new release)."""
    from . import registry as _registry
    manifest = read(directory)
    onto = manifest.get("ontology") or {}
    if not onto.get("name"):
        raise ValueError("the pack's manifest names no ontology")
    name, old = onto["name"], onto.get("release")
    if onto.get("registry"):
        _dest, _m = _registry.fetch(name, force=True)
        source = name
    elif onto.get("source") in ("built-in", "user", None):
        source = name
    else:
        source = onto["source"] if _ontologies.dir_for(onto["source"]) else name
    record = embed(directory, source)
    manifest["ontology"] = record
    write(directory, manifest)
    plugin_files(directory)
    return old, record["release"]


# ---- what is wrong, and what is worth knowing ----

VERSION_DIR = re.compile(r"^\d+(\.\d+)*$")


def _installed_as(name, directory):
    """Claude Code installs a plugin under <marketplace>/<plugin>/<version>/, so the directory a
    pack's start skill passes as ${CLAUDE_PLUGIN_ROOT} is named for the release, and its parent for
    the pack. That layout is the pack's, not a mistake."""
    norm = os.path.normpath(directory)
    return bool(VERSION_DIR.match(os.path.basename(norm))) and os.path.basename(os.path.dirname(norm)) == name


def _manifest_problems(directory):
    out = []
    path = path_for(directory)
    if not os.path.exists(path):
        return ["no %s" % MANIFEST_NAME]
    try:
        with open(path, encoding="utf-8") as f:
            declared = json.load(f)
    except ValueError as exc:
        return ["%s is not valid JSON: %s" % (MANIFEST_NAME, exc)]
    if not isinstance(declared, dict):
        return ["%s must be a JSON object" % MANIFEST_NAME]
    name = declared.get("name")
    if not isinstance(name, str) or not NAME_OK.match(name):
        out.append("%s name %r must be lowercase letters, digits and hyphens" % (MANIFEST_NAME, name))
    elif name != os.path.basename(os.path.normpath(directory)) and not _installed_as(name, directory):
        out.append("%s names %r but the directory is %r" % (MANIFEST_NAME, name, os.path.basename(os.path.normpath(directory))))
    release = declared.get("release", 1)
    if not isinstance(release, int) or isinstance(release, bool) or release < 1:
        out.append("%s release must be a positive integer, not %r" % (MANIFEST_NAME, release))
    out += _om.domain_problems(declared.get("domain"), MANIFEST_NAME)
    onto = declared.get("ontology")
    if not isinstance(onto, dict) or not isinstance(onto.get("name"), str) or not isinstance(onto.get("release"), int):
        out.append("%s needs `ontology` with the embedded ontology's `name` and `release`" % MANIFEST_NAME)
    engine = declared.get("engine")
    if engine is not None:
        ok = _om.satisfies(engine)
        if ok is None:
            out.append("%s engine %r is not a spec this engine reads (use \">=x.y\")" % (MANIFEST_NAME, engine))
        elif not ok:
            out.append("%s needs engine %s and this engine is %s" % (MANIFEST_NAME, engine, __version__))
    changelog = declared.get("changelog", [])
    if not isinstance(changelog, list):
        out.append("%s changelog must be a list" % MANIFEST_NAME)
    else:
        for index, entry in enumerate(changelog, 1):
            if not isinstance(entry, dict) or not isinstance(entry.get("release"), int) \
                    or not isinstance(entry.get("note"), str) or not entry.get("note", "").strip():
                out.append("%s changelog entry %d needs an integer release and a note" % (MANIFEST_NAME, index))
            elif entry.get("at") and not DATE_OK.match(str(entry["at"])):
                out.append("%s changelog entry %d: `at` must be YYYY-MM-DD" % (MANIFEST_NAME, index))
    return out


def check(directory):
    """Problems with a pack. An empty list means it is usable and publishable."""
    from ..apps import manifest as _apps
    problems = _manifest_problems(directory)
    manifest = read(directory)
    onto_dir = embedded_dir(directory)
    if onto_dir is None:
        problems.append("no embedded ontology: ontology/<name>/ must hold the ontology the manifest names "
                        "(oto pack new, or oto pack refresh)")
        return problems
    for problem in _ontologies.self_check(embedded_name(directory), roots=[embedded_root(directory)]):
        problems.append("ontology: %s" % problem)
    embedded = _ontologies.manifest_dir(onto_dir)
    onto = manifest.get("ontology") or {}
    if onto.get("name") and embedded["name"] != onto["name"]:
        problems.append("the manifest says the ontology is %r but ontology/ holds %r" % (onto["name"], embedded["name"]))
    if onto.get("release") is not None and embedded["release"] != onto["release"]:
        problems.append("the manifest says ontology release %s but ontology/ is at release %s: oto pack refresh"
                        % (onto["release"], embedded["release"]))
    config = embedded_config(directory)
    if config is not None:
        for view, vdir in views(directory).items():
            for problem in _apps.problems(vdir, config):
                problems.append("view %s: %s" % (view, problem))
    for name in sorted(os.listdir(os.path.join(directory, VIEWS_DIR))) if os.path.isdir(os.path.join(directory, VIEWS_DIR)) else []:
        if os.path.isdir(os.path.join(directory, VIEWS_DIR, name)) and name not in views(directory):
            problems.append("views/%s has no app.json" % name)
    shipped = skills(directory)
    if START_SKILL not in shipped:
        problems.append("no starter skill skills/%s/SKILL.md (oto pack refresh writes it)" % START_SKILL)
    skills_root = os.path.join(directory, SKILLS_DIR)
    if os.path.isdir(skills_root):
        for name in sorted(os.listdir(skills_root)):
            if os.path.isdir(os.path.join(skills_root, name)) and name not in shipped:
                problems.append("skills/%s has no SKILL.md" % name)
    for name, path in shipped.items():
        with open(path, encoding="utf-8") as f:
            head = f.read(400)
        if not head.startswith("---\n") or ("\nname: %s\n" % name) not in head:
            problems.append("skills/%s/SKILL.md must start with frontmatter naming it `%s`" % (name, name))
    plugin_path = os.path.join(directory, PLUGIN_DIR, "plugin.json")
    if not os.path.exists(plugin_path):
        problems.append("no %s/plugin.json (oto pack refresh writes it)" % PLUGIN_DIR)
    else:
        try:
            with open(plugin_path, encoding="utf-8") as f:
                plugin = json.load(f)
            if plugin.get("name") != manifest["name"]:
                problems.append("plugin.json names %r, the pack is %r" % (plugin.get("name"), manifest["name"]))
            if plugin.get("version") != "%d.0.0" % int(manifest["release"]):
                problems.append("plugin.json version %r is not release %s (oto pack refresh)" % (plugin.get("version"), manifest["release"]))
            if ENGINE_PLUGIN not in (plugin.get("dependencies") or []):
                problems.append("plugin.json must depend on the engine plugin %r" % ENGINE_PLUGIN)
        except ValueError as exc:
            problems.append("plugin.json is not valid JSON: %s" % exc)
    problems += publishability_problems(directory)
    return problems


def publishability_problems(directory):
    """Deny terms in any text file of the pack, and personal data in the embedded sample."""
    out = []
    terms = sorted({t.strip().lower() for t in os.environ.get("OTO_DENY_TERMS", "").split(",") if t.strip()})
    if terms:
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))
            for filename in sorted(filenames):
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, encoding="utf-8") as f:
                        text = f.read().lower()
                except (OSError, UnicodeDecodeError):
                    continue
                hits = [t for t in terms if t in text]
                if hits:
                    out.append("%s names a deny term (%s); a pack must not" % (os.path.relpath(path, directory), ", ".join(hits)))
    name = embedded_name(directory)
    if name and embedded_dir(directory):
        try:
            for problem in _ontologies.publishability_problems(name, roots=[embedded_root(directory)]):
                if "deny term" not in problem:
                    out.append("ontology: %s" % problem)
        except (KeyError, _ontologies.OntologyError):
            pass
    return out


def newer_ontology(manifest):
    """The registry's release of the embedded ontology when newer, from local knowledge only."""
    from . import registry as _registry
    onto = manifest.get("ontology") or {}
    if not onto.get("name"):
        return None
    _record, entry = _registry.find(onto["name"])
    if entry is None:
        local = _ontologies.dir_for(onto["name"])
        current = _ontologies.manifest_dir(local)["release"] if local else None
    else:
        current = int(entry.get("release") or 1)
    return current if current is not None and int(current) > int(onto.get("release") or 0) else None


def notes(directory):
    """Advisory lines: a domain the engine has not seen, a newer ontology release."""
    manifest = read(directory)
    out = []
    note = _om.domain_note(manifest.get("domain"))
    if note:
        out.append(note)
    try:
        newer = newer_ontology(manifest)
    except Exception:                                                   # noqa: BLE001 - advisory only
        newer = None
    if newer:
        out.append("the ontology %s is at release %s upstream, this pack embeds release %s: oto pack refresh"
                   % (manifest["ontology"].get("name"), newer, manifest["ontology"].get("release")))
    return out


def summary(name):
    """One line for a listing."""
    directory = dir_for(name)
    manifest = read(directory)
    onto = manifest.get("ontology") or {}
    return {"name": manifest["name"], "release": manifest["release"], "domain": manifest.get("domain"),
            "about": (manifest.get("summary") or "").strip(), "ontology": onto.get("name"),
            "ontology_release": onto.get("release"), "views": sorted(views(directory)),
            "skills": sorted(skills(directory)), "origin": origin(name)}
