# -*- coding: utf-8 -*-
"""The studio: a product's pages, assembled from the views of the packs it uses.

Every pack may ship a view of its part (`views/<name>/app.json`); a project installs the views of
the packs it declares. The studio is those views side by side, in the order a reader needs them,
with one look, one navigation, links that open any thing on the page that shows it, and on every
page what is still open. A view says where it belongs in its `app.json`:

    {"name": "pipeline", "title": "The data pipeline", "place": "data",
     "shows": ["Output", "DatasetField"], "open": ["MD"], ...}

`title` is what a reader sees, in plain words; `place` is one of PLACES; `shows` the classes whose
things this page can open (a link to such a thing lands on it, `#<id>`); `open` the competency
questions, by id or by id prefix, whose gaps belong on this page; `portal` true for the product's
front page, which the product type's pack provides. Nothing here names a pack: the studio is what
the project's views declare.

The kit every view includes lives in `oto/ui/_studio/`: `studio.css` (the look), `studio.js` (the
navigation, `Studio.link`, the "still open" box) and `data.js`, generated here, which sets
`window.__STUDIO__`. A view includes them with relative addresses, so the same pages work served
and published:

    <link rel="stylesheet" href="../_studio/studio.css">
    <script src="../_studio/data.js"></script><script src="../_studio/studio.js"></script>
"""
import json
import os
import re

from .manifest import UI_DIR, read

KIT_DIR = os.path.join(UI_DIR, "_studio")
KIT_PREFIX = "_studio"
DATA_NAME = "data.js"
#: Where a page belongs, in the order a reader needs them, and what the reader sees as its heading.
PLACES = (
    ("front", "The product"),
    ("product", "What the product is"),
    ("domain", "What it deals with"),
    ("design", "How it is designed"),
    ("data", "Where the data comes from"),
    ("people", "How people work with it"),
    ("runs", "Where it runs"),
    ("build", "How it is built"),
    ("tools", "Tools"),
    ("other", "More"),
    ("technical", "Technical"),
)
PLACE_IDS = tuple(p for p, _label in PLACES)
FINDING_STATUSES = ("unanswered", "violated")
_PARAM = re.compile(r"\$[A-Z][A-Z0-9_]*")


def page(name, directory):
    """What the studio needs of one view: its title, place, the classes it shows, its open questions."""
    manifest = read(directory)
    title = manifest.get("title") or name.replace("-", " ").capitalize()
    place = manifest.get("place") or "other"
    return {"name": name, "title": title, "place": place if place in PLACE_IDS else "other",
            "summary": (manifest.get("summary") or "").strip(), "shows": list(manifest.get("shows") or []),
            "open": list(manifest.get("open") or []), "portal": bool(manifest.get("portal")), "path": "%s/" % name}


def pages(views):
    """[(name, directory)] as studio pages, in reading order: by place, then as listed."""
    listed = [page(name, directory) for name, directory in views]
    return sorted(listed, key=lambda p: PLACE_IDS.index(p["place"]) if not p["portal"] else -1)


def portal(listed):
    """The front page's name: the first view that says it is one, else None."""
    return next((p["name"] for p in listed if p["portal"]), None)


def _matches(qid, wanted):
    for w in wanted:
        if qid == w or (qid.startswith(w) and qid[len(w):].isdigit()):
            return True
    return False


def _open_items(row):
    """One unanswered question as what a reader sees: the things it is about, each with its gaps in
    words; or, for a question about the whole graph, its gaps (or the question itself)."""
    if row.get("unanswered"):
        out = []
        for item in row["unanswered"]:
            if item.get("gaps"):
                out.append({"label": item.get("label"), "gaps": list(item["gaps"])})
            else:
                # no gap in words: the question itself, about this thing
                out.append({"label": None, "gaps": [_PARAM.sub(item.get("label") or "this", row.get("question") or "").strip()]})
        return out
    gaps = list(row.get("gaps") or [])
    return [{"label": None, "gaps": gaps or [_PARAM.sub("this", row.get("question") or "").strip()]}]


def data(views, payload, survey_rows=None, identity=None):
    """The studio's data: the project, the places with their pages, the front page, which page shows
    each thing, and what is still open on each page."""
    listed = pages(views)
    vocabulary = (payload or {}).get("vocabulary") or {}
    covers = _covers(vocabulary.get("classes") or {})
    entities = {}
    for p in listed:
        kinds = set()
        for kind in p["shows"]:
            kinds |= set(covers.get(kind, {kind}))
        if not kinds:
            continue
        for node in (payload or {}).get("nodes") or []:
            if node.get("type") in kinds and node.get("id") not in entities and node.get("status", "current") != "retired":
                entities[node["id"]] = {"label": node.get("label") or "", "view": p["name"]}
    still_open = {}
    for p in listed:
        if not p["open"]:
            continue
        entries = []
        for row in survey_rows or []:
            if row.get("status") in FINDING_STATUSES and _matches(row.get("id") or "", p["open"]):
                entries.append({"who": row.get("who") or "", "items": _open_items(row)})
        still_open[p["name"]] = entries
    project = dict((payload or {}).get("project") or {})
    if identity:
        project.update({k: identity.get(k) for k in ("name", "slug") if identity.get(k)})
    return {"project": {"name": project.get("name"), "slug": project.get("slug")},
            "places": [{"id": pid, "label": label, "pages": [p["name"] for p in listed if p["place"] == pid and not p["portal"]]}
                       for pid, label in PLACES],
            "pages": listed, "portal": portal(listed), "entities": entities, "open": still_open}


def script(studio_data):
    """`data.js`: the studio's data as a global, so a page reads it with a script tag, served or from disk."""
    return "window.__STUDIO__ = %s;\n" % json.dumps(studio_data, ensure_ascii=False, separators=(",", ":"))


def survey(questions, payload):
    """Every question over the payload's graph, as `oto query questions` runs them."""
    from ..model.vocabulary import covers as covers_of
    from ..reason import questions as _questions
    if not questions:
        return []
    vocabulary = (payload or {}).get("vocabulary") or {}
    derived = {}
    for row in (payload or {}).get("derived_attributes") or []:
        derived.setdefault(row["node"], {})[row["name"]] = row["value"]
    return _questions.survey(questions, payload.get("nodes") or [], payload.get("edges") or [],
                             covers_of(vocabulary.get("classes") or {}), derived,
                             _questions.declared_names(vocabulary))


def _covers(classes):
    from ..model.vocabulary import covers as covers_of
    try:
        return covers_of(classes)
    except Exception:                                                   # noqa: BLE001 - a store with no vocabulary
        return {}
