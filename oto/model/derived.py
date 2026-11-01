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
