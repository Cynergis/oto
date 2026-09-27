# -*- coding: utf-8 -*-
"""Find figures that carry no description.

A figure with no words is invisible to retrieval. Extraction leaves a placeholder for each one, and a
later pass replaces it with a description. That pass is easy to skip, and a skipped figure is silently
missing from the knowledge base rather than visibly broken.

This module reports the gap and produces a worklist, so the missing descriptions can be written.

A deliberate limit: an automatic summary is built from the text printed on the slide. When a figure
carries a title but no labels, the summary repeats the title, and the title is already in the heading
and already indexed. Such a summary looks like a description and adds nothing. So the report separates
"an automatic summary would help" from "this figure needs eyes on it", and never counts the second as
described.
"""
import json
import os

from .descriptions import HEADING, INJECTED, LOOKAHEAD_LINES, NO_LABELS, PLACEHOLDER, auto_summary

USEFUL = "auto-summary would add on-slide labels"
NEEDS_EYES = "needs a real description: no labels to summarize"

#: A second axis, independent of the first. Whether a figure CAN be described now depends on whether
#: its image is on disk, and the two questions have different answers and different fixes. A figure
#: that needs eyes and has no image cannot be worked on at all: sending a person or a vision pass to
#: a path that does not exist wastes the pass and looks like a description failure. The images are
#: often absent because rendering them is a separate step from extracting the text.
IMAGE_PRESENT = "image on disk"
IMAGE_MISSING = "image not rendered yet"


def scan_corpus(corpus_dir, curated=None):
    """Return a list of undescribed figures, each with enough context to describe it."""
    curated = curated or {}
    out = []
    for name in sorted(os.listdir(corpus_dir)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(corpus_dir, name)
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        title = ""
        for index, line in enumerate(lines):
            heading = HEADING.match(line)
            if heading:
                title = heading.group(1) or ""
            match = PLACEHOLDER.match(line)
            injected_without_labels = False
            if not match:
                # Ingest injects a description into every placeholder, so on a real corpus the
                # marker is gone. An injected automatic summary that found no labels is still an
                # undescribed figure, and this is where it gets reported.
                match = INJECTED.match(line)
                if not match:
                    continue
                description = lines[index + 2] if index + 2 < len(lines) else ""
                if not (description.startswith("> **Description (auto-summary") and NO_LABELS in description):
                    continue                     # curated, or a summary with real labels: described
                injected_without_labels = True
            reasons, slug, image, number = match.groups()
            key = "%s#%d" % (slug, int(number))
            summary = "" if injected_without_labels else auto_summary(title, lines[index + 1:index + 1 + LOOKAHEAD_LINES])
            relative = os.path.join("assets", slug, image)
            out.append({
                "document": name,
                "key": key,
                "image": relative,
                "image_present": os.path.exists(os.path.join(corpus_dir, relative)),
                "title": title,
                "detected_because": reasons,
                "curated": key in curated,
                "verdict": USEFUL if "Key on-slide elements" in summary else NEEDS_EYES,
            })
    return out


def report(figures):
    """A short summary plus the per-document breakdown."""
    if not figures:
        return "Every figure has a description."
    useful = [f for f in figures if f["verdict"] == USEFUL]
    eyes = [f for f in figures if f["verdict"] == NEEDS_EYES]
    blocked = [f for f in eyes if not f.get("image_present")]
    by_document = {}
    for f in figures:
        by_document.setdefault(f["document"], 0)
        by_document[f["document"]] += 1

    lines = ["%d figure(s) have no description, across %d document(s)."
             % (len(figures), len(by_document)), ""]
    lines.append("  %d could be summarized from on-slide labels" % len(useful))
    lines.append("  %d need a real description: there is nothing to summarize" % len(eyes))
    if blocked:
        lines.append("    of those, %d have no image on disk and cannot be described by anyone until "
                     "it is rendered" % len(blocked))
    lines.append("")
    for document in sorted(by_document):
        lines.append("  %-58s %d" % (document, by_document[document]))
    if blocked:
        lines.append("")
        lines.append("Render the missing images before starting a description pass. Sending a person "
                     "or a vision model to a path")
        lines.append("that does not exist wastes the pass, and the result looks like a description "
                     "failure rather than a missing file.")
    return "\n".join(lines)


def worklist(figures, path):
    """Write a worklist a person or a vision pass can work through, then feed back as curated JSON."""
    payload = {
        "_about": "Figures with no description. Fill `description` for each, then save the mapping of "
                  "key to description as diagram_descriptions.json in the project.",
        # Ordered so everything workable comes first. A worklist that opens with entries nobody can
        # act on reads as a broken tool.
        "figures": [{"key": f["key"], "document": f["document"], "image": f["image"],
                     "image_present": f.get("image_present", False),
                     "title": f["title"], "detected_because": f["detected_because"],
                     "verdict": f["verdict"], "description": ""}
                    for f in sorted(figures, key=lambda x: not x.get("image_present"))],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path
