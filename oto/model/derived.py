# -*- coding: utf-8 -*-
"""A knowledge project's vocabulary, when it is the packs' and not the project's own.

A project started from a pack, or from an ontology an installed pack carries, does not define its
vocabulary: it uses one (docs/plans/ontology-workspace.md). Its `ontology.config.json` is what the
ontologies it started from compose, written by the engine, and the project says so in
`project.config.json`:

    "kind": "knowledge",          what the project is: knowledge (a graph on packs), or concierge
    "vocabulary": "derived"       derived: the file is the packs'; own: the project's, edited in place

`derived` is written by `oto init --pack` and `oto init --ontology <name>` when every name resolves
on the machine (an installed pack's copy, or a fetched one). `own` is written when the project
starts with no ontology or from a directory, and is what every project made before this plan reads
as: nothing changes for them. On a derived project `oto ontology check` and `accept` refuse a hand
edit, naming what differs and where a change belongs (the pack's workspace, or a pack that extends
it), `oto ontology import` is refused, and `oto ontology update` re-derives the file after fetching.
A knowledge project that wants its vocabulary back sets `"vocabulary": "own"`.
"""
import datetime
import json
import os

DERIVED = "derived"
OWN = "own"
KNOWLEDGE = "knowledge"
CONCIERGE = "concierge"
#: The keys of ontology.config.json that are the vocabulary; the rest (`_about`, `_derived`) is a note.
COMPARED = ("name", "ontology_version", "strict_domains", "strict_attributes", "languages", "classes", "properties",
            "attributes", "temporal", "namespaces", "schemes")


def kind(project):
    """What the project is: knowledge unless it says otherwise (a concierge root says so)."""
    return project.config().get("kind") or KNOWLEDGE


def mode(project):
    """`derived` or `own`; a project that says nothing owns its vocabulary."""
    return project.config().get("vocabulary") or OWN


def record(project):
    """The ontology record the project started from, or None."""
    from . import registry as _registry
    found, _legacy = _registry.project_record(project)
    return found


def names(project):
    """The ontologies the project started from, in composition order: one, or a merge's parts."""
    found = record(project) or {}
    if found.get("source") == "merge" and found.get("parts"):
        return [p["name"] for p in found["parts"]]
    return [found["name"]] if found.get("name") else []


def releases(project):
    """[(name, release)] as the record remembers them."""
    found = record(project) or {}
    if found.get("source") == "merge" and found.get("parts"):
        return [(p["name"], p.get("release")) for p in found["parts"]]
    return [(found["name"], found.get("release"))] if found.get("name") else []


def _roots(project):
    """Where to read the ontologies from first: the pack the project started from, when it is installed."""
    from . import packs as _packs
    found = record(project) or {}
    pack = (found.get("pack") or {}).get("name")
    if not pack:
        return None
    directory = _packs.dir_for(pack)
    return [_packs.embedded_root(directory)] if directory else None


def about(wanted):
    """The header a derived file carries."""
    return ("Derived from %s: this file is what the ontologies the project started from compose, written by the "
            "engine, and the project does not edit it (project.config.json: vocabulary: derived). Do not edit it "
            "here: a term these packs lack is a pack that extends them (oto pack new <name> --extends %s), a "
            "change to a term belongs in its pack's workspace. `oto ontology check` refuses a hand edit; "
            "`oto ontology update` rewrites this file from the packs' current releases."
            % (", ".join(wanted), ",".join(wanted)))


def compose(project):
    """The vocabulary the project's ontologies compose, named after the project: what ontology.config.json
    must hold. Raises ValueError when a name no longer resolves on this machine."""
    from . import ontologies as _ontologies
    wanted = names(project)
    if not wanted:
        raise ValueError("this project records no ontology it started from; its vocabulary is its own")
    roots = _roots(project)
    missing = [n for n in wanted if _ontologies.dir_for(n, roots) is None]
    if missing:
        raise ValueError("the vocabulary is derived from %s, which this machine does not have: oto pack add %s"
                         % (", ".join(missing), " ".join(missing)))
    if len(wanted) == 1:
        config = dict(_ontologies.composed(wanted[0], roots=roots)["config"])
    else:
        config = dict(_ontologies.merge(wanted, roots=roots)[0])
        for key in list(config):
            if key.startswith("_") and key != "_about":
                config.pop(key)
    config["name"] = project.config().get("name") or config.get("name")
    config["_about"] = about(wanted)
    config["_derived"] = {"from": [{"name": n, "release": r} for n, r in releases(project)],
                          "at": datetime.date.today().isoformat()}
    return config


def _differences(label, mine, theirs):
    mine, theirs = mine or {}, theirs or {}
    out = ["%s %s is not in the packs' vocabulary (added by hand)" % (label, k) for k in mine if k not in theirs]
    out += ["%s %s is in the packs' vocabulary but not in the file" % (label, k) for k in theirs if k not in mine]
    out += ["%s %s differs from the packs' declaration" % (label, k) for k in mine if k in theirs and mine[k] != theirs[k]]
    return out


def drift(project):
    """How ontology.config.json differs from what the packs compose: [] when it is theirs. A note-only
    difference (`_about`, `_derived`) is not drift."""
    with open(project.ontology_config_path, encoding="utf-8") as f:
        mine = json.load(f)
    theirs = compose(project)
    out = _differences("class", mine.get("classes"), theirs.get("classes"))
    out += _differences("relation", mine.get("properties"), theirs.get("properties"))
    for owner in sorted(set(mine.get("attributes") or {}) | set(theirs.get("attributes") or {})):
        out += _differences("attribute of %s," % owner, (mine.get("attributes") or {}).get(owner), (theirs.get("attributes") or {}).get(owner))
    for key in COMPARED:
        if key in ("classes", "properties", "attributes"):
            continue
        if mine.get(key) != theirs.get(key) and not (mine.get(key) in (None, {}, []) and theirs.get(key) in (None, {}, [])):
            out.append("%s differs from the packs' (%r here)" % (key, mine.get(key) if not isinstance(mine.get(key), dict) else "..."))
    return out


def take_release(project):
    """Record the release of the pack this project now derives from, or the next run offers the same one again. Returns (old, new) when it moved, else None."""
    from . import packs as _packs
    config_path = project.config_path
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    found = config.get("ontology") or {}
    pack = found.get("pack") or {}
    directory = _packs.dir_for(pack.get("name")) if pack.get("name") else None
    if directory is None:
        return None
    manifest = _packs.read(directory)
    if int(pack.get("release") or 0) == int(manifest["release"]):
        return None
    old = pack.get("release")
    pack["release"] = manifest["release"]
    embedded = (manifest.get("ontology") or {}).get("release")
    if embedded is not None:
        found["release"] = embedded
    with open(config_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return old, manifest["release"]


def write(project):
    """Write ontology.config.json from the packs. Returns the path."""
    config = compose(project)
    path = project.ontology_config_path
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def refusal(project, found):
    """What `oto ontology check` says when a derived vocabulary was edited by hand."""
    wanted = names(project)
    lines = ["the vocabulary is derived from %s and was edited by hand (project.config.json: vocabulary: derived):"
             % ", ".join(wanted)]
    lines += ["  %s" % line for line in found[:12]]
    if len(found) > 12:
        lines.append("  ... and %d more" % (len(found) - 12))
    lines.append("a term the packs lack is a pack that extends them: oto pack new <name> --extends %s, then start from both;" % ",".join(wanted))
    lines.append("a change to a term belongs in its pack's workspace; `oto ontology update --project %s` puts the packs' vocabulary back;"
                 % os.path.basename(project.data))
    lines.append("a project that wants to own its vocabulary says so: \"vocabulary\": \"own\" in project.config.json")
    return "\n".join(lines)


# ---- the routes' policy (docs/plans/graph-journeys.md, phase 6) ----

ROUTE_KEYS = ("allowed", "session", "reviewed", "guardrailed")


def pack_dirs(project):
    """The directories of the installed packs the project's vocabulary is derived from, in composition
    order: the pack the record names, then the pack each ontology name resolves inside."""
    from . import ontologies as _ontologies, packs as _packs
    out = []
    found = record(project) or {}
    pack = (found.get("pack") or {}).get("name")
    if pack and _packs.dir_for(pack):
        out.append(_packs.dir_for(pack))
    roots = _roots(project)
    pack_roots = {os.path.normpath(r) for r in _ontologies._pack_roots()}
    for name in names(project):
        path = _ontologies.dir_for(name, roots)
        if path and os.path.normpath(os.path.dirname(path)) in pack_roots:
            directory = os.path.dirname(os.path.dirname(path))
            if directory not in out:
                out.append(directory)
    return out


def routes_policy(directories):
    """(routes, routes_from, notes) composed from the packs at `directories`, in order: `allowed` is the
    intersection of what the packs allow (the stricter wins); `session`, `reviewed` and `guardrailed`
    come from the first pack that declares each, and a later pack declaring one too is noted. Each
    entry of routes_from says which keys a pack gave, at which release, and the values as derived, so
    a later update can tell a key the project rewrote from one still the pack's."""
    from . import packs as _packs
    routes, routes_from, notes = {}, [], []
    allowed = None
    for directory in directories:
        manifest = _packs.read(directory)
        policy = manifest.get("routes") if isinstance(manifest.get("routes"), dict) else {}
        if not policy:
            continue
        gave = []
        if isinstance(policy.get("allowed"), list):
            mine = [r for r in policy["allowed"] if isinstance(r, str)]
            allowed = mine if allowed is None else [r for r in allowed if r in mine]
            gave.append("allowed")
        for key in ("session", "reviewed", "guardrailed"):
            if isinstance(policy.get(key), dict):
                if key in routes:
                    notes.append("the pack %s also declares routes.%s; %s's is kept" % (manifest["name"], key, routes_from[0]["pack"]))
                    continue
                routes[key] = json.loads(json.dumps(policy[key]))
                gave.append(key)
        if gave:
            routes_from.append({"pack": manifest["name"], "release": manifest["release"], "keys": sorted(gave), "derived": {}})
    if allowed is not None:
        routes["allowed"] = allowed
    for entry in routes_from:
        entry["derived"] = {k: json.loads(json.dumps(routes[k])) for k in entry["keys"] if k in routes}
        entry["keys"] = sorted(entry["derived"])
    return routes, routes_from, notes


def write_routes(project):
    """Re-derive the project's routes from its packs' current releases, keeping every key the project
    rewrote: a key is the pack's while its value is what the pack gave (`routes_from[].derived`), and
    the project's once it differs. Returns {moved, kept, dropped, from} or None when nothing is
    derived (no pack declares routes and the project recorded none)."""
    config = project.config()
    current = dict(config.get("routes") or {})
    was_from = config.get("routes_from") or []
    derived_now, from_now, _notes = routes_policy(pack_dirs(project))
    if not was_from and not from_now:
        return None
    theirs_before = {}
    for entry in was_from:
        for key in entry.get("keys") or []:
            theirs_before[key] = (entry.get("derived") or {}).get(key)
    kept = sorted(k for k in current if k in theirs_before and current[k] != theirs_before[k])      # rewritten by the project
    projects_own = {k: current[k] for k in current if k not in theirs_before or k in kept}
    new_routes = dict(projects_own)
    moved, dropped = [], []
    for key, value in derived_now.items():
        if key in projects_own:
            continue
        new_routes[key] = value
        if current.get(key) != value:
            moved.append(key)
    for key in theirs_before:
        if key not in derived_now and key not in projects_own:
            dropped.append(key)
    for entry in from_now:
        entry["keys"] = [k for k in entry["keys"] if k not in projects_own]
        entry["derived"] = {k: v for k, v in entry["derived"].items() if k not in projects_own}
    from_now = [e for e in from_now if e["keys"]]
    if new_routes:
        config["routes"] = new_routes
    else:
        config.pop("routes", None)
    if from_now:
        config["routes_from"] = from_now
    else:
        config.pop("routes_from", None)
    with open(project.config_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"moved": moved, "kept": kept, "dropped": dropped, "from": from_now}


def routes_said(config):
    """One line for `oto status`: which keys of `routes` are the packs' and which the project's. A key is
    the pack's while its value is what the pack gave (`routes_from[].derived`), as `write_routes` decides
    it, so a key the project rewrote is said to be set here at once, not only after the next update."""
    routes = config.get("routes") or {}
    entries = config.get("routes_from") or []
    if not routes and not entries:
        return None
    parts = []
    theirs = set()
    for entry in entries:
        given = entry.get("derived") or {}
        keys = [k for k in entry.get("keys") or [] if k in routes and (k not in given or routes[k] == given[k])]
        theirs |= set(keys)
        if keys:
            parts.append("from the pack %s @%s: %s" % (entry.get("pack"), entry.get("release"), ", ".join(keys)))
    mine = sorted(k for k in routes if k not in theirs)
    if mine:
        parts.append("%s set here" % ", ".join(mine))
    return "; ".join(parts)
