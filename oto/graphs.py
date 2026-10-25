# -*- coding: utf-8 -*-
"""Graph descriptors: the node every graph holds about itself and about the graphs it depends on
(roadmap A1, A2).

Graphs reference other graphs. The core ontology's `Graph` class is the baseline every graph has:
one node for itself, written by `oto init` from the project's config and vocabulary (subject, main
classes, how to reach it, slug), and one for each dependency, which is the other graph's own
descriptor brought here with a `depends_on_graph` edge. An agent then lists a graph's dependencies,
reads what each holds and chooses which to ask (CORE4) without custom modelling; the concierge root
(A5) is a graph of nothing but descriptors.

    oto graph describe [--reach URL]        this graph's descriptor as JSON, for another project to depend on
    oto graph describe --record             write this graph's own descriptor into a project made before them
    oto graph depend --on <descriptor.json> declare a dependency: the other graph's node, and the edge
    oto graph dependencies                  what this graph depends on, from its own facts

The project's own descriptor is inferred from its config (`source_type: inference`, cited to
project.config.json); a dependency is a person's declaration and goes through the gates like any
other write (work._commit), recorded in the audit log.
"""
import datetime
import json
import os

from .project import ProjectError

CLASS = "Graph"
DEPENDS_ON = "depends_on_graph"
DESCRIPTOR_KEYS = ("id", "label", "subject", "classes", "reach", "slug")
MAX_CLASSES = 64


class GraphError(ProjectError):
    """A refusal, in words the person can act on."""


def node_id(slug):
    return "graph.%s" % slug


def declared(vocabulary):
    """Does the vocabulary declare Graph? A bare project does not, and gets no descriptor."""
    return CLASS in ((vocabulary or {}).get("classes") or {})


def main_classes(vocabulary, graph=None):
    """The classes worth naming: those with instances first, most first, then the rest declared,
    capped. Document, Tool and Graph last: every graph has them."""
    names = list(((vocabulary or {}).get("classes") or {}).keys())
    counts = {}
    for n in (graph or {}).get("nodes") or []:
        if n.get("status", "current") == "current":
            counts[n.get("type")] = counts.get(n.get("type"), 0) + 1
    core = ("Document", "Tool", CLASS)
    ordered = sorted(names, key=lambda c: (c in core, -counts.get(c, 0), c))
    return ordered[:MAX_CLASSES]


def describe(project, vocabulary=None, graph=None, reach=None):
    """This graph's descriptor, from the project's identity and vocabulary: what another project
    stores when it depends on this one."""
    from . import __version__
    if vocabulary is None:
        with open(project.ontology_config_path, encoding="utf-8") as f:
            vocabulary = json.load(f)
    if graph is None and os.path.exists(project.graph_path):
        with open(project.graph_path, encoding="utf-8") as f:
            graph = json.load(f)
    identity = project.identity()
    cfg = project.config()
    subject = (vocabulary.get("_summary") or vocabulary.get("_about") or "").strip()
    subject = "%s: %s" % (identity["name"], subject) if subject else identity["name"]
    return {"id": node_id(identity["slug"]), "label": identity["name"], "subject": subject.split("\n")[0][:300],
            "classes": main_classes(vocabulary, graph), "reach": reach or identity["server_name"], "slug": identity["slug"],
            "namespace": cfg.get("namespace"), "engine": __version__, "described_at": datetime.date.today().isoformat()}


def descriptor_problems(descriptor):
    """What is wrong with a descriptor another project gave us, in words."""
    if not isinstance(descriptor, dict):
        return ["a descriptor is a JSON object, what `oto graph describe` prints"]
    out = []
    for key in DESCRIPTOR_KEYS:
        if not descriptor.get(key):
            out.append("`%s` is required" % key)
    if not isinstance(descriptor.get("classes", []), list):
        out.append("`classes` is a list of class names")
    if isinstance(descriptor.get("id"), str) and not descriptor["id"].startswith("graph."):
        out.append("`id` is graph.<slug>")
    return out


def own_node(descriptor, at=None):
    """The project's own descriptor as a node: inferred from its config, so cited to it."""
    at = at or datetime.date.today().isoformat()
    return {"id": descriptor["id"], "type": CLASS, "label": descriptor["label"], "summary": "This graph, described from outside: " + descriptor["subject"],
            "attributes": {"subject": descriptor["subject"], "classes": list(descriptor["classes"]), "reach": descriptor["reach"], "slug": descriptor["slug"]},
            "as_of": at, "valid_from": at, "status": "current", "source_type": "inference",
            "source_doc": "project.config.json", "sources": ["project.config.json"], "aliases": [], "tags": []}


def existing(graph, slug=None, node=None):
    """The descriptor node for `slug` (or with id `node`) the graph holds, or None."""
    want = node or node_id(slug)
    for n in graph.get("nodes") or []:
        if n.get("id") == want and n.get("status", "current") == "current":
            return n
    return None


def record_own(project, by, at):
    """Write this graph's own descriptor into a project made before descriptors existed, through the
    gates. Returns the node id, or None when it is there already."""
    from . import work as _work
    from .curate import session as _session
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    if not declared(vocabulary):
        raise GraphError("the vocabulary declares no Graph: the descriptor needs an ontology on oto-core 7 or later")
    live = _session.live(project)
    descriptor = describe(project, vocabulary, live)
    if existing(live, node=descriptor["id"]):
        return None

    def edit(candidate, source):
        candidate["nodes"].append(own_node(descriptor, at))
        return {"node": descriptor["id"]}
    _work._commit(project, "graph %s describes itself: %s" % (descriptor["id"], descriptor["subject"]), by, at, [descriptor["id"]], edit, action="graph describe")
    return descriptor["id"]


def depend(project, descriptor, by, at):
    """Declare that this graph depends on the one `descriptor` describes: its node (a copy of its
    descriptor, as the person declared it) and the edge, through the gates. Returns
    {"node", "edge", "already"}."""
    from . import work as _work
    from .curate import session as _session
    problems = descriptor_problems(descriptor)
    if problems:
        raise GraphError("not a descriptor `oto graph describe` printed:\n  - " + "\n  - ".join(problems))
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    if not declared(vocabulary):
        raise GraphError("the vocabulary declares no Graph: a dependency needs an ontology on oto-core 7 or later")
    own = node_id(project.identity()["slug"])
    if descriptor["id"] == own:
        raise GraphError("%s is this graph: a graph does not depend on itself" % own)
    live = _session.live(project)
    if existing(live, node=own) is None:
        raise GraphError("this graph has no descriptor of its own yet: run `oto graph describe --record` first")
    if existing(live, node=descriptor["id"]) and any(e.get("from") == own and e.get("rel") == DEPENDS_ON and e.get("to") == descriptor["id"]
                                                    for e in live.get("edges") or []):
        return {"node": descriptor["id"], "edge": None, "already": True}
    text = "%s depends on %s (%s), reached at %s" % (own, descriptor["id"], descriptor["subject"], descriptor["reach"])

    def edit(candidate, source):
        if existing(candidate, node=descriptor["id"]) is None:
            candidate["nodes"].append(dict(source, id=descriptor["id"], type=CLASS, label=descriptor["label"],
                                           summary="A graph this one depends on: " + descriptor["subject"],
                                           attributes={"subject": descriptor["subject"], "classes": list(descriptor["classes"]),
                                                       "reach": descriptor["reach"], "slug": descriptor["slug"]}))
        candidate["edges"].append({"from": own, "rel": DEPENDS_ON, "to": descriptor["id"]})
        return {"node": descriptor["id"], "edge": (own, DEPENDS_ON, descriptor["id"]), "already": False}
    return _work._commit(project, text, by, at, [own, descriptor["id"]], edit, action="graph depend")


def dependencies(project):
    """[{id, label, subject, classes, reach}] this graph depends on, from its own facts."""
    from .curate import session as _session
    live = _session.live(project)
    own = node_id(project.identity()["slug"])
    by_id = {n.get("id"): n for n in live.get("nodes") or [] if n.get("status", "current") == "current"}
    out = []
    for e in live.get("edges") or []:
        if e.get("from") == own and e.get("rel") == DEPENDS_ON and e.get("to") in by_id:
            n = by_id[e["to"]]
            a = n.get("attributes") or {}
            out.append({"id": n["id"], "label": n.get("label"), "subject": a.get("subject"), "classes": a.get("classes") or [], "reach": a.get("reach")})
    return sorted(out, key=lambda d: d["id"])
