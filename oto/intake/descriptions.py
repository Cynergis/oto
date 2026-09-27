# -*- coding: utf-8 -*-
"""Give every figure a description, so figures are searchable.

An extracted deck leaves a placeholder for each figure. A figure with no words is invisible to
retrieval, so each placeholder is replaced by either a curated description or an automatic summary
built from the text on the slide.

This is a pure text transform: it takes markdown and returns markdown. That makes it testable and
keeps extraction reproducible.
"""
import re

PLACEHOLDER = re.compile(
    r'^> \*\*\[DIAGRAM\]\*\* \((.+?)\) — see `assets/([^/]+)/((?:slide|page|image)-(\d+)\.(?:png|jpe?g|gif|webp|svg))`\. '
    r'_Description added in review pass\._\s*$')
HEADING = re.compile(r'^#{2,4} (?:Slide|Page) \d+(?: — (.*))?$')

#: The same line after injection: the marker is gone and the description follows two lines down.
INJECTED = re.compile(
    r'^> \*\*\[DIAGRAM\]\*\* \((.+?)\) — see `assets/([^/]+)/((?:slide|page|image)-(\d+)\.(?:png|jpe?g|gif|webp|svg))`\.\s*$')
PLACEHOLDER_MARKER = "_Description added in review pass._"
#: What the automatic summary says when the figure carried no labels to summarize. It looks like a
#: description and adds nothing, so a figure carrying it still needs eyes.
NO_LABELS = "A visual graphic; see the linked image for the full layout."
MAX_LABELS = 8
MAX_LABEL_CHARS = 120
# Lines scanned after a placeholder for bullet labels. The legacy window was 29 lines; a
# wider window picks up an extra label and changes the summary text, so it is pinned.
LOOKAHEAD_LINES = 29


def auto_summary(title, following):
    """Summarize a figure from the text printed on it. The weakest option, but never empty."""
    labels = []
    for line in following:
        s = line.strip()
        if s.startswith("- "):
            candidate = s[2:].strip()
            if candidate and len(candidate) < MAX_LABEL_CHARS:
                labels.append(candidate)
        if len(labels) >= MAX_LABELS:
            break
    out = "**Description (auto-summary from on-slide text):** "
    title = (title or "").strip()
    if title:
        out += "Diagram titled “%s”. " % title
    if labels:
        out += "Key on-slide elements: " + "; ".join(labels[:MAX_LABELS]) + "."
    else:
        out += NO_LABELS
    return out


def inject(text, curated=None):
    """Replace every figure placeholder. Returns (text, n_curated, n_auto)."""
    curated = curated or {}
    lines = text.split("\n")
    out = []
    current_title = ""
    n_curated = n_auto = 0

    for index, line in enumerate(lines):
        heading = HEADING.match(line)
        if heading:
            current_title = heading.group(1) or ""
        match = PLACEHOLDER.match(line)
        if not match:
            out.append(line)
            continue
        reasons, slug, image, number = match.group(1), match.group(2), match.group(3), match.group(4)
        key = "%s#%d" % (slug, int(number))
        base = "> **[DIAGRAM]** (%s) — see `assets/%s/%s`." % (reasons, slug, image)
        if key in curated:
            n_curated += 1
            body = "> **Description:** %s" % curated[key]
        else:
            n_auto += 1
            body = "> %s" % auto_summary(current_title, lines[index + 1:index + 1 + LOOKAHEAD_LINES])
        out.append(base)
        out.append(">")
        out.append(body)

    return "\n".join(out), n_curated, n_auto


def needs_injection(text):
    return PLACEHOLDER_MARKER in text
