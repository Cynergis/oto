# -*- coding: utf-8 -*-
"""Deterministic scoring.

Every metric here runs without a model and without a network call, so a run is reproducible. That is
itself one of the claims being tested: a number nobody else can reproduce is an anecdote.

Answer correctness genuinely needs a judge, and a judge is not deterministic. It is kept out of this
module on purpose and handled separately, so a judge's variance can never contaminate the numbers that
are supposed to be stable.

  citation      precision, recall and F1 of the sources a system cites against the gold sources.
                Claim-level grounding: a system that cites the chunk it pulled cannot do this.
  coverage      did a gold source appear in the top k retrieved? This is recall, and it is the lane
                where a dense baseline may win. Measuring it is what keeps the comparison honest.
  entity hit    did retrieval surface the entity the question is about?
  temporal      for a time-aware question, was the status right: current, superseded, absent, changed?
  token F1      lexical overlap of a produced answer against a gold answer, when both exist.
  outcome       right, wrong or abstained: the answer a system put forward, judged strictly. A
                wrong answer is worse than none, so the summary scores right +1, abstained 0,
                wrong -1, beside precision (right among answered) and coverage (answered at all).
"""
import re
from collections import Counter


def _clean(values):
    return {v for v in (values or []) if v}


def citation_prf(cited, gold):
    """Precision, recall and F1. Returns (None, None, None) when there is nothing to grade against."""
    cited, gold = _clean(cited), _clean(gold)
    if not gold:
        return (None, None, None)
    hits = len(cited & gold)
    precision = hits / len(cited) if cited else 0.0
    recall = hits / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return (precision, recall, f1)


def coverage(retrieved, gold, k):
    """(hit, rank) — did any gold source land in the top k? Rank is 1-based, or None."""
    gold = _clean(gold)
    if not gold:
        return (None, None)
    for position, source in enumerate(list(retrieved)[:k], 1):
        if source in gold:
            return (1.0, position)
    return (0.0, None)


def entity_hit(retrieved, expected):
    expected = _clean(expected)
    if not expected:
        return None
    return 1.0 if (_clean(retrieved) & expected) else 0.0


def temporal_score(result, question):
    """Was the status right, for a time-aware question. A negative question also states `absent`, but
    it is about what the corpus says, not about time: `outcome` grades it."""
    expected = question.get("expected_status")
    if expected is None or not str(question.get("type") or "").startswith("temporal"):
        return None
    return 1.0 if result.get("answer_status") == expected else 0.0


def strict_entity(result, question):
    """Is the entity the system answered with one of the expected ones? Not a neighbour of it."""
    expected = _clean(question.get("expected_entities"))
    if not expected or result.get("answer_kind") != "entity":
        return None
    return 1.0 if result.get("resolved_entity") in expected else 0.0


def outcome(result, question):
    """"right", "wrong" or "abstained": what the system put forward as its answer, judged strictly.

    An entity system answers with the entity it bound; a passage retriever with the first source it
    surfaced. A negative question (the corpus does not say it) is answered right only by abstaining.
    A temporal question needs the right status, which a retriever with no notion of time cannot give.
    Otherwise the expected entity decides, or, when the question names none, the first source.
    """
    negative = question.get("type") == "negative"
    if result.get("abstained"):
        return "right" if negative else "abstained"
    if negative:
        return "wrong"
    entity_answer = result.get("answer_kind") == "entity"
    expected_entities = _clean(question.get("expected_entities"))
    if question.get("expected_status") and str(question.get("type") or "").startswith("temporal"):
        if result.get("answer_status") != question["expected_status"]:
            return "wrong"
        if not expected_entities:
            return "right"
        return "right" if entity_answer and result.get("resolved_entity") in expected_entities else "wrong"
    if expected_entities and entity_answer:
        return "right" if result.get("resolved_entity") in expected_entities else "wrong"
    first = next(iter(result.get("surfaced_sources") or []), None)
    return "right" if first in _clean(question.get("supporting_sources")) else "wrong"


def token_f1(predicted, gold):
    if not predicted or not gold:
        return None
    tokens = lambda s: re.findall(r"[a-z0-9]+", s.lower())
    p, g = tokens(predicted), tokens(gold)
    if not p or not g:
        return 0.0
    overlap = sum((Counter(p) & Counter(g)).values())
    if not overlap:
        return 0.0
    precision, recall = overlap / len(p), overlap / len(g)
    return 2 * precision * recall / (precision + recall)


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
