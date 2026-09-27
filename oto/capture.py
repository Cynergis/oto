# -*- coding: utf-8 -*-
"""Knowledge that arrived in conversation, written down as a source document.

The most valuable corrections are spoken: "that is wrong, the owner changed in March". A curator
working locally records one with `oto curate assert`, which gives it an id that facts cite. Most
people are not curators, and in a project that lives in a repository the way knowledge enters is
the inbox. So a conversation becomes a *document*: dated, attributed, the statements in the
speaker's words, and it goes through ingest, drafting, the gates and the pull request like any
other file. The graph then cites it as a source, the same way it cites a memo.

The note has one shape, written here rather than by hand, so every capture carries the same
header and the drafting rules can read it: who said it, when, what it refers to, and that it is a
record of speech rather than an authored document.
"""
import datetime
import os
import re

from .intake.document import slugify

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def note(title, statements, by, at, about=None, context=None, recorded_by=None):
    """The Markdown for one captured conversation."""
    if not ISO_DATE.match(at or ""):
        raise ValueError("--at must be a YYYY-MM-DD date: the date the statements refer to, not today")
    if not (by or "").strip():
        raise ValueError("--by is required: an unattributed statement cannot be followed up")
    statements = [s.strip() for s in statements if s and s.strip()]
    if not statements:
        raise ValueError("at least one statement is required")
    lines = ["# %s" % title.strip(), "",
             "> **Captured:** %s · **By:** %s · **Recorded by:** %s" % (at, by.strip(), recorded_by or "an agent, in conversation")
             + (" · **About:** %s" % ", ".join(about) if about else ""),
             ">", "> This note records statements made in conversation, in the speaker's words, on the date "
             "they refer to. It is a source document: a fact derived from it cites it, and the speaker "
             "named above is who to ask.", "", "## Statements", ""]
    for number, statement in enumerate(statements, 1):
        lines.append("%d. \"%s\" — %s, %s" % (number, statement.replace('"', "'"), by.strip(), at))
    if context and context.strip():
        lines += ["", "## Context", "", context.strip()]
    return "\n".join(lines) + "\n"


def filename(title, at):
    return "%s-%s.md" % (at, slugify(title)[:60] or "capture")


def write(project, title, statements, by, at, about=None, context=None, recorded_by=None, force=False):
    """Write the note into the project's inbox. Returns (path, warnings)."""
    from .curate import session as _session

    warnings = []
    known = {n.get("id") for n in (_session.live(project).get("nodes") or [])}
    for nid in about or []:
        if nid not in known:
            warnings.append("about %r: no such id in the graph; the drafter will treat it as a name to resolve" % nid)
    text = note(title, statements, by, at, about=about, context=context, recorded_by=recorded_by)
    inbox = project.layout.inbox
    os.makedirs(inbox, exist_ok=True)
    path = os.path.join(inbox, filename(title, at))
    if os.path.exists(path) and not force:
        raise FileExistsError(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path, warnings
