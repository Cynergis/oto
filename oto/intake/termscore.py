# -*- coding: utf-8 -*-
"""Measure the survey against a gold term list, so each stage of the chain shows what it adds.

A gold term list is what a person building a vocabulary from a corpus would want the survey to
surface: classes, named entities, codes, acronyms, each with the variants that count as the same
term (`aka`). It carries its provenance like a gold question set (`bench/gold.py`): who wrote it,
of what kind, how much a person checked. JSON Lines, `_meta` first; `//` lines are ignored.

    recall       gold terms the survey surfaced, as any candidate's term, variant or expansion
    precision    candidates that are a gold term; the rest is what a reader wades through
    review load  candidates read per real term found: the cost of the list to the person using it

`ablations` runs the survey with each fix off in turn, and with all of them off (the survey this
stage replaced), so a fix that does not earn its place shows it.
"""
import json
import re

from . import survey as _survey

TERM_WORDS = re.compile(r"[a-z0-9]+(?:[-'/.][a-z0-9]+)*")


def load(path):
    """(meta, terms). Refuses a list that does not say who wrote it."""
    from ..bench import gold as _gold
    meta, terms = {}, []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                payload = json.loads(line)
            except ValueError as exc:
                raise ValueError("line %d is not valid JSON: %s" % (number, exc))
            if "_meta" in payload:
                meta = payload["_meta"]
            elif not str(payload.get("term") or "").strip():
                raise ValueError("line %d has no `term`" % number)
            else:
                terms.append(payload)
    if not meta:
        raise ValueError("no `_meta` line: a gold list with no recorded provenance cannot support a claim")
    if meta.get("authored_by_kind") not in _gold.AUTHOR_KINDS or not str(meta.get("authored_by") or "").strip():
        raise ValueError("_meta must say who wrote the list (`authored_by`) and of what kind (`authored_by_kind`: %s)"
                         % ", ".join(_gold.AUTHOR_KINDS))
    return meta, terms


def describe(meta):
    from ..bench import gold as _gold
    return _gold.describe(meta)


def normal(text):
    """A name as the scoring compares it: lowercase words, the last one singular."""
    words = TERM_WORDS.findall(str(text or "").lower())
    if words:
        words[-1] = _survey.singular(words[-1])
    return " ".join(words)


def _candidate_names(candidate):
    names = {normal(candidate["term"])} | {normal(v) for v in candidate.get("variants") or []}
    if candidate.get("expansion"):
        names.add(normal(candidate["expansion"]["text"]))
    return names - {""}


def _gold_names(entry):
    return ({normal(entry["term"])} | {normal(a) for a in entry.get("aka") or []}) - {""}


def score(result, gold):
    """{recall, precision, review_load, found, missed, noise, candidates}. A metric with nothing to
    divide by is None, never a flattering zero or one."""
    candidates = result.get("candidates") or []
    surfaced = set().union(*[_candidate_names(c) for c in candidates]) if candidates else set()
    wanted = set().union(*[_gold_names(g) for g in gold]) if gold else set()
    found = sorted(g["term"] for g in gold if _gold_names(g) & surfaced)
    missed = sorted(g["term"] for g in gold if not _gold_names(g) & surfaced)
    real = [c for c in candidates if _candidate_names(c) & wanted]
    noise = sorted(c["term"] for c in candidates if not _candidate_names(c) & wanted)
    return {"recall": len(found) / len(gold) if gold else None,
            "precision": len(real) / len(candidates) if candidates else None,
            "review_load": len(candidates) / len(found) if found else None,
            "candidates": len(candidates), "found": found, "missed": missed, "noise": noise}


def ablations(corpus_dir, gold, top=40, min_count=2):
    """[(label, score)]: every fix, each fix off in turn, and none of them."""
    rows = [("all fixes", score(_survey.survey(corpus_dir, top, min_count), gold))]
    for fix in _survey.FIXES:
        rows.append(("without %s" % fix, score(_survey.survey(corpus_dir, top, min_count, off=(fix,)), gold)))
    rows.append(("none (the survey before this stage)", score(_survey.survey(corpus_dir, top, min_count, off=_survey.FIXES), gold)))
    return rows


def _fmt(value):
    return "      -" if value is None else "%7.3f" % value


def report(meta, result, gold, rows=None, show=15):
    """The score as text: provenance first, then the numbers, then what was missed and what was noise."""
    s = score(result, gold)
    lines = [describe(meta), "",
             "%d gold term(s), %d candidate(s): recall %s, precision %s, review load %s"
             % (len(gold), s["candidates"], _fmt(s["recall"]).strip(), _fmt(s["precision"]).strip(), _fmt(s["review_load"]).strip()),
             "  recall       gold terms the survey surfaced",
             "  precision    candidates that are gold terms",
             "  review load  candidates a person reads per real term found", ""]
    lines.append("missed (%d): %s" % (len(s["missed"]), ", ".join(s["missed"][:show]) or "none"))
    lines.append("noise (%d): %s%s" % (len(s["noise"]), ", ".join(s["noise"][:show]) or "none",
                                       " ..." if len(s["noise"]) > show else ""))
    if rows:
        lines += ["", "%-38s %7s %9s %11s %10s" % ("ablation", "recall", "precision", "review load", "candidates")]
        for label, r in rows:
            lines.append("%-38s %7s %9s %11s %10d" % (label, _fmt(r["recall"]), _fmt(r["precision"]), _fmt(r["review_load"]), r["candidates"]))
        lines.append("A fix earns its place when switching it off lowers recall or precision, or raises the review load.")
    return "\n".join(lines)
