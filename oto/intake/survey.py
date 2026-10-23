# -*- coding: utf-8 -*-
"""Survey the corpus, so the vocabulary and the graph start from what the documents actually say.

Designing a vocabulary starts with the words the material uses, and authoring a graph starts with
the things the material names. Reading every document is still required. This pass gives the reader
a map before the reading: what each document is, how it is structured, which phrases, codes and
acronyms recur across documents, and which dates are mentioned.

It is deliberately dumb. No model, no dictionary of the domain, no inference: a recurring phrase is a
*candidate* for an entity, and a person or an agent decides. Everything here is a count, so two runs
over the same corpus agree.

The result is a list of candidates, each with the evidence that put it there: its counts, the
documents it is in, a quote from each, its variants. This is the first stage of a chain (`counted`);
later stages may add to a candidate, never rewrite what this one counted. Each fix below is named in
FIXES and can be switched off, so `termscore` can show what each one is worth against a gold list:

    header       OTO's own lines (the intake's provenance line, a capture's header) are not the corpus
    paragraphs   a name never runs across a blank line or out of a heading into the text below it
    boilerplate  a sentence repeated word for word in two or more documents is a template, not content
    codes        PM-B, WO-2291, BRK-221 are one identifier each, not an acronym plus a phrase
    acronyms     an all-capitals word is counted once, as an acronym, not also as a phrase
    plurals      Work Order and Work Orders are one candidate (case variants always are)
    lowercase    "error budget" recurring across documents is a term too
    expansions   "Mean Time To Recovery (MTTR)" gives MTTR its expansion, quoted, and one row

Each was kept because switching it off lowers recall or precision, or raises the review load, on
the gold lists of two unrelated corpora (tests/fixtures/survey). One that showed nothing, dropping a
sentence opener such as "Every" from the name after it, was left out for that reason.
"""
import os
import re
from collections import Counter, defaultdict

#: A run of capitalised words, allowing the small connectors a name may carry ("Notice of Loss").
PHRASE = re.compile(r"\b[A-Z][A-Za-z0-9&'\-]+(?:(?:\s+(?:of|and|for|the|de|du|des|von|van|di|da))?"
                    r"\s+(?:[A-Z][A-Za-z0-9&'\-]+|\d[A-Za-z0-9\-]*)){0,4}\b")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,6}\b")
#: An identifier: capitals or digits, a hyphen, then more ("PM-B", "WO-2291", "SEV-1").
CODE = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]*-[A-Z0-9][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*(?![\w-])")
ISO_DATE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*$")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")
#: The lines OTO writes itself: the intake's provenance line, and a captured note's header.
PROVENANCE_LINE = re.compile(r"^> \*\*(?:Source|Captured):\*\*.*$", re.M)
#: The least a repeated sentence must say before it counts as a template rather than a coincidence.
BOILERPLATE_WORDS = 6
#: Characters before a single capitalised word that mean "start of a sentence", where the capital
#: says nothing about the word. Multi-word phrases are kept regardless: "Claims Adjuster" at the
#: start of a sentence is still a name.
SENTENCE_START = set(".!?:\n#*-|>\"'(`")
STOP = set("the a an and or of to in on for with by as at is are be this that these those it its "
           "from into we you they our your their if then than when where how what which who not no "
           "all any each per via may can will shall must should".split())
CONNECTORS = {"of", "and", "for", "the", "to", "in", "on", "a", "an"}
FIXES = ("header", "paragraphs", "boilerplate", "codes", "acronyms", "plurals", "lowercase", "expansions")
STAGE = "counted"
QUOTES = 2


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
        before = text[:m.start()].rstrip(" \t")
        at_start = not before or before[-1] in SENTENCE_START
        # "The Fraud Unit" at the start of a sentence: the article is grammar, the rest is a name.
        tokens = phrase.split(" ")
        while len(tokens) > 1 and tokens[0].lower() in STOP:
            tokens.pop(0)
        phrase = " ".join(tokens)
        if single:
            if phrase.lower() in STOP or len(phrase) < 3:
                continue
            if at_start:
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


def codes(text):
    return Counter(m.group(0) for m in CODE.finditer(_clean(text)))


def lowercase_terms(text):
    """Two- and three-word runs of lowercase words, none of them a stop word, inside one clause."""
    counts = Counter()
    for clause in re.split(r"[.,;:!?()\[\]\n|*>\"`]+", _clean(text)):
        words = WORD.findall(clause)
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                window = words[i:i + size]
                if all(w[0].islower() and len(w) > 2 and w.lower() not in STOP for w in window):
                    counts[" ".join(window)] += 1
    return counts


def singular(word):
    """A plural's singular, by the regular rules only: what is left is still a variant, never a guess."""
    lower = word.lower()
    if len(word) > 4 and lower.endswith("ies"):
        return word[:-3] + ("Y" if word[-3].isupper() else "y")
    if lower.endswith(("sses", "ches", "shes", "xes", "uses")):
        return word[:-2]
    if len(word) > 3 and lower.endswith("s") and not lower.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _key(phrase, plurals):
    words = phrase.lower().split()
    if plurals and words:
        words[-1] = singular(words[-1])
    return " ".join(words)


def expansions(text):
    """{acronym: (long form, the sentence it is defined in)} for "Long Form (LF)" and "LF (long form)"."""
    found = {}
    text = _clean(text)
    for sentence in _sentences(text):
        for m in re.finditer(r"\(([A-Z][A-Z0-9]{1,6})\)", sentence):
            words = WORD.findall(sentence[:m.start()])
            for size in range(1, min(len(words), 8) + 1):
                if _initials_match(m.group(1), words[-size:]):
                    found.setdefault(m.group(1), (" ".join(words[-size:]), sentence))
                    break
        for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,6})\s*\(([^)]{3,80})\)", sentence):
            words = WORD.findall(m.group(2))
            if _initials_match(m.group(1), words):
                found.setdefault(m.group(1), (" ".join(words), sentence))
    return found


def _initials_match(acronym, words):
    letters = [c.lower() for c in acronym if c.isalpha()]
    every = [w[0].lower() for w in words]
    content = [w[0].lower() for w in words if w.lower() not in CONNECTORS]
    return bool(words) and words[0].lower() not in CONNECTORS and letters in (every, content)


def _sentences(text):
    return [s.strip(" -*#>\t") for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip(" -*#>\t")]


def _quote(sentences, forms):
    pattern = re.compile(r"(?<![\w-])(?:%s)(?![\w-])" % "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)),
                         re.IGNORECASE)
    for sentence in sentences:
        if pattern.search(sentence):
            return sentence[:240]
    return None


def _paragraphs(text):
    """End every heading and every paragraph with a stop, so a name cannot run across either."""
    text = re.sub(r"^(#{1,6}[ \t].*)$", r"\1 .", text, flags=re.M)
    return re.sub(r"\n[ \t]*\n+", "\n.\n", text)


def _boilerplate(docs):
    """Sentences that appear word for word in two or more documents and say enough to be a template."""
    seen = Counter()
    for _slug, text in docs:
        seen.update(set(_sentences(_clean(text))))
    return {s for s, n in seen.items() if n > 1 and len(WORD.findall(s)) >= BOILERPLATE_WORDS}


def _read(corpus_dir, on):
    """The corpus as the survey reads it: OTO's own lines gone, and the templates it repeats."""
    docs = [(slug, PROVENANCE_LINE.sub("", text) if on["header"] else text) for slug, text in read_corpus(corpus_dir)]
    return docs, (_boilerplate(docs) if on["boilerplate"] else set())


def _count(slug, text, template, on, forms, defined):
    """One document's forms, counted into `forms` per (kind, surface), with the fixes in `on` applied."""
    if on["expansions"]:
        for acronym, (long_form, quote) in expansions(text).items():
            defined.setdefault(acronym, {"text": long_form, "doc": slug, "quote": quote[:240]})
    body = _clean(text)
    for sentence in template:
        body = body.replace(sentence, " . ")
    if on["paragraphs"]:
        body = _paragraphs(body)
    if on["codes"]:
        for code, n in codes(body).items():
            forms[("code", code)][slug] += n
        body = CODE.sub(" , ", body)
    for phrase, n in phrases(body).items():
        if on["acronyms"] and " " not in phrase and ACRONYM.fullmatch(phrase):
            continue                              # counted as an acronym below, not twice
        forms[("phrase", phrase)][slug] += n
    if on["lowercase"]:
        for phrase, n in lowercase_terms(body).items():
            forms[("lower", phrase)][slug] += n
    for token, n in acronyms(body).items():
        forms[("acronym", token)][slug] += n


def _group(forms, defined, on):
    """Forms of one candidate gathered under one key: case and plural variants, and an acronym with
    its expansion."""
    groups = defaultdict(lambda: {"forms": Counter(), "docs": Counter(), "kinds": set()})
    for (kind, surface), per_doc in forms.items():
        key = (kind if kind in ("code", "acronym") else "phrase",
               surface if kind in ("code", "acronym") else _key(surface, on["plurals"]))
        group = groups[key]
        group["forms"][surface] += sum(per_doc.values())
        group["docs"].update(per_doc)
        group["kinds"].add(kind)
    for acronym, expansion in defined.items():
        target = groups.get(("acronym", acronym))
        source = groups.pop(("phrase", _key(expansion["text"], on["plurals"])), None)
        if target is not None and source is not None:
            target["forms"].update(source["forms"])
            target["docs"].update(source["docs"])
    return groups


def _term(kind, normal, group):
    """The form a candidate is listed under: an acronym as written, else its most frequent capitalised form."""
    if kind == "acronym":
        return normal
    return sorted(group["forms"], key=lambda f: (not f[:1].isupper(), -group["forms"][f], len(f), f))[0]


def survey(corpus_dir, top=40, min_count=2, off=()):
    """The whole map: documents, and candidates with their evidence. `top` limits each kind; a
    candidate must occur `min_count` times. `off` names FIXES to leave out (all of them is the
    survey this stage replaced)."""
    on = {fix: fix not in off for fix in FIXES}
    docs, template = _read(corpus_dir, on)
    documents, forms, sentences, defined = [], defaultdict(Counter), {}, {}
    for slug, text in docs:
        documents.append(profile(slug, text))
        sentences[slug] = _sentences(_clean(text))
        _count(slug, text, template, on, forms, defined)
    groups = _group(forms, defined, on)

    candidates = {"phrase": [], "code": [], "acronym": []}
    for (kind, normal), group in groups.items():
        total = sum(group["forms"].values())
        if total < min_count:
            continue
        if group["kinds"] == {"lower"} and len(group["docs"]) < 2:
            continue                                  # a lowercase run in one document is prose, not yet a term
        term = _term(kind, normal, group)
        documents_in = sorted(group["docs"])
        quotes = []
        for slug in documents_in:
            text = _quote(sentences[slug], list(group["forms"]))
            if text and len(quotes) < QUOTES:
                quotes.append({"doc": slug, "text": text})
        candidate = {"term": term, "kind": kind, "count": total, "documents": documents_in,
                     "variants": sorted(f for f in group["forms"] if f != term), "quotes": quotes,
                     "evidence": STAGE, "stage": STAGE, "via": []}
        if kind == "acronym" and term in defined:
            candidate["expansion"] = defined[term]
        # Which fixes brought or shaped it, so a person's verdicts can be counted per fix.
        if kind == "code":
            candidate["via"].append("codes")
        if kind == "phrase" and group["kinds"] == {"lower"}:
            candidate["via"].append("lowercase")
        if kind == "phrase" and any(f.lower() != term.lower() for f in group["forms"]):
            candidate["via"].append("plurals")
        if candidate.get("expansion"):
            candidate["via"].append("expansions")
        candidates[kind].append(candidate)

    def ranked(rows):
        return sorted(rows, key=lambda r: (-len(r["documents"]), -r["count"], r["term"]))[:top]

    terms, code_rows, acronym_rows = ranked(candidates["phrase"]), ranked(candidates["code"]), ranked(candidates["acronym"])
    return {"documents": documents,
            "candidates": terms + code_rows + acronym_rows,
            "terms": terms, "codes": code_rows, "acronyms": acronym_rows,
            "stage": STAGE, "fixes": [fix for fix in FIXES if on[fix]],
            "totals": {"documents": len(documents),
                       "words": sum(d["words"] for d in documents),
                       "distinct_terms": sum(1 for k in groups if k[0] == "phrase"),
                       "distinct_codes": sum(1 for k in groups if k[0] == "code"),
                       "distinct_acronyms": sum(1 for k in groups if k[0] == "acronym")}}


def report(result):
    """Plain text, for a reader planning the vocabulary."""
    t = result["totals"]
    lines = ["%d document(s), %d words, %d distinct phrases, %d codes, %d acronyms"
             % (t["documents"], t["words"], t["distinct_terms"], t.get("distinct_codes", 0), t["distinct_acronyms"]), ""]
    lines.append("Documents:")
    for d in result["documents"]:
        dates = ("  dates: %s" % ", ".join(d["dates"][:4])) if d["dates"] else ""
        lines.append("  %-32s %6d words  %-40s%s" % (d["slug"], d["words"], d["title"][:40], dates))
        for h in d["headings"][:8]:
            lines.append("      - %s" % h[:70])
        if len(d["headings"]) > 8:
            lines.append("      ... and %d more heading(s)" % (len(d["headings"]) - 8))
    lines += ["", "Candidates, counted and quoted in the corpus (stage: %s; fixes: %s)"
              % (result.get("stage", STAGE), ", ".join(result.get("fixes", FIXES)) or "none"), ""]

    def section(title, rows, extra=lambda r: ""):
        lines.append(title)
        for r in rows:
            also = ("   also: " + ", ".join(r.get("variants", [])[:4])) if r.get("variants") else ""
            decided = ("  [accepted by %s]" % r["decision"]["by"]) if (r.get("decision") or {}).get("verdict") == "accepted" else ""
            lines.append("  %2d / %4d  %s%s%s%s" % (len(r["documents"]), r["count"], r["term"], decided, extra(r), also))
        if not rows:
            lines.append("  none recur")
        lines.append("")

    section("Recurring phrases (candidates for entities; documents / mentions):", result["terms"])
    section("Codes (identifiers, usually one entity each):", result.get("codes", []))
    section("Acronyms (each needs an expansion in the lexicon or an alias):", result["acronyms"],
            lambda r: ("  = %s  (defined in %s)" % (r["expansion"]["text"], r["expansion"]["doc"])) if r.get("expansion") else "")
    if result.get("rejected"):
        lines.append("%d candidate(s) rejected by a person are not listed (oto survey decisions shows them)."
                     % len(result["rejected"]))
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
    # The survey's own candidate stage and fixes, so the brief lists what `oto survey` would count
    # in this document: no capture header, no headings run into text, codes whole.
    on = {fix: True for fix in FIXES}
    docs, template = _read(corpus_dir, on)
    text = dict(docs)[slug]
    document = profile(slug, text)
    forms, defined = defaultdict(Counter), {}
    _count(slug, text, template, on, forms, defined)
    found = {"phrase": [], "code": [], "acronym": []}
    for (kind, normal), group in _group(forms, defined, on).items():
        if group["kinds"] == {"lower"}:
            continue                                  # a lowercase run in one document is prose, not yet a term
        found[kind].append((_term(kind, normal, group), sum(group["forms"].values())))

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

    def rows(kind):
        return [{"term": t, "count": n, "matches": matches(t)}
                for t, n in sorted(found[kind], key=lambda kv: (-kv[1], kv[0]))[:top]]

    return {"document": document, "terms": rows("phrase"), "codes": rows("code"), "acronyms": rows("acronym"),
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
    for section in (result["terms"], result.get("codes", []), result["acronyms"]):
        for row in section:
            if row["matches"]:
                hits = "; ".join("%s (%s%s)" % (m["id"], m["type"], ", " + m["where"] if m["where"] != "live" else "")
                                 for m in row["matches"])
                lines.append("  %3d  %-34s -> %s" % (row["count"], row["term"][:34], hits))
            else:
                lines.append("  %3d  %-34s    new: derive an id from the label if it is an entity" % (row["count"], row["term"][:34]))
    lines += ["", "Reuse a matched id. A hit is a hint, not a verdict: read the sentence before deciding."]
    return "\n".join(lines)
