# -*- coding: utf-8 -*-
"""Survey the corpus, so the vocabulary and the graph start from what the documents actually say.

Designing a vocabulary starts with the words the material uses, and authoring a graph starts with
the things the material names. Reading every document is still required. This pass gives the reader
a map before the reading: what each document is, how it is structured, which capitalised phrases
recur across documents, which acronyms appear, and which dates are mentioned.

It is deliberately dumb. No model, no dictionary of the domain, no inference: a recurring
capitalised phrase is a *candidate* for an entity, and a person or an agent decides. Everything
here is a count, so two runs over the same corpus agree.
"""
import os
import re
from collections import Counter, defaultdict

#: A run of capitalised words, allowing the small connectors a name may carry ("Notice of Loss").
PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9&'\-]+(?:(?:\s+(?:of|and|for|the|de|du|des|von|van|di|da))?"
                    r"\s+(?:[A-Z][A-Za-z0-9&'\-]+|\d[A-Za-z0-9\-]*)){0,4}\b")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,6}\b")
ISO_DATE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*$")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
#: Characters before a single capitalised word that mean "start of a sentence", where the capital
#: says nothing about the word. Multi-word phrases are kept regardless: "Claims Adjuster" at the
#: start of a sentence is still a name.
SENTENCE_START = set(".!?:\n#*-|>\"'(`")
STOP = set("the a an and or of to in on for with by as at is are be this that these those it its "
           "from into we you they our your their if then than when where how what which who not no "
           "all any each per via may can will shall must should".split())


def read_corpus(corpus_dir):
    """(slug, text) for every markdown file in the corpus, sorted, assets skipped."""
    out = []
    if not os.path.isdir(corpus_dir):
        return out
    for name in sorted(os.listdir(corpus_dir)):
        path = os.path.join(corpus_dir, name)
        if not name.endswith(".md") or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            out.append((name[:-3], f.read()))
    return out


def _clean(text):
    """Strip markdown syntax that would otherwise glue onto a phrase."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("**", " ").replace("__", " ")


def profile(slug, text):
    """What one document is: title, headings, size, dates mentioned."""
    title = None
    headings = []
    for line in text.splitlines():
        m = HEADING.match(line)
        if not m:
            continue
        if len(m.group(1)) == 1 and title is None:
            title = m.group(2)
        else:
            headings.append(m.group(2))
    dates = sorted(set(ISO_DATE.findall(text)))
    return {"slug": slug, "title": title or slug, "headings": headings,
            "words": len(WORD.findall(text)), "dates": dates}


def phrases(text):
    """Capitalised phrases in one document, with counts. A lone capitalised word at the start of a
    sentence is not counted: its capital is grammar, not a name."""
    counts = Counter()
    text = _clean(text)
    for m in PHRASE.finditer(text):
        phrase = re.sub(r"\s+", " ", m.group(0))
        single = " " not in phrase
        # "The Fraud Unit" at the start of a sentence: the article is grammar, the rest is a name.
        tokens = phrase.split(" ")
        while len(tokens) > 1 and tokens[0].lower() in STOP:
            tokens.pop(0)
        phrase = " ".join(tokens)
        if single:
            if phrase.lower() in STOP or len(phrase) < 3:
                continue
            before = text[:m.start()].rstrip(" \t")
            if not before or before[-1] in SENTENCE_START:
                continue
        counts[phrase] += 1
    return counts


def acronyms(text):
    counts = Counter()
    for m in ACRONYM.finditer(_clean(text)):
        token = m.group(0)
        if not any(c.isalpha() for c in token) or len(token) < 2:
            continue
        counts[token] += 1
    return counts


def survey(corpus_dir, top=40, min_count=2):
    """The whole map. `top` limits the term and acronym lists; `min_count` is the floor for both."""
    docs = read_corpus(corpus_dir)
    documents, term_total, term_docs, acro_total, acro_docs = [], Counter(), defaultdict(set), Counter(), defaultdict(set)
    for slug, text in docs:
        documents.append(profile(slug, text))
        for phrase, n in phrases(text).items():
            term_total[phrase] += n
            term_docs[phrase].add(slug)
        for token, n in acronyms(text).items():
            acro_total[token] += n
            acro_docs[token].add(slug)

    def ranked(total, per_doc):
        rows = [{"term": t, "count": n, "documents": sorted(per_doc[t])}
                for t, n in total.items() if n >= min_count]
        rows.sort(key=lambda r: (-len(r["documents"]), -r["count"], r["term"]))
        return rows[:top]

    return {"documents": documents,
            "terms": ranked(term_total, term_docs),
            "acronyms": ranked(acro_total, acro_docs),
            "totals": {"documents": len(documents),
                       "words": sum(d["words"] for d in documents),
                       "distinct_terms": len(term_total),
                       "distinct_acronyms": len(acro_total)}}


def report(result):
    """Plain text, for a reader planning the vocabulary."""
    t = result["totals"]
    lines = ["%d document(s), %d words, %d distinct capitalised phrases, %d acronyms"
             % (t["documents"], t["words"], t["distinct_terms"], t["distinct_acronyms"]), ""]
    lines.append("Documents:")
    for d in result["documents"]:
        dates = ("  dates: %s" % ", ".join(d["dates"][:4])) if d["dates"] else ""
        lines.append("  %-32s %6d words  %-40s%s" % (d["slug"], d["words"], d["title"][:40], dates))
        for h in d["headings"][:8]:
            lines.append("      - %s" % h[:70])
        if len(d["headings"]) > 8:
            lines.append("      ... and %d more heading(s)" % (len(d["headings"]) - 8))
    lines.append("")
    lines.append("Recurring phrases (candidates for entities; documents / mentions):")
    for r in result["terms"]:
        lines.append("  %2d / %4d  %s" % (len(r["documents"]), r["count"], r["term"]))
    if not result["terms"]:
        lines.append("  none recur")
    lines.append("")
    lines.append("Acronyms (each needs an expansion in the lexicon or an alias):")
    for r in result["acronyms"]:
        lines.append("  %2d / %4d  %s" % (len(r["documents"]), r["count"], r["term"]))
    if not result["acronyms"]:
        lines.append("  none recur")
    lines.append("")
    lines.append("A phrase here is a candidate, not a fact. Read the documents before declaring a class.")
    return "\n".join(lines)


# ---- one document, for whoever is about to draft its proposal ----

def brief(corpus_dir, slug, live, candidate=None, top=30):
    """What a drafter needs before reading one document: its shape, its recurring terms, and for
    each term whether the graph (live, or the open candidate) already holds an entity for it.

    The point is id reuse. A drafter who sees that "Claims Manager" already resolves to
    role.claims-manager lists that id; one who does not invents role.manager, and the graph has two
    nodes for one thing. Matching is by label and alias, exact before contains, and it is a hint:
    the drafter still decides.
    """
    from ..curate.session import find

    path = os.path.join(corpus_dir, slug + ".md")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    document = profile(slug, text)

    live_ids = {n.get("id") for n in (live.get("nodes") or [])}

    def matches(term):
        out = []
        for graph, where in ((candidate, "candidate"), (live, "live")):
            if graph is None:
                continue
            for node in find(graph, term)[:3]:
                if node.get("id") in {m["id"] for m in out}:
                    continue
                out.append({"id": node.get("id"), "type": node.get("type"), "label": node.get("label"),
                            "status": node.get("status", "current"),
                            "where": "candidate only" if (where == "candidate" and node.get("id") not in live_ids)
                                     else "live"})
        return out

    terms = [{"term": t, "count": n, "matches": matches(t)}
             for t, n in sorted(phrases(text).items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
    acros = [{"term": t, "count": n, "matches": matches(t)}
             for t, n in sorted(acronyms(text).items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
    return {"document": document, "terms": terms, "acronyms": acros,
            "candidate_open": candidate is not None}


def brief_report(result):
    d = result["document"]
    lines = ["%s: %s  (%d words, %d heading(s)%s)" % (
        d["slug"], d["title"], d["words"], len(d["headings"]),
        ("; dates " + ", ".join(d["dates"][:5])) if d["dates"] else "")]
    for h in d["headings"][:12]:
        lines.append("    - %s" % h[:70])
    where = "the candidate and the live graph" if result["candidate_open"] else "the live graph"
    lines += ["", "Terms in this document, and what %s already holds for them:" % where]
    for section in (result["terms"], result["acronyms"]):
        for row in section:
            if row["matches"]:
                hits = "; ".join("%s (%s%s)" % (m["id"], m["type"], ", " + m["where"] if m["where"] != "live" else "")
                                 for m in row["matches"])
                lines.append("  %3d  %-34s -> %s" % (row["count"], row["term"][:34], hits))
            else:
                lines.append("  %3d  %-34s    new: derive an id from the label if it is an entity" % (row["count"], row["term"][:34]))
    lines += ["", "Reuse a matched id. A hit is a hint, not a verdict: read the sentence before deciding."]
    return "\n".join(lines)
