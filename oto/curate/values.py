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


def check(live, candidate, corpus_dir):
    """[(severity, subject, message)] about the literal values this candidate brings."""
    from .diff import index_nodes
    live_by_id = index_nodes(live or {})
    corpus = _Corpus(corpus_dir)
    raw = {}
    out = []
    for node in (candidate or {}).get("nodes") or []:
        nid = node.get("id")
        if not nid or node.get("source_type") == "human_assertion":
            continue
        evidence = [e for e in node.get("evidence") or [] if isinstance(e, dict) and e.get("doc") and e.get("quote")]
        if not evidence:
            continue
        docs = sorted({e["doc"] for e in evidence if corpus.text(e["doc"]) is not None})
        if not docs:
            continue
        for doc in docs:
            if doc not in raw:
                with open(os.path.join(corpus.dir, "%s.md" % doc), encoding="utf-8", errors="replace") as f:
                    raw[doc] = f.read()
        quotes = [e["quote"] for e in evidence]
        for name, value in sorted(_changed(node, live_by_id.get(nid)).items()):
            if _kind(value) is None:
                continue
            if any(stated(value, q, normalise(q)) for q in quotes):
                continue
            holding = [doc for doc in docs if stated(value, raw[doc], corpus.text(doc))]
            if holding:
                out.append(("gap", nid, "%s = %r is in %s but not in the quotes it cites: quote the sentence that "
                                        "states it" % (name, value, ", ".join(holding))))
            else:
                out.append(("blocking", nid, "%s = %r appears nowhere in %s: a value its source never states was "
                                             "misread or invented" % (name, value, ", ".join(docs))))
    return out
