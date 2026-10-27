# -*- coding: utf-8 -*-
"""The lexicon as a person searches it (roadmap D3): every term of the vocabulary with its label,
alternative labels and definition in every language the project declares, the words people use
(lexicon.json) with the entity each one means, and a search over all of it where each hit says which
element it lands on: a class page of the ontology, the class that carries a relation or an attribute,
or an entity of the knowledge base. Carried in the graph payload as `terms` and served at
/api/lexicon (`?q=<words>` for the hits).

A term: kind (class | relation | attribute | temporal | scheme | concept), name, owner (the class of an
attribute, the scheme of a concept), labels and definition as {language: text} (the default language
always present, read from the name when nothing is written), alt_labels as {language: [texts]},
target ({section: "ontology", class, [relation | attribute | scheme]}). A phrase: phrase, canonical,
status, note, target (an entity id or None), label and type of that entity.
"""
from ..model import vocabulary as _vocab


def _words(name):
    """A name as words; an acronym stays as it is written."""
    return name if name.isupper() else _vocab.name_as_words(name)


def _labels(spec, name, languages):
    default = languages[0]
    found = _vocab.texts((spec or {}).get("label"), default)
    if default not in found:
        found[default] = _words(name)
    return {lang: found[lang] for lang in list(languages) + sorted(set(found) - set(languages)) if lang in found}


def _texts(value, languages):
    found = _vocab.texts(value, languages[0])
    return {lang: found[lang] for lang in list(languages) + sorted(set(found) - set(languages)) if lang in found}


def _holder(attributes, scheme):
    for owner, declared in (attributes or {}).items():
        for name, spec in (declared or {}).items():
            if (spec or {}).get("type") == "scheme:" + scheme:
                return owner, name
    return None, None


def model(vocabulary, lexicon_rows=(), nodes=()):
    """The terms and the phrases, with the languages they are written in."""
    vocabulary = vocabulary or {}
    languages = [x for x in (vocabulary.get("languages") or []) if isinstance(x, str) and x] or [_vocab.DEFAULT_LANGUAGE]
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}
    attributes = vocabulary.get("attributes") or {}
    schemes = vocabulary.get("schemes") or {}
    terms = []

    def term(kind, name, owner, spec, target):
        spec = spec or {}
        terms.append({"kind": kind, "name": name, "owner": owner, "labels": _labels(spec, name, languages),
                      "alt_labels": _vocab.alt_labels(spec.get("alt_labels"), languages[0]),
                      "definition": _texts(spec.get("definition"), languages), "target": target})

    for name, spec in classes.items():
        term("class", name, None, spec, {"section": "ontology", "class": name})
    for name, spec in properties.items():
        domain = list(_vocab._union((spec or {}).get("domain")))
        term("relation", name, None, spec, {"section": "ontology", "class": domain[0] if domain else None, "relation": name})
    for owner, declared in attributes.items():
        for name, spec in (declared or {}).items():
            term("attribute", name, owner, spec, {"section": "ontology", "class": owner, "attribute": name})
    for name, spec in (vocabulary.get("temporal") or {}).items():
        term("temporal", name, None, spec, {"section": "ontology", "class": None})
    for scheme, spec in schemes.items():
        owner, attribute = _holder(attributes, scheme)
        target = {"section": "ontology", "class": owner, "attribute": attribute} if owner else {"section": "ontology", "class": None, "scheme": scheme}
        term("scheme", scheme, None, spec, target)
        for key, concept in ((spec or {}).get("concepts") or {}).items():
            term("concept", key, scheme, concept, dict(target))

    by_id = {n["id"]: n for n in nodes or []}
    phrases = []
    for row in lexicon_rows or []:
        target = row.get("target") or None
        node = by_id.get(target) if target else None
        phrases.append({"phrase": row.get("phrase") or "", "canonical": row.get("canonical") or row.get("phrase") or "",
                        "status": row.get("status") or "current", "note": row.get("note") or "", "target": target,
                        "label": node.get("label") if node else None, "type": node.get("type") if node else None})
    phrases.sort(key=lambda p: (p["phrase"], p["canonical"], p["target"] or ""))
    return {"languages": languages, "default_language": languages[0], "terms": terms, "phrases": phrases,
            "counts": {"terms": len(terms), "phrases": len(phrases), "languages": len(languages)}}


def _score(wanted, text):
    text = (text or "").lower()
    if not text:
        return 0
    if text == wanted:
        return 3
    if text.startswith(wanted):
        return 2
    if wanted in text:
        return 1
    return 0


def search(m, query):
    """The elements the words name, best match first: a term by label, alternative label or name in
    any language, or a phrase people use. Each hit carries where it lands."""
    wanted = " ".join(str(query or "").split()).lower()
    if not wanted:
        return []
    hits = []
    for t in m.get("terms") or []:
        candidates = [(lang, text, "label") for lang, text in t["labels"].items()]
        candidates += [(lang, text, "alt_label") for lang, items in t["alt_labels"].items() for text in items]
        candidates += [(None, t["name"], "name"), (None, _words(t["name"]), "name")]
        best = None
        for lang, text, how in candidates:
            score = _score(wanted, text)
            if score and (best is None or score > best[0]):
                best = (score, {"language": lang, "text": text, "how": how})
        if best:
            hits.append((best[0], {"kind": t["kind"], "name": t["name"], "owner": t["owner"], "label": t["labels"][m["default_language"]],
                                   "labels": t["labels"], "target": t["target"], "match": best[1]}))
    for p in m.get("phrases") or []:
        score = max(_score(wanted, p["phrase"]), _score(wanted, p["canonical"]))
        if score:
            text = p["phrase"] if _score(wanted, p["phrase"]) >= _score(wanted, p["canonical"]) else p["canonical"]
            target = {"section": "knowledge", "entity": p["target"]} if p["target"] else None
            hits.append((score, {"kind": "phrase", "name": p["phrase"], "owner": None, "label": p["label"], "labels": {},
                                 "canonical": p["canonical"], "type": p["type"], "status": p["status"], "note": p["note"],
                                 "target": target, "match": {"language": None, "text": text, "how": "phrase"}}))
    hits.sort(key=lambda h: (-h[0], len(h[1]["match"]["text"]), h[1]["name"].lower()))
    return [h for _s, h in hits]
