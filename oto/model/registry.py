# -*- coding: utf-8 -*-
"""Registries: where ontologies and packs come from when they are not on this machine.

A registry is a git repository with an index, `registry.json`, the ontologies beside it and the
packs under `packs/`:

    {
      "name": "cynergis",
      "summary": "Cynergis domain ontologies and packs.",
      "ontologies": [
        {"name": "insurance-claims", "release": 3, "domain": "insurance", "summary": "...",
         "path": "insurance-claims", "extends": ["oto-core", "insurance-party"]},
        {"name": "telco-network", "release": 1, "summary": "...",
         "source": "https://github.com/Cynergis/telco-kb-ontology", "ref": "v1"}
      ],
      "packs": [
        {"name": "insurance-claims", "release": 2, "domain": "insurance", "summary": "...",
         "path": "packs/insurance-claims", "ontology": {"name": "insurance-claims", "release": 3}}
      ]
    }

The registry is also a Claude Code marketplace: `.claude-plugin/marketplace.json` lists the
engine plugin first and then every pack, generated on publish.

An entry names a directory in the same repository (`path`) or another repository (`source`, with
an optional `ref` and `path`). Registries are recorded, with a cached copy of their index, in
`~/.oto/registries.json` (`OTO_REGISTRIES` overrides), in the order they were added; a name
resolves through them in that order. `oto ontology add <name>` fetches an ontology into the user
ontology directory beside exports, with its provenance (registry, source, ref, commit) written
into its manifest, so once added it works offline and `update` knows where it came from.

A release can be pinned: `insurance-claims@3`. The registry's current release is what the index
lists; an older one is fetched from the tag `<name>/v<release>`, which `oto ontology publish`
creates. `oto init` never fetches on its own.
"""
import datetime
import json
import os
import re
import shutil
import tempfile

from .. import gitx
from ..project import ProjectError
from . import ontology_manifest as _manifest

INDEX_NAME = "registry.json"
REGISTRIES_ENV = "OTO_REGISTRIES"
TOKEN_ENV = "OTO_REGISTRY_TOKEN"
NAME_OK = re.compile(r"^[a-z][a-z0-9-]*$")
VERSIONED = re.compile(r"^([a-z][a-z0-9-]*)@(\d+)$")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _token():
    return os.environ.get(TOKEN_ENV) or None


def tag_for(name, release, kind="ontology"):
    """An ontology's tag is `<name>/v<release>`; a pack's follows the convention Claude Code uses
    to resolve plugin versions, `<name>--v<release>.0.0`, so both update paths see one number."""
    if kind == "pack":
        return "%s--v%d.0.0" % (name, int(release))
    return "%s/v%d" % (name, int(release))


#: What differs between the two kinds a registry lists.
KINDS = {"ontology": {"list": "ontologies", "prefix": ""},
         "pack": {"list": "packs", "prefix": "packs/"}}


def _kind_tools(kind):
    """(user dir, is-one-of-these test, read manifest, write manifest) for a kind."""
    if kind == "pack":
        from . import packs as _packs
        return _packs.user_dir, _packs._is_pack_dir, _packs.read, _packs.write
    from .ontologies import user_dir, CONFIG_NAME
    return user_dir, (lambda d: os.path.exists(os.path.join(d, CONFIG_NAME))), _manifest.read, _manifest.write


def split_release(text):
    """'name@3' -> ('name', 3); 'name' -> ('name', None). A path is returned untouched."""
    m = VERSIONED.match(text or "")
    return (m.group(1), int(m.group(2))) if m else (text, None)


# ---- the registries file ----

def registries_path():
    from .ontologies import user_dir
    override = os.environ.get(REGISTRIES_ENV)
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.dirname(os.path.normpath(user_dir())), "registries.json")


def load_registries():
    path = registries_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return list(payload.get("registries") or [])


def save_registries(registries):
    path = registries_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"_about": "Ontology registries this machine knows, in resolution order, each with a cached "
                             "copy of its index. `oto registry` maintains it.",
                   "registries": registries}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


# ---- the index ----

def index_problems(index, root=None):
    """What is wrong with an index. With `root`, the directories beside it are checked too."""
    out = []
    if not isinstance(index, dict):
        return ["registry.json must be a JSON object"]
    name = index.get("name")
    if not isinstance(name, str) or not NAME_OK.match(name):
        out.append("registry.json needs a lowercase `name`")
    entries = index.get("ontologies")
    if not isinstance(entries, list):
        return out + ["registry.json needs an `ontologies` list"]
    packs = index.get("packs", [])
    if not isinstance(packs, list):
        return out + ["registry.json `packs` must be a list"]
    for kind, entries in (("ontology", entries), ("pack", packs)):
        _read = _kind_tools(kind)[2]
        seen = set()
        for number, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                out.append("%s entry %d is not an object" % (kind, number)); continue
            ename = entry.get("name")
            if not isinstance(ename, str) or not NAME_OK.match(ename):
                out.append("%s entry %d needs a lowercase `name`" % (kind, number)); continue
            if ename in seen:
                out.append("%s %r is listed twice" % (kind, ename))
            seen.add(ename)
            release = entry.get("release")
            if not isinstance(release, int) or isinstance(release, bool) or release < 1:
                out.append("%s %r needs a positive integer `release`" % (kind, ename))
            if entry.get("domain") is not None and (not isinstance(entry["domain"], str) or not NAME_OK.match(entry["domain"])):
                out.append("%s %r: `domain` must be one lowercase slug" % (kind, ename))
            if not entry.get("path") and not entry.get("source"):
                out.append("%s %r needs a `path` in this repository or a `source` repository" % (kind, ename))
            if kind == "pack" and entry.get("path") and not str(entry["path"]).startswith(KINDS["pack"]["prefix"]):
                out.append("pack %r: its `path` must be under %s" % (ename, KINDS["pack"]["prefix"]))
            if kind == "pack" and not isinstance(entry.get("ontology"), dict):
                out.append("pack %r needs `ontology` with the embedded ontology's name and release" % ename)
            if root is not None and entry.get("path") and not entry.get("source"):
                directory = os.path.join(root, entry["path"])
                if not os.path.isdir(directory):
                    out.append("%s %r: no directory %r beside the index" % (kind, ename, entry["path"]))
                    continue
                manifest = _read(directory)
                if manifest["name"] != ename:
                    out.append("%s %r: the directory's manifest names %r" % (kind, ename, manifest["name"]))
                if isinstance(release, int) and manifest["release"] != release:
                    out.append("%s %r: the index says release %s, the manifest says %s"
                               % (kind, ename, release, manifest["release"]))
                if kind == "pack" and isinstance(entry.get("ontology"), dict) and \
                        (manifest.get("ontology") or {}).get("release") != entry["ontology"].get("release"):
                    out.append("pack %r: the index says it embeds %s@%s, the manifest says @%s"
                               % (ename, entry["ontology"].get("name"), entry["ontology"].get("release"),
                                  (manifest.get("ontology") or {}).get("release")))
    return out


def read_index(directory):
    path = os.path.join(directory, INDEX_NAME)
    if not os.path.exists(path):
        raise ProjectError("%s holds no %s: not an ontology registry" % (directory, INDEX_NAME))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_index(url, ref=None):
    """Clone the registry and return (index, commit). Raises ProjectError with the reason."""
    work = tempfile.mkdtemp(prefix="oto-registry-")
    try:
        gitx.clone(url, work, ref=ref, token=_token())
        index = read_index(work)
        problems = index_problems(index, work)
        if problems:
            raise ProjectError("the registry at %s has problems:\n  - %s" % (url, "\n  - ".join(problems[:10])))
        return index, gitx.head(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- registries ----

def add_registry(url, name=None, ref=None):
    """Register a registry, first fetching its index. Returns the record. Re-adding the same url
    refreshes it; a different url under a taken name is refused."""
    index, commit = fetch_index(url, ref)
    name = name or index.get("name")
    registries = load_registries()
    for existing in registries:
        if existing["name"] == name and existing["url"] != url:
            raise ProjectError("a registry named %r is already registered for %s; remove it first, or add "
                               "this one under another name with --as" % (name, existing["url"]))
    record = {"name": name, "url": url, "ref": ref, "added_at": _now(), "fetched_at": _now(),
              "commit": commit, "index": index}
    registries = [r for r in registries if r["name"] != name] + [record] \
        if not any(r["name"] == name for r in registries) else \
        [record if r["name"] == name else r for r in registries]
    save_registries(registries)
    return record


def remove_registry(name):
    registries = load_registries()
    kept = [r for r in registries if r["name"] != name]
    if len(kept) == len(registries):
        raise ProjectError("no registry named %r (known: %s)" % (name, ", ".join(r["name"] for r in registries) or "none"))
    save_registries(kept)


def refresh(name=None):
    """Re-fetch the index of one registry, or of all. Returns the records refreshed."""
    registries = load_registries()
    out = []
    for record in registries:
        if name and record["name"] != name:
            continue
        index, commit = fetch_index(record["url"], record.get("ref"))
        record.update({"index": index, "commit": commit, "fetched_at": _now()})
        out.append(record)
    if name and not out:
        raise ProjectError("no registry named %r" % name)
    save_registries(registries)
    return out


def find(name, kind="ontology"):
    """(registry record, index entry) for the first registry listing `name`, or (None, None)."""
    for record in load_registries():
        for entry in (record.get("index") or {}).get(KINDS[kind]["list"]) or []:
            if entry.get("name") == name:
                return record, entry
    return None, None


def remote_entries(kind="ontology"):
    """Every index entry with the registry it comes from, in resolution order, first listing wins."""
    seen, out = set(), []
    for record in load_registries():
        for entry in (record.get("index") or {}).get(KINDS[kind]["list"]) or []:
            if entry.get("name") in seen:
                continue
            seen.add(entry["name"])
            out.append((record["name"], entry))
    return out


# ---- fetching ontologies ----

def _install(src, name, provenance, force=False, kind="ontology"):
    """Copy a directory into the kind's user directory and stamp its provenance."""
    user_dir, is_one, read, write = _kind_tools(kind)
    if not is_one(src):
        raise ProjectError("%s is not %s" % (src, "a pack: no manifest.json with an ontology/ beside it" if kind == "pack"
                                             else "an ontology: no ontology.config.json"))
    dest = os.path.join(user_dir(), name)
    if os.path.exists(dest):
        existing = read(dest)
        if not existing.get("source") and not force:
            raise ProjectError("%s already holds %s of your own named %r (no provenance in its "
                               "manifest); pass --force to replace it" % (user_dir(), "a pack" if kind == "pack" else "an ontology", name))
        shutil.rmtree(dest)
    os.makedirs(user_dir(), exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
    manifest = read(dest)
    manifest.update(provenance)
    manifest["fetched_at"] = _now()
    write(dest, manifest)
    return dest, manifest


def fetch(name, release=None, force=False, kind="ontology"):
    """Fetch an ontology or a pack by name from the registries. Returns (dest, manifest)."""
    read = _kind_tools(kind)[2]
    record, entry = find(name, kind)
    if entry is None:
        known = ", ".join(e["name"] for _r, e in remote_entries(kind))
        raise ProjectError("no registry lists %s named %r%s" % ("a pack" if kind == "pack" else "an ontology", name,
                                                               (" (listed: %s)" % known) if known else
                                                               "; add a registry first: oto registry add <url>"))
    url = entry.get("source") or record["url"]
    ref = entry.get("ref") or (record.get("ref") if not entry.get("source") else None)
    current = int(entry.get("release") or 1)
    if release is not None and release != current:
        ref = tag_for(name, release, kind)
        if not gitx.has_ref(url, ref, token=_token()):
            raise ProjectError("the registry %r lists %s at release %d and has no tag %s for release %d"
                               % (record["name"], name, current, ref, release))
    work = tempfile.mkdtemp(prefix="oto-%s-" % kind)
    try:
        gitx.clone(url, work, ref=ref, token=_token())
        src = os.path.join(work, entry["path"]) if entry.get("path") else work
        manifest = read(src)
        if release is not None and manifest["release"] != release:
            raise ProjectError("the tag %s holds %s at release %s, not %d" % (ref, name, manifest["release"], release))
        if manifest["name"] != name:
            raise ProjectError("the registry lists %r but the directory's manifest names %r" % (name, manifest["name"]))
        return _install(src, name, {"registry": record["name"], "source": url, "ref": ref,
                                    "path": entry.get("path"), "commit": gitx.head(work)}, force=force, kind=kind)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def fetch_url(url, path=None, ref=None, force=False, kind="ontology"):
    """Fetch one ontology or pack from a repository, no registry needed. Returns (dest, manifest)."""
    read = _kind_tools(kind)[2]
    work = tempfile.mkdtemp(prefix="oto-%s-" % kind)
    try:
        gitx.clone(url, work, ref=ref, token=_token())
        src = os.path.join(work, path) if path else work
        if not os.path.isdir(src):
            raise ProjectError("%s has no directory %r" % (url, path))
        if os.path.exists(os.path.join(src, INDEX_NAME)) and not path:
            raise ProjectError("%s is a registry, not %s: oto registry add %s"
                               % (url, "a pack" if kind == "pack" else "an ontology", url))
        manifest = read(src)
        return _install(src, manifest["name"], {"registry": None, "source": url, "ref": ref, "path": path,
                                                "commit": gitx.head(work)}, force=force, kind=kind)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def fetched(kind="ontology"):
    """What is on this machine that came from somewhere: [(name, manifest)]."""
    user_dir, is_one, read, _write = _kind_tools(kind)
    out = []
    root = user_dir()
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        directory = os.path.join(root, name)
        if is_one(directory):
            manifest = read(directory)
            if manifest.get("source"):
                out.append((name, manifest))
    return out


def update(name=None, kind="ontology"):
    """Re-fetch fetched ontologies or packs whose registry lists a newer release, or the one named.
    Returns [(name, old release, new release)]; unchanged ones are not listed."""
    refresh()
    out = []
    for fetched_name, manifest in fetched(kind):
        if name and fetched_name != name:
            continue
        if manifest.get("registry"):
            _record, entry = find(fetched_name, kind)
            if entry is None:
                continue
            if int(entry.get("release") or 1) > int(manifest["release"]):
                _dest, new = fetch(fetched_name, force=True, kind=kind)
                out.append((fetched_name, manifest["release"], new["release"]))
        else:
            _dest, new = fetch_url(manifest["source"], path=manifest.get("path"), ref=manifest.get("ref"), force=True, kind=kind)
            if new["release"] != manifest["release"] or new.get("commit") != manifest.get("commit"):
                out.append((fetched_name, manifest["release"], new["release"]))
    if name and not any(n == name for n, _m in fetched(kind)):
        raise ProjectError("%r was not fetched from anywhere; nothing to update" % name)
    return out


# ---- publishing ----

def _clone_for_writing(url, ref=None):
    """A full clone to commit into; an empty repository gets its first branch here."""
    work = tempfile.mkdtemp(prefix="oto-publish-")
    gitx.clone(url, work, ref=ref, token=_token(), depth=None)
    try:
        gitx.run(["rev-parse", "--verify", "HEAD"], cwd=work)
        branch = gitx.run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=work).strip()
    except ProjectError:
        branch = ref or "main"
        gitx.run(["checkout", "-q", "-b", branch], cwd=work)
    return work, branch


def _strip_provenance(manifest):
    for key in _manifest.PROVENANCE:
        manifest.pop(key, None)
    return manifest


DEFAULT_ENGINE = "https://github.com/Cynergis/oto"


def _open_index(work, to, registry_name, engine):
    """(index, created) for a registry checkout, creating the index for an empty repository."""
    created = not os.path.exists(os.path.join(work, INDEX_NAME))
    if not created:
        index = read_index(work)
    else:
        index = {"name": registry_name or re.sub(r"\.git$", "", os.path.basename(to.rstrip("/"))) or "registry",
                 "summary": "", "engine": engine or DEFAULT_ENGINE, "ontologies": [], "packs": []}
        if not NAME_OK.match(index["name"]):
            raise ProjectError("the registry needs a lowercase name: pass --registry-name")
    return index, created


def _write_index(work, index):
    problems = index_problems(index, work)
    if problems:
        raise ProjectError("the registry index would be wrong (nothing was pushed):\n  - %s" % "\n  - ".join(problems[:15]))
    with open(os.path.join(work, INDEX_NAME), "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _scaffold_registry(work, index, engine):
    write_check_workflow(work, engine=engine)
    write_site_workflow(work, engine=engine)
    with open(os.path.join(work, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s: OTO ontologies and packs\n\nA registry. `oto registry add <this url>` on a machine, then "
                "`oto ontology add <name>` or `oto pack add <name>`. Published by `oto ontology publish` and "
                "`oto pack publish`; the index and the marketplace are generated, do not edit them by hand. "
                "Packs install in Claude Code with `/plugin marketplace add <this url>` then "
                "`/plugin install <name>@%s`; the engine plugin `oto` comes with them. The catalog, a page per "
                "pack and per ontology with the sample graph drawn, is generated by `oto registry site` and "
                "published with GitHub Pages on every push.\n"
                % (index["name"], index["name"]))


def _commit_and_push(work, to, branch, tag, message):
    gitx.run(["add", "-A"], cwd=work)
    gitx.run(["-c", "user.name=oto publish", "-c", "user.email=oto-registry@localhost", "commit", "--quiet",
              "-m", message], cwd=work)
    gitx.run(["tag", tag], cwd=work)
    gitx.run(["push", "--quiet", gitx.with_token(to, _token()), "HEAD:%s" % branch, "refs/tags/%s" % tag], cwd=work)
    return gitx.head(work)


def _refresh_cached(to):
    cached = False
    for record in load_registries():
        if record["url"] == to:
            refresh(record["name"])
            cached = True
    return cached


def publish(to, project=None, ontology=None, name=None, summary=None, from_graph=0, note=None, ref=None,
            registry_name=None, engine=None):
    """Publish an ontology into a registry: from a project (exported) or from an ontology on this
    machine. Bumps the release, appends the changelog, regenerates the index, tags and pushes.
    Refuses on any self-check or publishability problem, and pushes nothing then."""
    from . import ontologies as _ontologies

    if project is None and ontology is None:
        raise ProjectError("publish needs a project to export or --ontology <name>")
    work, branch = _clone_for_writing(to, ref)
    try:
        index, created = _open_index(work, to, registry_name, engine)
        entries = {e["name"]: e for e in index.get("ontologies") or []}
        published_name = name or (_ontologies.manifest_dir(_ontologies.dir_for(ontology))["name"]
                                  if ontology and _ontologies.dir_for(ontology) else None)
        prior = []
        if published_name and os.path.isdir(os.path.join(work, published_name)):
            prior = list(_ontologies.manifest_dir(os.path.join(work, published_name)).get("changelog") or [])

        if ontology:
            src = _ontologies.dir_for(ontology)
            if src is None:
                raise ProjectError("unknown ontology %r on this machine" % ontology)
            name = name or _ontologies.manifest_dir(src)["name"]
            dest = os.path.join(work, name)
            if os.path.exists(dest):
                shutil.rmtree(dest)
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
        else:
            if not name:
                raise ProjectError("publish needs --name <ontology-name> when exporting a project")
            dest, _problems = _ontologies.export(project, name, to=work, from_graph=from_graph, summary=summary, force=True)

        manifest = _strip_provenance(_ontologies.manifest_dir(dest))
        manifest["name"] = name
        previous = int(entries[name]["release"]) if name in entries else 0
        manifest["release"] = previous + 1
        if summary:
            manifest["summary"] = summary
        manifest["carries"] = _manifest.detect_carries(dest)
        # The registry's own history of this ontology continues; what export or a local copy says
        # about earlier releases is not the registry's record.
        manifest["changelog"] = [{"release": manifest["release"], "at": datetime.date.today().isoformat(),
                                  "note": note or ("Published from the project %s." % project.identity()["name"]
                                                   if project else "Published from this machine.")}] \
            + [e for e in prior if int(e.get("release", 0)) <= previous]
        _manifest.write(dest, manifest)
        for stale in (PLUGIN_DIR, "skills", "views"):                  # an ontology carries none of these now
            shutil.rmtree(os.path.join(dest, stale), ignore_errors=True)

        problems = _ontologies.self_check(name, roots=[work])
        if problems:
            raise ProjectError("%r is not publishable (nothing was pushed):\n  - %s" % (name, "\n  - ".join(problems[:15])))

        entries[name] = {"name": name, "release": manifest["release"], "summary": manifest.get("summary", ""),
                         "path": name, "extends": list(manifest.get("extends") or [])}
        if manifest.get("domain"):
            entries[name]["domain"] = manifest["domain"]
        index["ontologies"] = [entries[k] for k in sorted(entries)]
        _write_index(work, index)
        _path, plugins = write_marketplace(work, index)
        if created:
            _scaffold_registry(work, index, engine)
        tag = tag_for(name, manifest["release"])
        commit = _commit_and_push(work, to, branch, tag, "ontology %s @%d: %s" % (name, manifest["release"], manifest["changelog"][0]["note"]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"name": name, "release": manifest["release"], "tag": tag, "registry": index["name"], "commit": commit,
            "cached": _refresh_cached(to), "plugins": [p["name"] for p in plugins], "created": created}


def publish_pack(to, pack, note=None, summary=None, ref=None, registry_name=None, engine=None):
    """Publish a pack from this machine into a registry, under packs/<name>. Bumps the release,
    regenerates the plugin files so the plugin version follows, appends the changelog, updates the
    index and the marketplace, tags and pushes. Refuses on any check problem, and pushes nothing."""
    from . import packs as _packs

    src = _packs.dir_for(pack)
    if src is None:
        raise ProjectError("unknown pack %r on this machine (oto pack list)" % pack)
    work, branch = _clone_for_writing(to, ref)
    try:
        index, created = _open_index(work, to, registry_name, engine)
        entries = {e["name"]: e for e in index.get("packs") or []}
        name = _packs.read(src)["name"]
        dest = os.path.join(work, KINDS["pack"]["prefix"] + name)
        prior = list(_packs.read(dest).get("changelog") or []) if os.path.isdir(dest) else []
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
        manifest = _packs.read(dest)
        for key in _packs.PROVENANCE:
            manifest.pop(key, None)
        previous = int(entries[name]["release"]) if name in entries else 0
        manifest["release"] = previous + 1
        if summary:
            manifest["summary"] = summary
        manifest["changelog"] = [{"release": manifest["release"], "at": datetime.date.today().isoformat(),
                                  "note": note or "Published from this machine."}] \
            + [e for e in prior if int(e.get("release", 0)) <= previous]
        _packs.write(dest, manifest)
        _packs.plugin_files(dest, registry_name=index["name"])
        problems = _packs.check(dest)
        if problems:
            raise ProjectError("pack %r is not publishable (nothing was pushed):\n  - %s" % (name, "\n  - ".join(problems[:15])))
        onto = manifest.get("ontology") or {}
        entries[name] = {"name": name, "release": manifest["release"], "summary": manifest.get("summary", ""),
                         "path": KINDS["pack"]["prefix"] + name, "ontology": {"name": onto.get("name"), "release": onto.get("release")}}
        if manifest.get("domain"):
            entries[name]["domain"] = manifest["domain"]
        index["packs"] = [entries[k] for k in sorted(entries)]
        _write_index(work, index)
        _path, plugins = write_marketplace(work, index)
        if created:
            _scaffold_registry(work, index, engine)
        tag = tag_for(name, manifest["release"], "pack")
        commit = _commit_and_push(work, to, branch, tag, "pack %s @%d: %s" % (name, manifest["release"], manifest["changelog"][0]["note"]))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"name": name, "release": manifest["release"], "tag": tag, "registry": index["name"], "commit": commit,
            "cached": _refresh_cached(to), "plugins": [p["name"] for p in plugins], "created": created}


# ---- what an upstream ontology changed since a project started from it ----

def _upstream(record):
    """(kind, url, ref, path) for where a project's ontology lives upstream, or a ProjectError."""
    from . import ontologies as _ontologies
    name = record.get("name")
    if record.get("registry"):
        reg, entry = find(name)
        if entry is None:
            raise ProjectError("the registry %r no longer lists %r (or is not registered here)" % (record["registry"], name))
        url = entry.get("source") or reg["url"]
        return "registry", url, entry.get("ref") or (reg.get("ref") if not entry.get("source") else None), entry.get("path"), int(entry.get("release") or 1), reg["name"]
    if record.get("origin") == _ontologies.FETCHED and record.get("source"):
        return "url", record["source"], record.get("ref"), record.get("path"), None, record["source"]
    if record.get("origin") == _ontologies.BUILTIN:
        return "built-in", None, None, None, _ontologies.manifest_for(name)["release"], "engine"
    raise ProjectError("this project started from %r (%s); there is no upstream to diff against"
                       % (name, record.get("origin") or record.get("source") or "a merge"))


def project_record(project):
    """(the ontology record a project started from, whether it was found under the old key).

    Projects made before 2026-09-24 recorded it as `template` with a `version`; both are read for
    one release, and `oto status` says so. Nothing is rewritten: the record is the project's."""
    config = project.config()
    record = config.get("ontology")
    if record and record.get("name"):
        return dict(record), False
    record = config.get("template")
    if record and record.get("name"):
        out = dict(record)
        if "release" not in out and "version" in out:
            out["release"] = out.pop("version")
        return out, True
    return None, False


def newer_release(record):
    """The upstream release when it is newer than the project's, from local knowledge only."""
    kind, _url, _ref, _path, current, _where = _upstream(record)
    if current is None:
        return None
    return current if int(current) > int(record.get("release") or 0) else None


def diff_project(project):
    """What the upstream ontology changed since the project started from it. Reads, never writes."""
    from . import ontologies as _ontologies
    from . import vocabulary as vocab

    record, _legacy = project_record(project)
    if not record:
        raise ProjectError("this project records no ontology (project.config.json has no `ontology`); "
                           "nothing to diff against")
    name, recorded = record["name"], int(record.get("release") or 0)
    kind, url, ref, path, _current, where = _upstream(record)

    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []

    work = old_work = None
    try:
        if kind == "built-in":
            new = _ontologies.composed(name)
            roots_new = None
        else:
            work = tempfile.mkdtemp(prefix="oto-diff-")
            gitx.clone(url, work, ref=ref, token=_token())
            roots_new = [os.path.join(work, path) and work] if path else [work]
            if path and path != name:
                raise ProjectError("the registry keeps %r under %r; publish keeps them equal" % (name, path))
            new = _ontologies.composed(name, roots=roots_new)
        current = int(new["manifest"]["release"])

        basis, tag, old_vocab, old_rules = "lock", None, None, None
        if kind != "built-in" and recorded and recorded != current:
            tag = tag_for(name, recorded)
            if gitx.has_ref(url, tag, token=_token()):
                old_work = tempfile.mkdtemp(prefix="oto-diff-old-")
                gitx.clone(url, old_work, ref=tag, token=_token())
                old = _ontologies.composed(name, roots=[old_work])
                old_vocab = vocab.Vocabulary.from_config(old["config"])
                old_rules = old["rules"]
                basis = "tag"
        if old_vocab is None:
            old_vocab = vocab.read_lock(project)
            if old_vocab is None:
                with open(project.ontology_config_path, encoding="utf-8") as f:
                    old_vocab = vocab.Vocabulary.from_config(json.load(f))
                basis = "config"
            lock = vocab.lock_path(project)
            if os.path.exists(lock):
                with open(lock, encoding="utf-8") as f:
                    old_rules = json.load(f).get("rules") or []
            else:
                from ..reason import rules as _rules
                old_rules = _rules.load(project)

        changes = vocab.impact(vocab.diff(old_vocab, vocab.Vocabulary.from_config(new["config"])), nodes, edges)
        old_by = {r.get("id"): r for r in old_rules or []}
        new_by = {r.get("id"): r for r in new["rules"] or []}
        rules = {"added": sorted(set(new_by) - set(old_by)), "removed": sorted(set(old_by) - set(new_by)),
                 "changed": sorted(k for k in set(old_by) & set(new_by)
                                   if json.dumps(old_by[k], sort_keys=True) != json.dumps(new_by[k], sort_keys=True))}
        changelog = [e for e in new["manifest"].get("changelog") or [] if int(e.get("release", 0)) > recorded]
        changelog.sort(key=lambda e: -int(e.get("release", 0)))
        return {"name": name, "recorded": recorded, "current": current, "where": where, "basis": basis, "tag": tag,
                "changes": changes, "rules": rules, "changelog": changelog}
    finally:
        for directory in (work, old_work):
            if directory:
                shutil.rmtree(directory, ignore_errors=True)


# ---- an ontology as a Claude Code plugin, and a registry as a marketplace ----

PLUGIN_DIR = ".claude-plugin"
MARKETPLACE_NAME = "marketplace.json"
CHECK_WORKFLOW = """name: oto registry check

# The index must match the directories beside it, every ontology must pass its self-check and
# every pack its check.
# Runs on every push to the default branch and every pull request; `oto ontology publish` keeps
# this true, a hand edit may not. Tag pushes are not checked twice. The engine is private, so the
# repository needs the secret OTO_ENGINE_TOKEN (a token that can read it); OTO_DENY_TERMS is
# optional and makes the self-check strict about names.

on:
  push:
    branches: [ main ]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
      - name: Install the engine from its repository
        run: python -m pip install "oto-kg @ git+${ENGINE}"
        env:
          ENGINE: ${{ vars.OTO_ENGINE || '%(engine)s' }}
      - name: Index matches directories
        run: oto registry check .
      - name: Every ontology passes its self-check, every pack its check
        env:
          OTO_DENY_TERMS: ${{ secrets.OTO_DENY_TERMS }}
        run: |
          python - <<'PY'
          import json, sys
          from oto.model import ontologies, packs
          index = json.load(open("registry.json"))
          bad = 0
          for entry in index["ontologies"]:
              if not entry.get("path"):
                  continue
              problems = ontologies.self_check(entry["name"], roots=["."])
              print("%%-24s %%s" %% ("ontology " + entry["name"], "ok" if not problems else "%%d problem(s)" %% len(problems)))
              for p in problems:
                  print("    - " + p)
              bad += bool(problems)
          for entry in index.get("packs") or []:
              if not entry.get("path"):
                  continue
              problems = packs.check(entry["path"])
              print("%%-24s %%s" %% ("pack " + entry["name"], "ok" if not problems else "%%d problem(s)" %% len(problems)))
              for p in problems:
                  print("    - " + p)
              bad += bool(problems)
          sys.exit(1 if bad else 0)
          PY
"""


def _engine_source(engine):
    """A marketplace source for the engine repository: GitHub shorthand when it is one."""
    m = re.match(r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", engine or "")
    if m:
        return {"source": "github", "repo": m.group(1)}
    return {"source": "url", "url": engine}


def write_marketplace(work, index):
    """The registry as a Claude Code marketplace: the engine plugin first, then every pack, so a
    pack's dependency on `oto` resolves inside the same marketplace."""
    engine = index.get("engine") or DEFAULT_ENGINE
    plugins = [{"name": "oto", "source": _engine_source(engine),
                "description": "The OTO engine: the kg_* query tools as an MCP server, the generic skills, and "
                               "the session hook. Every pack depends on it."}]
    for entry in index.get("packs") or []:
        if not entry.get("path"):
            continue
        if os.path.exists(os.path.join(work, entry["path"], PLUGIN_DIR, "plugin.json")):
            plugin = {"name": entry["name"], "source": "./%s" % entry["path"],
                      "description": (entry.get("summary") or "").strip(), "version": "%d.0.0" % int(entry.get("release") or 1)}
            if entry.get("domain"):
                plugin["category"] = entry["domain"]
            plugins.append(plugin)
    os.makedirs(os.path.join(work, PLUGIN_DIR), exist_ok=True)
    path = os.path.join(work, PLUGIN_DIR, MARKETPLACE_NAME)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"name": index["name"], "owner": {"name": index.get("owner") or index["name"]},
                   "metadata": {"description": index.get("summary") or "OTO packs: an ontology, its skills and its views, installable as plugins."},
                   "plugins": plugins}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path, plugins[1:]


SITE_WORKFLOW = """name: oto registry site

# The catalog: one page for the registry, one per pack and per ontology, the sample graph of
# every pack drawn by the explorer. Generated by `oto registry site` on every push to the default
# branch and published with GitHub Pages: enable Pages with "GitHub Actions" as the source once.

on:
  push:
    branches: [ main ]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  site:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Reach the engine repository when it is private
        run: if [ -n "$OTO_ENGINE_TOKEN" ]; then git config --global url."https://x-access-token:${OTO_ENGINE_TOKEN}@github.com/".insteadOf "https://github.com/"; fi
        env:
          OTO_ENGINE_TOKEN: ${{ secrets.OTO_ENGINE_TOKEN }}
      - name: Install the engine from its repository
        run: python -m pip install "oto-kg @ git+${ENGINE}"
        env:
          ENGINE: ${{ vars.OTO_ENGINE || '%(engine)s' }}
      - name: Generate the catalog
        run: oto registry site . --out site --url "https://github.com/${{ github.repository }}"
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site
      - id: deploy
        uses: actions/deploy-pages@v4
"""


def write_site_workflow(work, engine=None):
    """The registry's catalog, published with Pages; written once when a registry is created."""
    path = os.path.join(work, ".github", "workflows", "oto-registry-site.yml")
    if os.path.exists(path):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(SITE_WORKFLOW % {"engine": engine or DEFAULT_ENGINE})
    ignore = os.path.join(work, ".gitignore")
    lines = open(ignore, encoding="utf-8").read().splitlines() if os.path.exists(ignore) else []
    if "site/" not in lines:
        with open(ignore, "a", encoding="utf-8", newline="\n") as f:
            f.write("%s# the catalog, generated by `oto registry site` and published by the site workflow\nsite/\n" % ("\n" if lines and lines[-1] else ""))
    return path


def write_check_workflow(work, engine=None):
    """The registry's own gate, written once when a registry is created."""
    path = os.path.join(work, ".github", "workflows", "oto-registry-check.yml")
    if os.path.exists(path):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(CHECK_WORKFLOW % {"engine": engine or DEFAULT_ENGINE})
    return path
