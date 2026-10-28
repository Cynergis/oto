# -*- coding: utf-8 -*-
"""Two helpers every pack and the engine's own tools share: a slug for a node id, and the ids the live
graph holds. They were the data pack's until ADR-0006 step 5 named them the engine's."""
import re


def slug(text):
    """Lowercase letters, digits and hyphens: the tail of a node id."""
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def graph_ids(project):
    """The ids of every node in the live graph, so a proposal can say what it points at that the graph lacks."""
    from .curate import session as _session
    return {n.get("id") for n in _session.live(project).get("nodes") or [] if n.get("id")}
