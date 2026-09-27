# -*- coding: utf-8 -*-
"""Facts that cite a document which has since arrived as a new version.

An ingest run records each file's content hash. When the same filename arrives with different
bytes, the run says so, and then the question is: do the facts citing the old version still hold?
Nothing can answer that automatically, so this module keeps the obligation visible instead. A fact
is re-attested when a proposal from the new version lists it again, which moves its `as_of` to
that date. Until then, or until it is retired, it is reported: by `oto curate check` as a gap, by
`oto status` as a count, and `oto ingest complete` refuses to close the run with any outstanding.
"""
from ..intake import pipeline as _pipeline


def new_versions(project):
    """slug -> (run_id, date) for the latest run in which that document arrived changed."""
    out = {}
    for manifest in _pipeline.runs(project):
        started = (manifest.get("started") or "")[:10]
        for entry in manifest.get("files") or []:
            if entry.get("previous_sha256") and entry.get("slug"):
                out[entry["slug"]] = (manifest.get("run_id"), started)
    return out


def _cites(node, slug):
    return slug == node.get("source_doc") or slug in (node.get("sources") or [])


def pending(project, graph):
    """[{id, slug, run_id, since}] for every current node citing a re-ingested document whose
    `as_of` predates that run: nobody has looked at it against the new text."""
    versions = new_versions(project)
    if not versions:
        return []
    out = []
    for node in graph.get("nodes") or []:
        if node.get("status", "current") != "current":
            continue
        for slug, (run_id, since) in versions.items():
            if _cites(node, slug) and str(node.get("as_of") or "") < since:
                out.append({"id": node.get("id"), "slug": slug, "run_id": run_id, "since": since})
    return sorted(out, key=lambda r: (r["slug"], r["id"]))
