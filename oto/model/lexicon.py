# -*- coding: utf-8 -*-
"""The lexicon: the words people use, mapped to the entities they mean. A person writes it.

A name the graph does not know makes a lookup answer "nothing matched", which is right, and leaves the
reader to rephrase. The lexicon closes that gap deterministically: "depot" resolves to the garage it
means for every reader and every model, because someone said so once. An embedding model is good at
noticing which entity a word probably means and bad at being accountable for it, so it only
proposes:

    suggest   embed the words (given, or recurring in the corpus with no name in the graph) and each
              current entity; propose the nearest when it clears a similarity floor AND leads the
              runner-up by a margin, into `lexicon.suggestions.json`. Nothing it writes is read by the
              build. A word close to two entities is listed as unclear, with both, for a person.

Measured on a small fleet-maintenance graph with BAAI/bge-small-en-v1.5, similarity alone did not
separate right from wrong: "rear pads" scored 0.77 for the FRONT pads and 0.76 for the rear ones, and
words the graph does not hold at all ("driver", "invoice") scored 0.59-0.61, as high as a right match
(0.66). Every wrong or doubtful one was within 0.04 of its runner-up; the right one led by 0.06. Hence
the margin, and hence a person: the defaults are a starting point from one corpus, not a calibration.
    accept    a named person takes one suggestion, or names a target, into `lexicon.json`, dated and
              attributed. The next build carries it and every lookup binds it.
    reject    a named person refuses one; it is not proposed again.
"""
import datetime
import json
import os
import re

NAME = "lexicon.json"
SUGGESTIONS = "lexicon.suggestions.json"
DEFAULT_MIN_SIMILARITY = 0.60
DEFAULT_MIN_MARGIN = 0.05
#: The line the intake writes at the top of every extracted document. Its words are the pipeline's,
#: not the corpus's, and would otherwise be proposed as terms ("Converted", "Markdown").
PROVENANCE_LINE = re.compile(r"^> \*\*Source:\*\*.*$", re.M)


def _today():
    return datetime.date.today().isoformat()


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, payload):
    """Serialise first, then replace: a payload that cannot be written leaves the old file intact."""
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def load(project):
    """The lexicon as authored: {"entries": [...]}."""
    data = _read(os.path.join(project.data, NAME), {})
    return dict(data, entries=list(data.get("entries") or []))


def _queue(project):
    data = _read(os.path.join(project.data, SUGGESTIONS), {})
    return {"suggestions": list(data.get("suggestions") or []), "rejected": list(data.get("rejected") or []),
            "model": data.get("model"), "min_similarity": data.get("min_similarity")}


def _save_queue(project, queue):
    _write(os.path.join(project.data, SUGGESTIONS), {
        "_about": "Proposed lexicon entries, from an embedding model: NOT read by the build. `oto lexicon "
                  "accept --term <t> --by <you>` takes one into lexicon.json; `reject` refuses it.",
        "model": queue.get("model"), "min_similarity": queue.get("min_similarity"),
        "suggestions": queue["suggestions"], "rejected": queue["rejected"]})


def pending(project):
    """The suggestions waiting for a person."""
    return _queue(project)["suggestions"]


def _graph(project):
    with open(project.graph_path, encoding="utf-8") as f:
        return json.load(f)


def _names(graph, lexicon):
    """Every name a lookup already binds, lowercased: labels, aliases, lexicon phrases."""
    names = set()
    for node in graph.get("nodes") or []:
        names.add(str(node.get("label") or "").strip().lower())
        names.update(str(a).strip().lower() for a in node.get("aliases") or [])
    for entry in lexicon["entries"]:
        names.add(str(entry.get("term") or "").strip().lower())
        names.update(str(a).strip().lower() for a in entry.get("aka") or [])
    names.discard("")
    return names


def corpus_terms(project, top=40, min_count=2):
    """[(term, [documents])]: recurring phrases and acronyms of the corpus, as the survey finds them,
    with the intake's provenance line left out."""
    from ..intake import survey as _survey
    totals, where = {}, {}
    for slug, text in _survey.read_corpus(project.layout.corpus):
        text = PROVENANCE_LINE.sub("", text)
        for counter in (_survey.phrases(text), _survey.acronyms(text)):
            for term, count in counter.items():
                totals[term] = totals.get(term, 0) + count
                where.setdefault(term, set()).add(slug)
    ranked = sorted((t for t, n in totals.items() if n >= min_count), key=lambda t: (-len(where[t]), -totals[t], t))
    return [(t, sorted(where[t])) for t in ranked[:top]]


def default_embed(texts):
    """The bench's embedding model, so the lexicon and the dense baseline mean the same thing by close."""
    from ..bench import dense as _dense
    usable, reason = _dense.available()
    if not usable:
        raise RuntimeError("suggestions need an embedding model: %s" % reason)
    from fastembed import TextEmbedding
    return [list(v) for v in TextEmbedding(model_name=_dense.MODEL_NAME).embed(list(texts))]


def _unit(vector):
    """Plain floats, normalised: a model's float32 would not survive being written as JSON."""
    vector = [float(x) for x in vector]
    norm = sum(x * x for x in vector) ** 0.5 or 1.0
    return [x / norm for x in vector]


def _describe(node):
    """What an entity is, in words an embedding can compare a term with."""
    parts = ["%s (%s)" % (node.get("label") or node["id"], node.get("type") or "")]
    if node.get("aliases"):
        parts.append(", ".join(str(a) for a in node["aliases"]))
    if node.get("summary"):
        parts.append(str(node["summary"]))
    return ". ".join(parts)


def suggest(project, terms=None, embed=None, min_similarity=DEFAULT_MIN_SIMILARITY, min_margin=DEFAULT_MIN_MARGIN,
            top=40, model=None):
    """Propose a target for each term no name binds yet. Returns {"suggestions", "unclear", "known",
    "unmatched", "rejected"} and writes the suggestions, never the lexicon."""
    graph, lexicon, queue = _graph(project), load(project), _queue(project)
    names = _names(graph, lexicon)
    refused = {(r["term"].lower(), r.get("target")) for r in queue["rejected"]}
    if terms is None:
        candidates = corpus_terms(project, top=top)
    else:
        candidates = [(t.strip(), []) for t in terms if t and t.strip()]
    known = [t for t, _ in candidates if t.lower() in names]
    candidates = [(t, seen) for t, seen in candidates if t.lower() not in names]
    # A word that names a class or a relation is the vocabulary's (kg_define answers it), and a
    # document's own title names the document: neither is another name for an entity.
    from ..intake import survey as _survey
    from .terms import Vocabulary
    words = Vocabulary.of_project(project)
    titles = {_survey.profile(slug, text)["title"].lower() for slug, text in _survey.read_corpus(project.layout.corpus)}
    vocabulary = [t for t, _ in candidates if words.find(t)]
    documents = [t for t, _ in candidates if t.lower() in titles and t not in vocabulary]
    candidates = [(t, seen) for t, seen in candidates if t not in vocabulary and t not in documents]
    entities = [n for n in graph.get("nodes") or [] if n.get("status", "current") == "current"]
    out = {"suggestions": [], "unclear": [], "known": known, "vocabulary": vocabulary, "documents": documents,
           "unmatched": [], "rejected": []}
    if not candidates or not entities:
        out["unmatched"] = [t for t, _ in candidates]
        queue["suggestions"] = []
        _save_queue(project, queue)
        return out
    vectors = [_unit(v) for v in (embed or default_embed)([t for t, _ in candidates] + [_describe(n) for n in entities])]
    term_vectors, entity_vectors = vectors[:len(candidates)], vectors[len(candidates):]
    for (term, seen), tv in zip(candidates, term_vectors):
        scored = sorted(((sum(a * b for a, b in zip(tv, ev)), node) for ev, node in zip(entity_vectors, entities)),
                        key=lambda pair: (-pair[0], pair[1]["id"]))
        best_score, best = scored[0]
        if best_score < min_similarity:
            out["unmatched"].append(term)
            continue
        if (term.lower(), best["id"]) in refused:
            out["rejected"].append(term)
            continue
        runner_score, runner = scored[1] if len(scored) > 1 else (None, None)
        if runner is not None and best_score - runner_score < min_margin:
            out["unclear"].append({"term": term, "seen_in": seen, "candidates": [
                {"target": node["id"], "target_label": node.get("label"), "similarity": round(score, 4)}
                for score, node in scored[:2]]})
            continue
        suggestion = {"term": term, "target": best["id"], "target_label": best.get("label"),
                      "similarity": round(best_score, 4), "seen_in": seen}
        if runner is not None:
            suggestion["runner_up"] = {"target": runner["id"], "target_label": runner.get("label"),
                                       "similarity": round(runner_score, 4)}
        out["suggestions"].append(suggestion)
    queue.update(suggestions=out["suggestions"], model=model, min_similarity=min_similarity)
    _save_queue(project, queue)
    return out


def _take(queue, term):
    for index, suggestion in enumerate(queue["suggestions"]):
        if suggestion["term"].lower() == term.lower():
            return queue["suggestions"].pop(index)
    return None


def accept(project, term, by, target=None, at=None):
    """Write one entry into the lexicon, attributed and dated. The suggestion's target unless `target`
    names another. Returns the entry."""
    term = str(term or "").strip()
    if not str(by or "").strip():
        raise ValueError("accept needs --by: an entry nobody vouches for is a guess with a timestamp")
    if not term:
        raise ValueError("accept needs --term")
    queue = _queue(project)
    suggestion = _take(queue, term)
    chosen = target or (suggestion or {}).get("target")
    if not chosen:
        raise ValueError("no suggestion for %r: run `oto lexicon suggest`, or give --target" % term)
    ids = {n["id"] for n in _graph(project).get("nodes") or []}
    if chosen not in ids:
        raise ValueError("%r is not in the graph: a lexicon entry must point at an entity" % chosen)
    lexicon = load(project)
    for entry in lexicon["entries"]:
        if str(entry.get("term") or "").lower() == term.lower():
            if chosen in (entry.get("targets") or []):
                return entry
            raise ValueError("%r already maps to %s; change that entry by hand if it is wrong"
                             % (term, ", ".join(entry.get("targets") or []) or "nothing"))
    note = "accepted by %s on %s" % (by.strip(), at or _today())
    if suggestion and suggestion.get("target") == chosen:
        note += " from a suggestion (similarity %.2f%s)" % (suggestion["similarity"],
                                                           ", model %s" % queue["model"] if queue.get("model") else "")
    entry = {"term": term, "aka": [], "targets": [chosen], "status": "current", "note": note}
    lexicon["entries"].append(entry)
    _write(os.path.join(project.data, NAME), lexicon)
    _save_queue(project, queue)
    return entry


def reject(project, term, by, target=None, at=None):
    """Refuse a suggestion, so it is not proposed again. Returns the record."""
    if not str(by or "").strip():
        raise ValueError("reject needs --by")
    queue = _queue(project)
    suggestion = _take(queue, term)
    chosen = target or (suggestion or {}).get("target")
    if not chosen:
        raise ValueError("no suggestion for %r to reject" % term)
    record = {"term": str(term).strip(), "target": chosen, "by": by.strip(), "at": at or _today()}
    queue["rejected"].append(record)
    _save_queue(project, queue)
    return record
