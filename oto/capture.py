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

Two things are checked as the note is written, because they are cheapest to fix while the speaker is
still in the room. Both are warnings: the note keeps the speaker's words and the ids it was given.

- A statement that dates itself by "today", "last week" or "the same day" cannot be quoted for a
  date: the value check in `oto curate check` finds the date in the note's header, not in the words,
  and reports a gap. The warning names the expression, and for today, yesterday and tomorrow the
  date it would mean if `--at` is the day it was said, so the speaker can be asked to say the date.
- An `--about` is matched as a lookup matches a name: a current id is quiet; a retired one names its
  current version; a label, an alias or a lexicon word names the id it binds; a name of several
  entities lists them; a near name is said to be no match. The drafter never has to guess.
"""
import datetime
import os
import re

from .intake.document import slugify

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNIT = r"(?:days?|weeks?|months?|years?|quarters?)"
_DAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|night|morning|weekend)"
_COUNT = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|a few|several|couple of)"
#: Expressions that date a statement by when it was said rather than by a date.
RELATIVE = re.compile(r"(?<![\w-])(?:today|yesterday|tomorrow|tonight|"
                      r"(?:this|last|next|past) (?:%s|%s)|" % (_UNIT, _DAY) +
                      r"%s %s (?:ago|later|earlier|before|after|from now)|" % (_COUNT, _UNIT) +
                      r"the (?:same|next|following|previous|other) day|the day (?:before|after)|"
                      r"(?:earlier|later) this %s|recently)(?![\w-])" % _UNIT, re.IGNORECASE)
OFFSET = {"today": 0, "tonight": 0, "yesterday": -1, "tomorrow": 1}


def relative_dates(statements, at):
    """A warning for each statement that dates itself relative to when it was said."""
    out = []
    for number, statement in enumerate(statements, 1):
        for m in RELATIVE.finditer(statement):
            said = m.group(0).lower()
            meaning = ""
            if said in OFFSET:
                day = datetime.date.fromisoformat(at) + datetime.timedelta(days=OFFSET[said])
                meaning = " (%s, if --at %s is the day it was said)" % (day.isoformat(), at)
            out.append("statement %d dates itself by %r%s: a fact can only quote a date its words state; "
                       "ask the speaker for the date and record it as they say it" % (number, said, meaning))
    return out


def _current(by_id, nid):
    """The current version of a fact, following superseded_by; None when the chain ends elsewhere."""
    seen = set()
    while nid in by_id and nid not in seen:
        seen.add(nid)
        node = by_id[nid]
        if node.get("status", "current") == "current":
            return nid
        nxt = node.get("superseded_by")
        nid = nxt[0] if isinstance(nxt, list) and nxt else nxt
    return None


def about_warnings(graph, lexicon, about):
    """A warning for each `--about` that is not the id of a current entity, naming what it matches."""
    nodes = [n for n in (graph or {}).get("nodes") or [] if n.get("id")]
    by_id = {n["id"]: n for n in nodes}
    current = [n for n in nodes if n.get("status", "current") == "current"]
    out = []
    for term in about or []:
        if term in by_id:
            if by_id[term].get("status", "current") == "current":
                continue
            now = _current(by_id, term)
            out.append("about %r is %s%s" % (term, by_id[term].get("status"),
                                              "; its current version is %r: name that if the statements concern "
                                              "the present" % now if now else ", with no current version"))
            continue
        needle = term.strip().lower()
        found = {}
        for node in current:
            if str(node.get("label") or "").strip().lower() == needle:
                found.setdefault(node["id"], "label")
            elif needle in (str(a).strip().lower() for a in node.get("aliases") or []):
                found.setdefault(node["id"], "alias")
        if not found:
            for entry in (lexicon or {}).get("entries") or []:
                names = [entry.get("term")] + list(entry.get("aka") or [])
                if entry.get("status", "current") == "current" and needle in (str(n or "").strip().lower() for n in names):
                    for target in entry.get("targets") or []:
                        now = _current(by_id, target)
                        if now:
                            found.setdefault(now, "lexicon")
        if len(found) == 1:
            (nid, grade), = found.items()
            out.append("about %r is not an id; it names %s (%s): give the id" % (term, nid, grade))
        elif found:
            out.append("about %r names %d entities: %s; give the id of the one meant"
                       % (term, len(found), ", ".join(sorted(found))))
        else:
            near = sorted(n["id"] for n in current
                          if needle and (needle in n["id"].lower() or needle in str(n.get("label") or "").lower()
                                         or any(needle in str(a).lower() for a in n.get("aliases") or [])))
            out.append("about %r: no such id or name in the graph%s" % (
                term, "; closest by name, not a match: %s" % ", ".join(near[:5]) if near
                else "; the drafter will treat it as a name to resolve"))
    return out


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
    from .model import lexicon as _lexicon

    text = note(title, statements, by, at, about=about, context=context, recorded_by=recorded_by)
    inbox = project.layout.inbox
    os.makedirs(inbox, exist_ok=True)
    path = os.path.join(inbox, filename(title, at))
    if os.path.exists(path) and not force:
        raise FileExistsError(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    statements = [s.strip() for s in statements if s and s.strip()]
    warnings = relative_dates(statements, at) + about_warnings(_session.live(project), _lexicon.load(project), about)
    return path, warnings
