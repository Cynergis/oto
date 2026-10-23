# -*- coding: utf-8 -*-
"""Run the gold set through every system and report.

The report leads with where the questions came from, not with the numbers. A number quoted without
that context is not evidence, and the context is the first thing lost when a table gets pasted into a
deck.

It also prints threats to validity every time. They do not go away because a run went well, and a
report that omits them is making a stronger claim than the data supports.
"""
import time

from . import gold as _gold, metrics


def run(database, questions, systems, k=5):
    """Every (system, question) result, with its scores attached."""
    rows = []
    for system in systems:
        for question in questions:
            started = time.perf_counter()
            result = system.answer(question)
            elapsed_ms = (time.perf_counter() - started) * 1000.0

            precision, recall, f1 = metrics.citation_prf(
                result.get("cited_sources"), question.get("supporting_sources"))
            hit, rank = metrics.coverage(
                result.get("retrieved_sources"), question.get("supporting_sources"), k)
            # The same metric over what the system actually put in front of the answer. For a passage
            # retriever the two lists are identical, so this adds a column without moving anyone's
            # goalposts. For an entity-first system they differ, and reporting only the first would
            # mark it wrong on questions it answered correctly.
            surfaced_hit, surfaced_rank = metrics.coverage(
                result.get("surfaced_sources") or result.get("retrieved_sources"),
                question.get("supporting_sources"), k)
            rows.append({
                "system": system.name,
                "qid": question.get("id"),
                "type": question.get("type") or "factual",
                "citation_p": precision, "citation_r": recall, "citation_f1": f1,
                "coverage": hit, "coverage_rank": rank,
                "surfaced_coverage": surfaced_hit, "surfaced_rank": surfaced_rank,
                "entity_hit": metrics.entity_hit(result.get("retrieved_entities"),
                                                 question.get("expected_entities")),
                "temporal": metrics.temporal_score(result, question),
                "token_f1": metrics.token_f1(result.get("answer"), question.get("answer")),
                "latency_ms": elapsed_ms,
                "outcome": metrics.outcome(result, question),
                "strict_entity": metrics.strict_entity(result, question),
                "match": result.get("match"),
                "confidence": result.get("confidence"),
                "negative": question.get("type") == "negative",
            })
    return rows


def answers(rows):
    """Per system: right, wrong, abstained, and what they add up to. `score` is right +1, abstained 0,
    wrong -1 over every question, so answering everything only pays when the answers are right."""
    out = {}
    for row in rows:
        bucket = out.setdefault(row["system"], {"right": 0, "wrong": 0, "abstained": 0, "strict": []})
        if row.get("outcome") in ("right", "wrong", "abstained"):
            bucket[row["outcome"]] += 1
        bucket["strict"].append(row.get("strict_entity"))
    for bucket in out.values():
        answered = bucket["right"] + bucket["wrong"]
        total = answered + bucket["abstained"]
        bucket["precision"] = bucket["right"] / answered if answered else None
        bucket["coverage"] = answered / total if total else None
        bucket["score"] = (bucket["right"] - bucket["wrong"]) / total if total else None
        bucket["strict_entity"] = metrics.mean(bucket.pop("strict"))
    return out


def _with_cutoff(row, cutoff):
    """The outcome had the system abstained below `cutoff`: a question it would have dropped is right
    when the corpus does not answer it, and abstained otherwise."""
    confidence = row.get("confidence")
    if confidence is None or confidence >= cutoff or row.get("outcome") == "abstained":
        return row["outcome"]
    return "right" if row.get("negative") else "abstained"


def sweep(rows, cutoffs):
    """A system that reports a confidence, regraded at each cutoff without running it again."""
    out = []
    for cutoff in cutoffs:
        regraded = [dict(row, outcome=_with_cutoff(row, cutoff)) for row in rows]
        score = next(iter(answers(regraded).values()), {})
        out.append(dict(score, cutoff=cutoff))
    return out


SWEEP_CUTOFFS = (0.0, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)


def aggregate(rows):
    """Per system, the mean of each metric and how many questions it could be graded on."""
    out = {}
    for row in rows:
        bucket = out.setdefault(row["system"], {})
        for key in ("citation_f1", "coverage", "surfaced_coverage", "entity_hit", "temporal",
                    "token_f1", "latency_ms"):
            bucket.setdefault(key, []).append(row[key])
    summary = {}
    for system, buckets in out.items():
        summary[system] = {key: metrics.mean(values) for key, values in buckets.items()}
        summary[system]["graded_temporal"] = len([v for v in buckets["temporal"] if v is not None])
        summary[system]["graded_citation"] = len([v for v in buckets["citation_f1"] if v is not None])
        summary[system]["questions"] = len(buckets["latency_ms"])
    return summary


THREATS = """\
Threats to validity, which do not go away because a run went well:

  * One corpus. A result on a single domain is a case study, not a finding. Repeat it on a second,
    unrelated corpus before treating it as a property of the method.
  * Gold-set bias. Whoever wrote the questions shapes the answer. See the provenance above.
  * Paraphrase coverage. If the set has few paraphrase questions, a dense baseline looks artificially
    weak, because finding text worded differently from the source is exactly its advantage.
  * Scope. These metrics measure retrieval and grounding. Answer correctness needs a judge and is
    deliberately not scored here.
  * Size. A small set moves a long way on one question. Report the count next to every mean."""


def _fmt(value, width=7):
    if value is None:
        return " " * (width - 1) + "-"
    return ("%%%d.3f" % width) % value


def _answers_section(rows):
    """Right, wrong, abstained per system; the graph system by how its names matched; the cutoff
    sweep for a system that reports a confidence."""
    lines = ["", "=" * 78, "ANSWERS  (strict: the answer each system put forward)", "=" * 78]
    header = "%-18s %6s %6s %6s %10s %9s %7s %8s" % ("system", "right", "wrong", "abst", "precision",
                                                       "coverage", "score", "entity")
    lines += [header, "-" * len(header)]
    scored = answers(rows)
    for system in sorted(scored):
        s = scored[system]
        lines.append("%-18s %6d %6d %6d %10s %9s %7s %8s" % (system, s["right"], s["wrong"], s["abstained"],
                     _fmt(s["precision"], 10), _fmt(s["coverage"], 9), _fmt(s["score"], 7), _fmt(s["strict_entity"], 8)))
    lines += ["",
              "  precision  right among the questions it answered",
              "  coverage   the share it answered at all, rather than abstain",
              "  score      right +1, abstained 0, wrong -1, over every question: a guess that misses",
              "             costs more than saying nothing",
              "  entity     the entity it answered with is the expected one, not a neighbour of it",
              "  An entity system answers with the entity it bound, a passage retriever with its first",
              "  source. A negative question is right only when the system abstains."]
    graph = [row for row in rows if row["system"] == "oto"]
    if graph:
        grades = {}
        for row in graph:
            bucket = grades.setdefault(row.get("match") or "none", {"right": 0, "wrong": 0, "abstained": 0})
            if row.get("outcome") in bucket:
                bucket[row["outcome"]] += 1
        lines += ["", "oto, by how the question's name matched:"]
        for grade in ("id", "label", "alias", "lexicon", "ambiguous", "text", "none"):
            if grade in grades:
                g = grades[grade]
                lines.append("  %-10s right %d, wrong %d, abstained %d" % (grade, g["right"], g["wrong"], g["abstained"]))
        lines.append("  `text` and `ambiguous` are refused, never answered: binding them would be a guess.")
    for system in sorted({row["system"] for row in rows if row.get("confidence") is not None}):
        lines += ["", "%s at a similarity cutoff (below it, it abstains):" % system,
                  "  %-7s %6s %6s %6s %10s %9s %7s" % ("cutoff", "right", "wrong", "abst", "precision", "coverage", "score")]
        for s in sweep([row for row in rows if row["system"] == system], SWEEP_CUTOFFS):
            lines.append("  %-7.2f %6d %6d %6d %10s %9s %7s" % (s["cutoff"], s["right"], s["wrong"], s["abstained"],
                         _fmt(s["precision"], 10), _fmt(s["coverage"], 9), _fmt(s["score"], 7)))
        lines.append("  Read, do not pick, from this table: a cutoff chosen on the questions it is then scored")
        lines.append("  on is optimistic. Choose it on held-out questions, then pass --dense-min-similarity.")
    return lines


def report(meta, questions, summary, k, skipped=None, rows=None):
    """The full text report. Provenance first, threats last, numbers in between."""
    lines = []
    lines.append("=" * 78)
    lines.append("WHERE THESE QUESTIONS CAME FROM")
    lines.append("=" * 78)
    lines.append(_gold.describe(meta))
    lines.append("")
    kinds = {}
    for question in questions:
        kind = question.get("type") or "factual"
        kinds[kind] = kinds.get(kind, 0) + 1
    lines.append("%d question(s): %s" % (len(questions),
                                         ", ".join("%d %s" % (v, k2) for k2, v in sorted(kinds.items()))))
    if not kinds.get("paraphrase"):
        lines.append("NOTE: no paraphrase questions. A dense baseline's advantage is finding text "
                     "worded differently from the source, so a comparison without them flatters "
                     "lexical and graph methods.")
    lines.append("")
    lines.append("=" * 78)
    lines.append("RESULTS  (coverage at k=%d)" % k)
    lines.append("=" * 78)
    header = "%-18s %8s %8s %9s %8s %8s %9s" % ("system", "cite F1", "passage", "surfaced",
                                                "entity", "temporal", "ms/query")
    lines.append(header)
    lines.append("-" * len(header))
    for system in sorted(summary):
        row = summary[system]
        lines.append("%-18s %8s %8s %9s %8s %8s %9s"
                     # .get, not [], so a summary from an older run still prints. `_fmt(None)`
                     # renders a dash, which reads as "not measured" rather than as a zero.
                     % (system, _fmt(row.get("citation_f1"), 8), _fmt(row.get("coverage"), 8),
                        _fmt(row.get("surfaced_coverage"), 9), _fmt(row.get("entity_hit"), 8),
                        _fmt(row.get("temporal"), 8), _fmt(row.get("latency_ms"), 9)))
    lines.append("")
    lines.append("Two coverage columns, because one number cannot compare two architectures fairly:")
    lines.append("  passage   the gold source in the top %d of a passage search. What a retriever does."
                 % k)
    lines.append("  surfaced  the gold source anywhere the system put in front of the answer. For a")
    lines.append("            passage retriever these are the same list, so the two columns match. A")
    lines.append("            graph system reaches a source through an entity, so `passage` alone marks")
    lines.append("            it wrong on questions it answered correctly. Read both.")
    if rows:
        lines += _answers_section(rows)
    if skipped:
        lines.append("")
        lines.append("NOT MEASURED:")
        for name, reason in skipped:
            lines.append("  %-10s %s" % (name, reason))
        if any(name == "dense" for name, _ in (skipped or [])):
            lines.append("  Without a dense baseline the one dimension where an embedding method "
                         "usually wins is")
            lines.append("  unmeasured. Treat any comparison below as incomplete, not as a result.")
    lines.append("")
    any_system = next(iter(summary.values()), {})
    lines.append("graded on: %d question(s) for citation, %d for temporal"
                 % (any_system.get("graded_citation", 0), any_system.get("graded_temporal", 0)))
    lines.append("")
    lines.append(THREATS)
    return "\n".join(lines)
