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
    expected = question.get("expected_status")
    if expected is None:
        return None
    return 1.0 if result.get("answer_status") == expected else 0.0


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
