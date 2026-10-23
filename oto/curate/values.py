# -*- coding: utf-8 -*-
"""Values that hold: a number, a date or a code on a fact is stated by the source it cites.

The quote check (`evidence.py`) proves a fact's sentence is in its document. It cannot see that the
fact misread the sentence: `interval_km: 2000` quoting "the interval is 20,000 km" passes it. So
each literal value a change brings is looked for in the fact's quotes, then in the documents they cite:

- found in a quote: the evidence states it;
- found in a cited document but no quote: the value is probably right and its evidence incomplete,
  a **gap**: quote the sentence that states it;
- found in no cited document: the source never states it, so it was misread or invented, and it is
  **blocking**.

Literal means a number, an ISO date, or an identifier: a short string with a digit and no spaces
("WO-2291", "BRK-221", "4127", "305/70R22.5"). Words such as "open" are judgements about a source,
not text in it, and are not checked here; neither is a URL or an address, a reference often
configured rather than quoted. A number is matched in its usual written forms ("20,000", "20000",
"1,800.5", "12%"), a date as ISO, with slashes, or written out with or without its year ("5 August
2025", "August 5", "28 Au-gust" broken across a line): documents often leave the year to their own
date, but a year that is written must be the value's.

A fact citing a recorded assertion (`source_type: human_assertion`) is checked against the assertion's
words, the whole of its source: absent from them, the value blocks; equal only to the assertion's own
date, it is a gap, as a captured note's header date is. A value that cannot be checked at all (no
quote, or a quote from a document the project does not hold, or an assertion not on record) is not a
finding, but `unchecked` counts it, so a check that passed is never mistaken for one that ran.
"""
import datetime
import os
import re

from .evidence import _Corpus, normalise

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: A written number: digits with thousands separators (comma or a no-break space), or plain digits,
#: with an optional decimal part. Plain spaces are not separators: "12 16" is two table cells.
NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
#: An identifier: short, no spaces; a URL or an address is not one.
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9./_#-]{0,39}")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def _numbers(text):
    out = set()
    for m in NUMBER.finditer(text or ""):
        try:
            out.add(float(re.sub(r"[,  ]", "", m.group(0))))
        except ValueError:
            pass
    return out


def _date_stated(value, raw_text, normal_text):
    day = datetime.date.fromisoformat(value)
    lower = (raw_text or "").lower()
    if any(form in lower for form in (value, "%02d/%02d/%d" % (day.day, day.month, day.year),
                                      "%02d/%02d/%d" % (day.month, day.day, day.year))):
        return True
    month = MONTHS[day.month - 1].lower()
    for pattern in (r"(?<!\d)%d %s(?![a-z])(?:,? (\d{4}))?" % (day.day, month),
                    r"(?<![a-z])%s %d(?!\d)(?:,? (\d{4}))?" % (month, day.day)):
        for m in re.finditer(pattern, normal_text or ""):
            if not m.group(1) or int(m.group(1)) == day.year:
                return True
    return False


def _kind(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str) and ISO_DATE.match(value):
        try:
            datetime.date.fromisoformat(value)
            return "date"
        except ValueError:
            return "code"
    if isinstance(value, str) and IDENTIFIER.fullmatch(value) and any(c.isdigit() for c in value):
        return "code"
    return None


def stated(value, raw_text, normal_text):
    """Whether a text states the value. `raw_text` keeps separators and case; `normal_text` is the
    quote check's normal form, for identifiers."""
    kind = _kind(value)
    if kind == "number":
        return any(abs(n - float(value)) < 1e-9 for n in _numbers(raw_text))
    if kind == "date":
        return _date_stated(value, raw_text, normal_text)
    if kind == "code":
        wanted = normalise(value)
        return bool(wanted) and re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(wanted), normal_text or "") is not None
    return True


def _changed(node, live_node):
    """The attributes this change brings: all of a new fact's, only new or different values of a known one."""
    before = (live_node or {}).get("attributes") or {}
    return {k: v for k, v in (node.get("attributes") or {}).items() if k not in before or before[k] != v}


def _review(live, candidate, corpus_dir, assertions=None):
    """(status, node id, attribute, value, detail) for each literal value this candidate brings; status is
    "ok", "gap", "blocking" or "unchecked"."""
    from .assertions import cited_ids
    from .diff import index_nodes
    live_by_id = index_nodes(live or {})
    corpus = _Corpus(corpus_dir)
    raw = {}
    for node in (candidate or {}).get("nodes") or []:
        nid = node.get("id")
        if not nid:
            continue
        changed = [(k, v) for k, v in sorted(_changed(node, live_by_id.get(nid)).items()) if _kind(v) is not None]
        if not changed:
            continue
        if node.get("source_type") == "human_assertion":
            cited = sorted(cited_ids(node))
            entries = [(assertions or {}).get(i) for i in cited]
            if not cited or not all(entries):
                why = "cites no assertion on record" if not cited else \
                    "cites assertion %s, not on record" % ", ".join(i for i, e in zip(cited, entries) if not e)
                for name, value in changed:
                    yield "unchecked", nid, name, value, why
                continue
            for name, value in changed:
                if any(stated(value, e.get("text"), normalise(e.get("text"))) for e in entries):
                    yield "ok", nid, name, value, ""
                elif any(e.get("at") == value for e in entries):
                    yield ("gap", nid, name, value, "%s = %r is the date of assertion %s, not in its words: confirm when "
                           "it became true" % (name, value, ", ".join(cited)))
                else:
                    yield ("blocking", nid, name, value, "%s = %r appears nowhere in assertion %s: a value its source "
                           "never states was misread or invented" % (name, value, ", ".join(cited)))
            continue
        evidence = [e for e in node.get("evidence") or [] if isinstance(e, dict) and e.get("doc") and e.get("quote")]
        docs = sorted({e["doc"] for e in evidence if corpus.text(e["doc"]) is not None})
        if not docs:
            why = "no quote" if not evidence else \
                "quotes %s, which the project does not hold" % ", ".join(sorted({e["doc"] for e in evidence}))
            for name, value in changed:
                yield "unchecked", nid, name, value, why
            continue
        for doc in docs:
            if doc not in raw:
                with open(os.path.join(corpus.dir, "%s.md" % doc), encoding="utf-8", errors="replace") as f:
                    raw[doc] = f.read()
        quotes = [e["quote"] for e in evidence]
        for name, value in changed:
            if any(stated(value, q, normalise(q)) for q in quotes):
                yield "ok", nid, name, value, ""
                continue
            holding = [doc for doc in docs if stated(value, raw[doc], corpus.text(doc))]
            if holding:
                yield ("gap", nid, name, value, "%s = %r is in %s but not in the quotes it cites: quote the sentence "
                       "that states it" % (name, value, ", ".join(holding)))
            else:
                yield ("blocking", nid, name, value, "%s = %r appears nowhere in %s: a value its source never states "
                       "was misread or invented" % (name, value, ", ".join(docs)))


def check(live, candidate, corpus_dir, assertions=None):
    """[(severity, subject, message)] about the literal values this candidate brings. `assertions` maps
    an assertion id to its entry in the log."""
    return [(status, nid, detail) for status, nid, _, _, detail in _review(live, candidate, corpus_dir, assertions)
            if status in ("gap", "blocking")]


def unchecked(live, candidate, corpus_dir, assertions=None):
    """[(node id, attribute, why)] for each literal value nothing could check."""
    return [(nid, name, detail) for status, nid, name, _, detail in _review(live, candidate, corpus_dir, assertions)
            if status == "unchecked"]


def describe_unchecked(items, show=5):
    """One line for the check's report: how many values went unchecked, and on which facts."""
    facts = []
    for nid, _, _ in items:
        if nid not in facts:
            facts.append(nid)
    why = {}
    for nid, _, detail in items:
        why.setdefault(nid, detail)
    shown = ", ".join("%s (%s)" % (nid, why[nid]) for nid in facts[:show])
    return "values not checked: %d on %d fact%s, with nothing to check them against: %s%s" % (
        len(items), len(facts), "" if len(facts) == 1 else "s", shown,
        ", and %d more" % (len(facts) - show) if len(facts) > show else "")
