# -*- coding: utf-8 -*-
"""The candidate lifecycle: start, inspect, apply, abort.

Nothing edits the live graph. Edits go into a candidate file, and only an explicit apply promotes it.
That is the whole safety model, and it is deliberately boring: the failure this prevents is an agent
or a script quietly changing what the organization believes.

The apply is transactional in the same way the build is: the live graph is renamed aside, the
candidate takes its place, and the previous version is kept until the swap succeeds.
"""
import json
import os
import shutil

CANDIDATE_NAME = "graph.candidate.json"
PREVIOUS_NAME = "graph.previous.json"


def candidate_path(project):
    return os.path.join(project.data, CANDIDATE_NAME)


def previous_path(project):
    return os.path.join(project.data, PREVIOUS_NAME)


def exists(project):
    return os.path.exists(candidate_path(project))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, payload):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def live(project):
    return _read(project.graph_path)


def candidate(project):
    if not exists(project):
        raise FileNotFoundError(candidate_path(project))
    return _read(candidate_path(project))


def find(graph, term):
    """Nodes in a graph that a term refers to: by id, then label or alias, exact before contains.
    Case-insensitive. This is what lets a proposal reuse an id that only the candidate holds yet."""
    needle = (term or "").strip().lower()
    if not needle:
        return []
    exact, partial = [], []
    for node in graph.get("nodes") or []:
        names = [str(node.get("label") or "")] + [str(a) for a in (node.get("aliases") or [])]
        names = [n.lower() for n in names]
        if node.get("id", "").lower() == needle or needle in names:
            exact.append(node)
        elif any(needle in n for n in names) or needle in node.get("id", "").lower():
            partial.append(node)
    return exact + partial


def start(project, force=False):
    """Copy the live graph to a candidate, ready to edit. Returns the candidate path."""
    path = candidate_path(project)
    if os.path.exists(path) and not force:
        raise FileExistsError(path)
    graph = live(project)
    graph["_about"] = ("A CANDIDATE edit of the curated graph. Edit this, never the live graph. "
                       "`oto curate check` reports what it would change; `oto curate apply` promotes "
                       "it; `oto curate abort` discards it.")
    _write(path, graph)
    return path


def abort(project):
    """Discard the candidate. Returns True if there was one."""
    path = candidate_path(project)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True


def apply(project):
    """Promote the candidate to the live graph, keeping the previous version.

    The previous graph is kept rather than deleted. An apply that turns out to be wrong is then one
    command from being undone, and the alternative is asking someone to reconstruct it.
    """
    path = candidate_path(project)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    target = project.graph_path
    previous = previous_path(project)

    if os.path.exists(previous):
        os.remove(previous)
    shutil.copy2(target, previous)
    try:
        os.replace(path, target)
    except OSError:
        shutil.copy2(previous, target)      # put it back rather than leave a half-applied state
        raise
    return {"applied": target, "previous": previous}


def undo(project):
    """Restore the previous graph. Returns the path restored, or None when there is nothing to undo."""
    previous = previous_path(project)
    if not os.path.exists(previous):
        return None
    shutil.copy2(previous, project.graph_path)
    os.remove(previous)
    return project.graph_path
