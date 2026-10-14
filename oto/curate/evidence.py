# -*- coding: utf-8 -*-
"""Quotes that hold: every fact cites the sentence that says it, and that sentence is in the document.

A fact's evidence is `{"doc", "where", "quote"}`: the document, the place in it, and the sentence,
word for word. `oto curate check` looks each new quote up in the document it cites, when the project
holds that document (`build/documents/<doc>.md`, written by `oto ingest`):

- a quote that is not in its document is **blocking**: a citation that does not hold is worse than
  none, because it looks checkable;
- a fact with no quote, and a quote whose document the project does not hold, are **gaps**, one per
  document, naming the first few facts: a value read from a table or a diagram has no sentence, and
  a document may come later.

The comparison forgives what extraction and typing change and keeps the words: case, spacing, quote
marks, dashes and hyphens (a word broken at a line end), ligatures, and Markdown emphasis, links and
table bars, and the punctuation at a quote's ends (a quote may stop where the sentence goes on). `…`
(or `...`) joins parts of one passage that must appear in that order.
"""
import os
import re
import unicodedata

#: How many facts a gap names before "and N more".
SHOWN = 5
_QUOTES = "\"'`‘’‚‛“”„‟«»‹›"
_DASHES = "-‐‑‒–—―−­"
_DROP = re.compile("[%s%s*_#>|]" % (re.escape(_QUOTES), re.escape(_DASHES)))
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_SPACE = re.compile(r"\s+")
_BROKEN = re.compile("[%s]\\s*\\n\\s*" % re.escape(_DASHES))
_ELLIPSIS = re.compile(r"…|\.\.\.")


def normalise(text):
    """Text as the comparison sees it: the words, in order, without what extraction or typing varies."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _BROKEN.sub("", text)                 # a word broken at a line end is one word
    text = _LINK.sub(r"\1", text)
    text = _DROP.sub("", text)
    return _SPACE.sub(" ", text).strip().lower()


def found(quote, text):
    """Whether the quote is in the text: every part between ellipses, in order."""
    # a quote may stop where the sentence goes on: the punctuation at its ends is not its words
    parts = [normalise(p).strip(" .,;:!?") for p in _ELLIPSIS.split(quote or "")]
    parts = [p for p in parts if p]
    if not parts:
        return False
    at = 0
    for part in parts:
        at = text.find(part, at)
        if at < 0:
            return False
        at += len(part)
    return True


def no_sentence(node):
    """Whether a fact quotes no sentence: no quote at all, or its own name standing in for one (how
    facts were saved before quotes were checked)."""
    label = normalise(node.get("label"))
    quotes = [normalise(e.get("quote")) for e in (node.get("evidence") or []) if isinstance(e, dict)]
    return bool(node.get("evidence")) and not any(q and q != label for q in quotes)


class _Corpus:
    """The project's documents as the comparison sees them, read once each."""

    def __init__(self, corpus_dir):
        self.dir = corpus_dir
        self.texts = {}

    def text(self, doc):
        if doc not in self.texts:
            path = os.path.join(self.dir, "%s.md" % doc) if self.dir and doc else None
            if path and os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.texts[doc] = normalise(f.read())
            else:
                self.texts[doc] = None
        return self.texts[doc]


def _new_entries(node, live_node):
    """The evidence this change brings: all of a new fact's, only the added entries of a known one."""
    before = [e for e in ((live_node or {}).get("evidence") or []) if isinstance(e, dict)]
    return [e for e in (node.get("evidence") or []) if isinstance(e, dict) and e not in before]


def _named(ids):
    shown = ", ".join(ids[:SHOWN])
    return shown + (" and %d more" % (len(ids) - SHOWN) if len(ids) > SHOWN else "")


def check(live, candidate, corpus_dir):
    """[(severity, subject, message)] about the quotes this candidate brings. Severity is
    "blocking" or "gap"; the caller turns them into its findings."""
    from .diff import index_nodes
    live_by_id = index_nodes(live or {})
    corpus = _Corpus(corpus_dir)
    out, unquoted, unheld = [], {}, {}
    for node in (candidate or {}).get("nodes") or []:
        nid = node.get("id")
        if not nid or node.get("source_type") == "human_assertion":
            continue
        entries = _new_entries(node, live_by_id.get(nid))
        if not entries:
            continue
        for entry in entries:
            doc, quote = entry.get("doc"), (entry.get("quote") or "").strip()
            if not doc:
                continue
            if not quote:
                unquoted.setdefault(doc, []).append(nid)
                continue
            text = corpus.text(doc)
            if text is None:
                unheld.setdefault(doc, []).append(nid)
            elif not found(quote, text):
                out.append(("blocking", nid, "its quote is not in the document it cites (%s): \"%s\"; quote the "
                                             "sentence word for word, or leave the quote out" % (doc, quote[:120])))
    for doc, ids in sorted(unquoted.items()):
        out.append(("gap", doc, "%d fact(s) from this document say where they come from but not the sentence that says "
                                "it: %s" % (len(ids), _named(ids))))
    for doc, ids in sorted(unheld.items()):
        out.append(("gap", doc, "the knowledge base does not hold this document, so the quotes of %d fact(s) cannot be "
                                "checked: %s (add it to inbox/ and run oto ingest)" % (len(ids), _named(ids))))
    return out
