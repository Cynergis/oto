# -*- coding: utf-8 -*-
"""Packs: the full extension a person installs into Claude Code.

A pack wraps one ontology with the skills that know how to use it, the views that show its graph,
and the plugin manifest Claude Code reads. The ontology inside is a copy, with where it came from
recorded, so a pack works with no network and the engine can still say when the registry holds a
newer release of it.

    manifest.json               name, title, release, domain, summary, the ontology it embeds (name,
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
import contextlib
import io
import json
import os
import re
import shutil
import tempfile

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
ENGINE_MARKETPLACE = "cynergis-engine"           # the engine's own marketplace (Cynergis/oto, .claude-plugin/marketplace.json)
ENGINE_DEPENDENCY = "%s@%s" % (ENGINE_PLUGIN, ENGINE_MARKETPLACE)   # how a pack names it: a registry carries no engine (ADR-0009)
NAME_OK = re.compile(r"^[a-z][a-z0-9-]*$")
DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ("name", "title", "release", "domain", "product_type", "pattern", "playbook", "binding", "summary", "ontology", "engine", "maintainer",
          "license", "changelog", "routes")
#: The routes' policy a pack carries (docs/plans/graph-journeys.md, phase 6): which routes a project on it may use
#: (`allowed`, reviewed always among them), the classes a session may touch without review (`session.classes`),
#: and the guardrailed route's settings. Derived into the project at init and on update; which route a change
#: takes is never here (ADR-0013).
ROUTES = ("session", "reviewed", "guardrailed")
ROUTE_KEYS = ("allowed",) + ROUTES
GUARDRAILED_KEYS = {"from": str, "classes": list, "max_facts": int, "additive_only": bool, "attributed": bool}
#: A pattern pack declares what it is a design pattern of, for which part, and the skill that models
#: that part: {"of": "software-architecture", "for": "a part designed with DDD", "skill": "model-domain"}.
#: An architecture skill finds the patterns a project composes from this, never by their names.
PATTERN_KEYS = ("of", "for", "skill")
#: A playbook pack declares the journey one of its skills leads, from start to end: {"for": "a product,
#: from an idea to a published knowledge base", "skill": "atlas"}. The concierge offers the playbooks
#: it finds (`oto status`, `oto pack list --playbooks`), never by their names.
PLAYBOOK_KEYS = ("for", "skill")
#: A binding pack declares what it binds to a platform, and the skill that captures the binding:
#: {"of": "software-architecture", "for": "where each part runs and what it is built with",
#: "skill": "bind-platform"}. The design stays platform-neutral; the architecture skill finds the
#: bindings a project composes (`oto status`, `oto pack list --bindings`), never by their names.
BINDING_KEYS = ("of", "for", "skill")
#: How every skill talks with the person: the engine's skills carry it, and so does every pack's
#: generated start skill. Technical details (ids, commands, output) are the record's, not the talk's.
TALKING = ["## Talking with the person", "",
           "- **Plain, natural language, in the person's words.** Never say question numbers, ids, class or",
           "  field names, file names or commands, and never paste what a command printed.",
           "- **Technical details only when the person asks for them.** Never offer them, not even as a choice.",
           "- **The same clear shape every time:** say what we are about to do, ask a few questions at a time,",
           "  read back what you understood in plain sentences, confirm, then say what is next."]
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


def remove(name):
    """Delete the pack `name` from the packs directory, the one `add` and `new` write to, and return
    the directory it was. A name, never a path: a pack elsewhere is not the catalog's. A pack Claude
    Code installed is refused with the plugin command that removes it. A project built on the pack
    keeps the vocabulary it derived; what goes is the pack's copy on this machine."""
    from ..project import ProjectError
    if os.sep in name or (os.altsep and os.altsep in name) or name.startswith(".") or name.startswith("~"):
        raise ProjectError("rm takes a pack's name, never a path: %s" % name)
    path = os.path.join(user_dir(), name)
    if not _is_pack_dir(path):
        for root in _ontologies._pack_roots():
            pack_dir = os.path.dirname(os.path.normpath(root))
            if read(pack_dir)["name"] == name and os.path.dirname(pack_dir) != os.path.normpath(user_dir()):
                raise ProjectError("pack %r was installed by Claude Code (%s): /plugin uninstall %s removes it" % (name, pack_dir, name))
        raise ProjectError("no pack named %r here (installed: %s)" % (name, ", ".join(available()) or "none"))
    shutil.rmtree(path)
    return path


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


def frontmatter(text):
    """(fields, body) of a SKILL.md."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    fields, key = {}, None
    for line in text[4:end].splitlines():
        m = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1); fields[key] = m.group(2).strip().lstrip(">-").strip()
        elif key and line.startswith("  "):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields, text[end + 4:].lstrip("\n")


def _skill_summary(path):
    """What a skill does, in one clause: its description up to the first colon or full stop."""
    with open(path, encoding="utf-8") as f:
        description = frontmatter(f.read())[0].get("description") or ""
    return re.split(r":\s|\.\s|\.$", description, maxsplit=1)[0].strip()


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
    # The sources are resolved and copied aside before anything under ontology/ is removed: when the
    # ontology resolves to this pack's own embedded copy (a pack refreshed on a machine whose packs
    # directory holds it, the usual case since ADR-0011), removing first would delete what is copied.
    sources = []
    for part in _ontologies.parts(given):                       # bases first, the ontology last
        part_src = src if part == given or part == manifest["name"] else _ontologies.dir_for(part)
        sources.append((_ontologies.manifest_dir(part_src)["name"], part_src))
    provenance = _provenance_of(src, given)
    staging = tempfile.mkdtemp(prefix="oto-embed-")
    try:
        for name, part_src in sources:
            shutil.copytree(part_src, os.path.join(staging, name),
                            ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", PLUGIN_DIR, SKILLS_DIR, VIEWS_DIR))
        if os.path.exists(root):
            shutil.rmtree(root)
        os.makedirs(root)
        for name, _part_src in sources:
            shutil.move(os.path.join(staging, name), os.path.join(root, name))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return provenance


def own_config(directory):
    """The pack's own vocabulary file, uncomposed: what the pack itself declares; {} without one."""
    onto_dir = embedded_dir(directory)
    path = os.path.join(onto_dir, "ontology.config.json") if onto_dir else None
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def embedded_manifest(directory):
    """The embedded ontology's manifest, defaults filled in; {} without one."""
    onto_dir = embedded_dir(directory)
    return _ontologies.manifest_dir(onto_dir) if onto_dir else {}


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
    # A pack broader than its ontology (a studio over `product`) names itself; otherwise the ontology's name.
    title = (manifest.get("title") or raw["config"].get("name") or manifest["name"]).strip()
    onto = manifest.get("ontology") or {}
    written = []

    plugin_dir = os.path.join(directory, PLUGIN_DIR)
    os.makedirs(plugin_dir, exist_ok=True)
    plugin = {"name": manifest["name"], "displayName": "%s (OTO pack)" % title,
              "description": (manifest.get("summary") or "").strip() or "An OTO pack: an ontology, its skills and its views.",
              "version": "%d.0.0" % int(manifest["release"]),
              "author": {"name": manifest.get("maintainer") or registry_name or "OTO"},
              "dependencies": [ENGINE_DEPENDENCY]}
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
             % manifest["name"], ""] + TALKING + [""]
    pattern = manifest.get("pattern")
    if isinstance(pattern, dict) and all(isinstance(pattern.get(k), str) for k in PATTERN_KEYS):
        lines += ["**A design pattern of `%s`**: for %s. In a project that composes `%s`, such a part is modelled"
                  % (pattern["of"], pattern["for"].rstrip("."), pattern["of"]),
                  "with this pack's **%s** skill (`/%s:%s`); `oto status` lists the project's patterns."
                  % (pattern["skill"], manifest["name"], pattern["skill"]), ""]
    playbook = manifest.get("playbook")
    if isinstance(playbook, dict) and all(isinstance(playbook.get(k), str) for k in PLAYBOOK_KEYS):
        lines += ["**A playbook**: for %s. This pack's **%s** skill (`/%s:%s`) leads it from start to end; OTO's"
                  % (playbook["for"].rstrip("."), playbook["skill"], manifest["name"], playbook["skill"]),
                  "concierge offers it, and says where the project is at any point.", ""]
    binding = manifest.get("binding")
    if isinstance(binding, dict) and all(isinstance(binding.get(k), str) for k in BINDING_KEYS):
        lines += ["**A binding of `%s`**: for %s. In a project that composes `%s`, the binding is captured"
                  % (binding["of"], binding["for"].rstrip("."), binding["of"]),
                  "with this pack's **%s** skill (`/%s:%s`); `oto status` lists the project's bindings."
                  % (binding["skill"], manifest["name"], binding["skill"]), ""]
    lines += [
             "1. **Start a project from this pack.**", "", "   ```bash",
             '   oto init --name "<project name>" --pack "${CLAUDE_PLUGIN_ROOT}" --project <root>',
             "   ```", "",
             "   `${CLAUDE_PLUGIN_ROOT}` is this pack's directory; Claude Code fills it in. Outside Claude Code,",
             "   with the pack on the machine (`oto pack add %s`%s), `oto init --pack %s` does the same."
             % (manifest["name"], (" from the %s registry" % registry_name) if registry_name else "", manifest["name"]),
             "   The project records the ontology's origin, so `oto status` says when a newer release exists and",
             "   `oto ontology diff` shows what changed. Add `--ontology <name>,...` to merge other ontologies",
             "   with the pack's (a product type, the flow).", ""]
    # A pack that ships skills of its own hands over to them, then to the engine's generic skills for
    # what they do not cover; a pack with no skills of its own hands over to the generic ones.
    own = {name: path for name, path in skills(directory).items() if name != START_SKILL}
    if own:
        lines += ["2. **Go on with this pack's skills**, written for this domain:", ""]
        for name, path in own.items():
            what = _skill_summary(path)
            lines.append("   - **%s:%s**%s" % (manifest["name"], name, (": %s." % what) if what else ""))
        lines += ["",
                  "3. **For anything else, the engine's skills**: capture-form to answer the vocabulary's",
                  "   questions in an interview, ontology-interview to fit the vocabulary to the documents at hand%s,"
                  % (" (the domain interview below first)" if raw["interview"] else ""),
                  "   build-knowledge-base for a folder of documents, query-knowledge for questions. The engine",
                  "   plugin `oto` comes with this pack: the `kg_*` tools and the generic skills are available once",
                  "   it is installed.", ""]
    else:
        lines += ["2. **Run the domain interview** with the ontology-interview skill. The project holds `INTERVIEW.md`"
                  if raw["interview"] else
                  "2. **Run the ontology-interview skill** to fit the vocabulary to the documents at hand.",
                  "   with the questions a person who knows this domain asks first; ask them in order, record the"
                  if raw["interview"] else None,
                  "   answers in `ontology.rationale.json`, then `oto ontology check --strict` and `oto ontology accept`."
                  if raw["interview"] else None,
                  "",
                  "3. **Hand over** to the build-knowledge-base skill for the documents, and to the query-knowledge",
                  "   skill for questions. The engine plugin `oto` comes with this pack: the `kg_*` tools and the",
                  "   generic skills are available once it is installed.", ""]
    lines += ["## What the ontology declares", ""]
    for kind in classes:
        lines.append("- **%s**: %s" % (kind, (raw["config"]["classes"][kind].get("definition") or "").strip()))
    if raw.get("tools"):
        lines += ["", "## The tools it ships", "", "OTO lists them; the caller invokes (the act skill):", ""]
        for action in raw["tools"]:
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

def new(name, ontology=None, domain=None, summary=None, view_dirs=(), to=None, force=False, maintainer=None,
        extends=(), from_project=None, into=None):
    """Scaffold a pack. Returns (directory, problems).

    With `ontology`, a pack around an ontology this machine has, as before. With `from_project`, a
    workspace opened from a project that grew its own vocabulary: the bridge for a vocabulary made
    before the workspace existed. With neither, a workspace with a starter vocabulary to fill (the
    interview's job), resting on the bases `extends` names (oto-core when none). Under `to`, the pack
    is a directory of its own and gets what a workspace has: a trial project beside the deliverable
    and the two workflows; under the packs directory it is an installed pack and gets neither
    (docs/plans/ontology-workspace.md)."""
    if not NAME_OK.match(name or ""):
        raise ValueError("a pack name is lowercase letters, digits and hyphens, not %r" % (name,))
    if domain and not NAME_OK.match(domain):
        raise ValueError("a domain is a lowercase slug, not %r" % (domain,))
    if sum(1 for x in (ontology, from_project) if x) > 1:
        raise ValueError("new takes one of --ontology and --from-project")
    # `into`: this exact directory is the workspace (the sandbox's project folder, say), empty or missing
    target = os.path.abspath(os.path.expanduser(into)) if into else os.path.join(os.path.abspath(to) if to else user_dir(), name)
    if os.path.exists(target) and not force and (not into or os.listdir(target)):
        raise FileExistsError(target)
    if os.path.exists(target) and (not into or force):
        shutil.rmtree(target)
    os.makedirs(target, exist_ok=True)
    exported = None
    try:
        if from_project:
            from ..project import Project
            exported = tempfile.mkdtemp(prefix="oto-from-project-")
            path, problems = _ontologies.export(Project.standard(os.path.abspath(from_project)), name, to=exported,
                                                summary=summary, force=True)
            if problems:
                raise ValueError("the project's vocabulary is not ready to be an ontology: %s" % "; ".join(problems[:5]))
            record = embed(target, path)
            record["source"] = os.path.abspath(from_project)            # where it came from: the project, not the export's temp dir
            # `export` empties validated_by, since a confirmation does not carry to a new domain; a workspace
            # opened from the project is the same vocabulary, confirmed by the same people, so it keeps them
            own_rationale = os.path.join(os.path.abspath(from_project), "ontology.rationale.json")
            if os.path.exists(own_rationale):
                shutil.copyfile(own_rationale, os.path.join(embedded_root(target), record["name"], "ontology.rationale.json"))
        elif ontology:
            record = embed(target, ontology)
        else:
            record = _starter(target, name, list(extends) or ["oto-core"], domain)
    except ValueError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if exported:
            shutil.rmtree(exported, ignore_errors=True)
    onto_manifest = _ontologies.manifest_dir(os.path.join(embedded_root(target), record["name"]))
    for source in view_dirs:
        src = os.path.abspath(os.path.expanduser(source))
        if not os.path.exists(os.path.join(src, "app.json")):
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError("%s is not a view: no app.json" % source)
        shutil.copytree(src, os.path.join(target, VIEWS_DIR, os.path.basename(os.path.normpath(src))),
                        ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
    engine = ">=%s" % ".".join(str(x) for x in _om._version_tuple(__version__)[:2])
    write(target, {"name": name, "release": 1, "domain": domain or onto_manifest.get("domain"), "product_type": onto_manifest.get("product_type"),
                   "summary": (summary or onto_manifest.get("summary") or "").strip(), "ontology": record,
                   "engine": engine, "maintainer": maintainer or "", "license": None,
                   "changelog": [{"release": 1, "at": _today(), "note": "Made from the ontology %s@%s."
                                  % (record["name"], record["release"])}]})
    plugin_files(target)
    if to or into:
        workspace(target)
    return target, check(target)


# ---- the workspace: a pack in the making, with a trial project beside it ----

TRIAL_DIR = "trial"


def is_workspace(directory):
    """A pack in the making, in a directory of its own: it has a trial project beside the deliverable."""
    return os.path.isdir(os.path.join(directory, TRIAL_DIR))
WORKFLOWS_DIR = os.path.join(".github", "workflows")
#: What `oto pack publish` leaves behind: the workspace's own, never the pack's
WORKSPACE_ONLY = (TRIAL_DIR, ".github")
TRIAL_ABOUT = ("The trial project's vocabulary, written from the pack beside it by `oto pack try`: what ontology/%s composes "
               "with the bases it embeds. Do not edit it here; edit the pack's ontology/%s/ and run `oto pack try` again. "
               "The documents, proposals and graph of this project are its own and survive a try.")
PACK_CHECK_WORKFLOW = """name: pack check

# On every pull request and push: the pack's own gates. `oto pack check --strict` holds the vocabulary to its
# three gates (shapes, a question citing every term, a sample that answers) and the rationale (a reason and a
# confirmation per term), then the pack's tests, when it carries some, run against the engine.
on:
  pull_request:
  push:
    branches: [ main ]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the engine
        run: python -m pip install "oto-kg @ git+https://github.com/Cynergis/oto"
      - name: The pack's gates
        run: oto pack check . --strict
      - name: The pack's tests, when it has some
        run: if [ -d tests ]; then python -m pip install pytest && python -m pytest tests -q -p no:cacheprovider; fi
"""
PACK_PUBLISH_WORKFLOW = """name: pack publish

# A release of the pack: on a tag, or by hand. `oto pack publish` raises the release, regenerates the plugin
# files, appends the changelog note and pushes to the registry named in the repository variable OTO_REGISTRY
# (its git URL), with the token in the secret OTO_REGISTRY_TOKEN when the registry is private.
on:
  push:
    tags: [ "v*" ]
  workflow_dispatch:
    inputs:
      note:
        description: the changelog note for this release
        required: true

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the engine
        run: python -m pip install "oto-kg @ git+https://github.com/Cynergis/oto"
      - name: Publish the pack
        env:
          OTO_REGISTRY_TOKEN: ${{ secrets.OTO_REGISTRY_TOKEN }}
        run: oto pack publish --from . --to "${{ vars.OTO_REGISTRY }}" --note "${{ github.event.inputs.note || github.ref_name }}"
"""


def _starter(target, name, extends, domain):
    """A vocabulary to fill, resting on its bases: the files the interview writes, empty but well formed,
    and every base embedded beside it. Returns the pack's ontology record."""
    from .. import scaffold as _scaffold
    root = embedded_root(target)
    os.makedirs(os.path.join(root, name))
    for base in extends:
        if _ontologies.dir_for(base) is None:
            raise ValueError("unknown ontology %r to extend. Available: %s" % (base, ", ".join(_ontologies.available()) or "none"))
        for part in _ontologies.parts(base):
            src = _ontologies.dir_for(part)
            dest = os.path.join(root, _ontologies.manifest_dir(src)["name"])
            if not os.path.exists(dest):
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", PLUGIN_DIR, SKILLS_DIR, VIEWS_DIR))
    from . import ontology_manifest as _manifest
    engine = ">=%s" % ".".join(str(x) for x in _om._version_tuple(__version__)[:2])
    _manifest.write(os.path.join(root, name), {"name": name, "release": 1, "domain": domain, "summary": "", "extends": list(extends),
                                               "namespace": "https://example.org/ont/%s#" % name,        # the author's to change before a release
                                               "engine": engine, "carries": ["vocabulary", "rationale", "questions", "sample", "readme"],
                                               "maintainer": "", "changelog": [{"release": 1, "at": _today(), "note": "Started in a workspace: oto pack new."}]})
    config = {"_about": "The vocabulary this pack delivers. Empty until the interview fills it: classes, relations and attributes "
                        "derived from the questions the graph must answer (the ontology-interview skill); `oto pack check` holds "
                        "it to its gates, `oto pack try` tries it in the trial project beside this pack.",
              "name": name, "ontology_version": 1, "strict_domains": False, "languages": ["en"], "classes": {}, "properties": {}}
    if not extends:
        config["temporal"] = _scaffold.TEMPORAL
    files = {"ontology.config.json": config,
             "ontology.rationale.json": {"_about": "Why each class and relation exists, the alternatives considered, and who confirmed it.", "classes": {}, "properties": {}},
             "questions.json": {"_about": "What a graph in this vocabulary must answer; a term no question cites has no reason to exist.", "questions": {}},
             "sample.graph.json": {"nodes": [], "edges": []}}
    for filename, payload in files.items():
        with open(os.path.join(root, name, filename), "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
    with open(os.path.join(root, name, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s\n\nA vocabulary in the making. The interview writes the classes, the relations, why each exists and the "
                "questions the graph must answer; this file says what the domain is and how to read a graph in it.\n" % name)
    return {"name": name, "release": 1, "registry": None, "source": "workspace", "ref": None, "path": None, "commit": None,
            "embedded_at": _today()}


def workspace(directory):
    """Give a pack directory what a workspace has: a trial project beside the deliverable and the two
    workflows. The trial starts bare; `try_` writes its vocabulary from the pack when the pack is usable."""
    from .. import scaffold as _scaffold
    from . import lock as _lock
    name = read(directory)["name"]
    trial = os.path.join(directory, TRIAL_DIR)
    if not os.path.exists(os.path.join(trial, "project.config.json")):
        with contextlib.redirect_stdout(io.StringIO()):
            _scaffold.init(trial, slug="%s-trial" % name, name="%s, tried" % name.replace("-", " ").title())
        _lock.own(trial)                    # the engine alone: never the packs of the machine that laid it out
        path = os.path.join(trial, "project.config.json")
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        config["trial_of"] = name
        config["_about"] = ("The trial project of the pack %s beside it: where sample documents are read and the vocabulary is tried. "
                            "Its vocabulary is written from the pack by `oto pack try`; its documents, proposals and graph are its own. "
                            "Never published." % name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")
    os.makedirs(os.path.join(directory, WORKFLOWS_DIR), exist_ok=True)
    for filename, text in (("pack-check.yml", PACK_CHECK_WORKFLOW), ("pack-publish.yml", PACK_PUBLISH_WORKFLOW)):
        path = os.path.join(directory, WORKFLOWS_DIR, filename)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    if not _ontologies.self_check(embedded_name(directory), roots=[embedded_root(directory)]):
        try_(directory)
    return trial


def try_(directory):
    """Write the trial project's vocabulary from the pack, build it and ask its questions. Returns
    (exit code, what `oto ontology check` said of the trial). Raises ValueError when the pack is not usable."""
    from ..cli import main as _main
    from ..project import Project
    from ..reason import questions as _questions, rules as _rules
    name = embedded_name(directory)
    roots = [embedded_root(directory)]
    problems = _ontologies.self_check(name, roots=roots)
    if problems:
        raise ValueError("the pack's vocabulary is not usable yet: %s" % "; ".join(problems[:5]))
    trial = os.path.join(directory, TRIAL_DIR)
    if not os.path.exists(os.path.join(trial, "project.config.json")):
        workspace(directory)
    project = Project.standard(trial)
    result = _ontologies.composed(name, roots=roots)
    config = dict(result["config"], name=project.config().get("name") or name)
    config["_about"] = TRIAL_ABOUT % (name, name)
    with open(project.ontology_config_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    _questions.save(project, dict(result["questions"] or {}))
    if result["rules"]:
        _rules.save(project, list(result["rules"]))
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    # A trial that holds no fact in the pack's own classes yet (only what a bare project starts with: the
    # engine's sample documents and its own descriptor) starts from the pack's sample, so the questions have
    # something to answer; once it holds facts of its own, they are its own and stay.
    own = set(own_config(directory).get("classes") or {})
    if not [n for n in (graph.get("nodes") or []) if n.get("type") in own]:
        have = {n.get("id") for n in (graph.get("nodes") or [])}
        graph["nodes"] = list(graph.get("nodes") or []) + [n for n in (result["sample"].get("nodes") or []) if n.get("id") not in have]
        graph["edges"] = list(graph.get("edges") or []) + list(result["sample"].get("edges") or [])
        with open(project.graph_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)
            f.write("\n")
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = _main(["build", "--project", trial])
    if code != 0:
        return code, out.getvalue()
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = _main(["ontology", "check", "--project", trial])
    return code, out.getvalue()


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
    elif name != os.path.basename(os.path.normpath(directory)) and not _installed_as(name, directory) and not is_workspace(directory):
        # an installed pack lives under its name; a workspace is a repository and may be called anything (a sandbox's project folder)
        out.append("%s names %r but the directory is %r" % (MANIFEST_NAME, name, os.path.basename(os.path.normpath(directory))))
    release = declared.get("release", 1)
    if not isinstance(release, int) or isinstance(release, bool) or release < 1:
        out.append("%s release must be a positive integer, not %r" % (MANIFEST_NAME, release))
    out += _om.domain_problems(declared.get("domain"), MANIFEST_NAME)
    out += _om.product_type_problems(declared.get("product_type"), MANIFEST_NAME)
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
    pattern = declared.get("pattern")
    if pattern is not None and (not isinstance(pattern, dict) or set(pattern) != set(PATTERN_KEYS)
                                or not all(isinstance(pattern[k], str) and pattern[k].strip() for k in PATTERN_KEYS)):
        out.append("%s pattern must be {\"of\": <the ontology it is a pattern of>, \"for\": <which part, in a phrase>, "
                   "\"skill\": <this pack's skill that models it>}" % MANIFEST_NAME)
    playbook = declared.get("playbook")
    if playbook is not None and (not isinstance(playbook, dict) or set(playbook) != set(PLAYBOOK_KEYS)
                                 or not all(isinstance(playbook[k], str) and playbook[k].strip() for k in PLAYBOOK_KEYS)):
        out.append("%s playbook must be {\"for\": <which journey, in a phrase>, \"skill\": <this pack's skill that "
                   "leads it>}" % MANIFEST_NAME)
    binding = declared.get("binding")
    if binding is not None and (not isinstance(binding, dict) or set(binding) != set(BINDING_KEYS)
                                or not all(isinstance(binding[k], str) and binding[k].strip() for k in BINDING_KEYS)):
        out.append("%s binding must be {\"of\": <the ontology it binds to a platform>, \"for\": <what it binds, in a "
                   "phrase>, \"skill\": <this pack's skill that captures it>}" % MANIFEST_NAME)
    routes = declared.get("routes")
    if routes is not None:
        known = set((embedded_config(directory) or {}).get("classes") or {})
        out += routes_problems(routes, known, MANIFEST_NAME)
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


def routes_problems(routes, known_classes, where="routes"):
    """What is wrong with a `routes` section, in words: unknown keys or routes, `reviewed` missing from
    `allowed`, a class the vocabulary does not declare, a setting of the wrong shape. `known_classes`
    is the set of classes to hold the lists to; empty, the classes are not checked."""
    out = []
    if not isinstance(routes, dict):
        return ["%s routes must be an object with allowed, session, reviewed and guardrailed" % where]
    for key in routes:
        if key not in ROUTE_KEYS:
            out.append("%s routes has no key %r (known: %s)" % (where, key, ", ".join(ROUTE_KEYS)))
    allowed = routes.get("allowed")
    if allowed is not None:
        if not isinstance(allowed, list) or not allowed or not all(isinstance(r, str) for r in allowed):
            out.append("%s routes.allowed must be a non-empty list of route names" % where)
        else:
            for name in allowed:
                if name not in ROUTES:
                    out.append("%s routes.allowed names %r, not a route (%s)" % (where, name, ", ".join(ROUTES)))
            if "reviewed" not in allowed:
                out.append("%s routes.allowed must include reviewed: it is the route everything else falls back to" % where)

    def classes_ok(value, label):
        if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
            out.append("%s %s must be a list of classes, not %r" % (where, label, value))
            return
        unknown = sorted(c for c in value if known_classes and c not in known_classes)
        if unknown:
            out.append("%s %s names %s, which the vocabulary does not declare" % (where, label, ", ".join(unknown)))

    for name in ("session", "reviewed"):
        section = routes.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            out.append("%s routes.%s must be an object" % (where, name))
            continue
        for key in section:
            if key != "classes":
                out.append("%s routes.%s has no key %r (known: classes)" % (where, name, key))
        if "classes" in section:
            classes_ok(section["classes"], "routes.%s.classes" % name)
    guarded = routes.get("guardrailed")
    if guarded is not None:
        if not isinstance(guarded, dict):
            out.append("%s routes.guardrailed must be an object" % where)
        else:
            for key, value in guarded.items():
                kind = GUARDRAILED_KEYS.get(key)
                if kind is None:
                    out.append("%s routes.guardrailed has no key %r (known: %s)" % (where, key, ", ".join(GUARDRAILED_KEYS)))
                elif key == "classes":
                    classes_ok(value, "routes.guardrailed.classes")
                elif key == "max_facts":
                    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                        out.append("%s routes.guardrailed.max_facts must be a positive integer, not %r" % (where, value))
                elif key == "from":
                    if not isinstance(value, str) or not value.strip() or value.startswith(("/", "\\")) or ".." in value:
                        out.append("%s routes.guardrailed.from must be a folder of the project, relative (inbox/transcripts), not %r" % (where, value))
                elif not isinstance(value, kind) or (kind is bool and not isinstance(value, bool)):
                    out.append("%s routes.guardrailed.%s must be %s, not %r" % (where, key, "true or false" if kind is bool else kind.__name__, value))
    return out


def routes_of(directory):
    """The routes' policy the pack at `directory` declares, or {} when it declares none."""
    routes = read(directory).get("routes")
    return routes if isinstance(routes, dict) else {}


def check(directory, strict=False):
    """Problems with a pack. An empty list means it is usable and publishable. `strict` adds the rationale:
    a recorded reason and a named confirmation for every class and relation, what a workspace's gate asks
    (the packs the registry already holds were made before it, so without `strict` the rationale is advisory)."""
    from ..apps import manifest as _apps
    problems = _manifest_problems(directory)
    if strict:
        problems += rationale_problems(directory)
    manifest = read(directory)
    onto_dir = embedded_dir(directory)
    if onto_dir is None:
        problems.append("no embedded ontology: ontology/<name>/ must hold the ontology the manifest names "
                        "(oto pack new, or oto pack refresh)")
        return problems
    for problem in _ontologies.self_check(embedded_name(directory), roots=[embedded_root(directory)]):
        problems.append("ontology: %s" % problem)
    if not (own_config(directory).get("classes") or {}):
        problems.append("ontology: the pack's own vocabulary declares no classes: nothing to deliver yet (the interview fills ontology/%s/)"
                        % embedded_name(directory))
    pattern = manifest.get("pattern")
    if isinstance(pattern, dict) and all(isinstance(pattern.get(k), str) for k in PATTERN_KEYS):
        if pattern["skill"] not in skills(directory):
            problems.append("pattern: the skill %r is not one of this pack's (skills/%s/SKILL.md)" % (pattern["skill"], pattern["skill"]))
        try:
            composed_of = _ontologies.parts(embedded_name(directory), roots=[embedded_root(directory)])
        except (KeyError, _ontologies.OntologyError):
            composed_of = []
        if pattern["of"] not in composed_of[:-1]:
            problems.append("pattern: the pack's ontology %r does not extend %r, so it is no pattern of it"
                            % (embedded_name(directory), pattern["of"]))
    playbook = manifest.get("playbook")
    if isinstance(playbook, dict) and isinstance(playbook.get("skill"), str) and playbook["skill"] not in skills(directory):
        problems.append("playbook: the skill %r is not one of this pack's (skills/%s/SKILL.md)" % (playbook["skill"], playbook["skill"]))
    binding = manifest.get("binding")
    if isinstance(binding, dict) and all(isinstance(binding.get(k), str) for k in BINDING_KEYS):
        if binding["skill"] not in skills(directory):
            problems.append("binding: the skill %r is not one of this pack's (skills/%s/SKILL.md)" % (binding["skill"], binding["skill"]))
        try:
            composed_of = _ontologies.parts(embedded_name(directory), roots=[embedded_root(directory)])
        except (KeyError, _ontologies.OntologyError):
            composed_of = []
        if binding["of"] not in composed_of[:-1]:
            problems.append("binding: the pack's ontology %r does not extend %r, so it binds nothing of it"
                            % (embedded_name(directory), binding["of"]))
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
            if not any(str(d).split("@", 1)[0] == ENGINE_PLUGIN for d in (plugin.get("dependencies") or [])):
                problems.append("plugin.json must depend on the engine plugin %r (as %r: it comes from the engine's own marketplace)" % (ENGINE_PLUGIN, ENGINE_DEPENDENCY))
        except ValueError as exc:
            problems.append("plugin.json is not valid JSON: %s" % exc)
    problems += publishability_problems(directory)
    return problems


def rationale_problems(directory):
    """What the embedded ontology's rationale lacks: a reason, or a confirmation, for a class or a relation."""
    from . import rationale as _rationale
    onto_dir = embedded_dir(directory)
    config = own_config(directory)                       # the pack's own terms: the bases carry their own rationale
    if onto_dir is None or not config:
        return []
    path = os.path.join(onto_dir, "ontology.rationale.json")
    if not os.path.exists(path):
        return ["rationale: ontology/%s/ontology.rationale.json is missing" % embedded_name(directory)]
    with open(path, encoding="utf-8") as f:
        record = json.load(f)
    report = _rationale.report(config, record)
    out = ["rationale: %s" % p for p in report["problems"]]
    out += ["rationale: class %s has no recorded reason" % name for name in report["classes_missing"]]
    out += ["rationale: relation %s has no recorded reason" % name
            for name in sorted(set(config.get("properties") or {}) - set(record.get("properties") or {}))]
    out += ["rationale: class %s has no validated_by: nobody who knows the domain confirmed it" % name
            for name in sorted(config.get("classes") or {}) if name not in report["classes_missing"] and name not in report["classes_validated"]]
    out += ["rationale: relation %s has no validated_by" % name
            for name in sorted(set(record.get("properties") or {}) & set(config.get("properties") or {})) if name not in report["properties_validated"]]
    return out


def publishability_problems(directory):
    """Deny terms in any text file of the pack, and personal data in the embedded sample."""
    from ..validate.publishable import env_terms, names_a_term, term_patterns
    out = []
    patterns = term_patterns(env_terms())
    if patterns:
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))
            for filename in sorted(filenames):
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if names_a_term(text, patterns):
                    # never which term: this message is printed in public CI logs
                    out.append("%s names a client term; a pack must not" % os.path.relpath(path, directory))
    name = embedded_name(directory)
    if name and embedded_dir(directory):
        try:
            for problem in _ontologies.publishability_problems(name, roots=[embedded_root(directory)]):
                if "client term" not in problem:
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
            "skills": sorted(skills(directory)), "origin": origin(name), "pattern": manifest.get("pattern"),
            "playbook": manifest.get("playbook"), "binding": manifest.get("binding")}
