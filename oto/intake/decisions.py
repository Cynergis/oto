# -*- coding: utf-8 -*-
"""What a person decided about a survey candidate: a real term, or noise. Recorded, never inferred.

Every decision names the candidate, the stage that proposed it, the fixes that brought or shaped it
(`via`), who decided and when. The log is append-only; the latest decision on a term is the one that
counts. Two uses:

    the review list   a rejected candidate is not listed again, so nobody reads known noise twice;
                      an accepted one is marked. The measured result (`oto survey --score`) is never
                      changed by decisions: a measurement that people's verdicts can move is not one.
    acceptance rate   per stage and per fix. A stage, or a fix, whose candidates people mostly reject
                      is producing noise, and should become opt-in or go.

Accepted terms do not go into the gold term list on their own: every accepted term was surfaced by
the survey by definition, so folding them in would raise its recall without it having improved.
"""
import datetime
import json
import os

NAME = "survey.decisions.jsonl"
VERDICTS = ("accepted", "rejected")


def path(project):
    return os.path.join(project.data, NAME)


def read(project):
    """Every decision, oldest first."""
    if not os.path.exists(path(project)):
        return []
    with open(path(project), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def latest(project):
    """{lowercased term: the latest decision on it}."""
    out = {}
    for entry in read(project):
        out[entry["term"].lower()] = entry
    return out


def _candidate(result, term):
    wanted = str(term or "").strip().lower()
    for candidate in result.get("candidates") or []:
        if wanted == candidate["term"].lower() or wanted in (v.lower() for v in candidate.get("variants") or []):
            return candidate
    return None


def record(project, result, term, verdict, by, at=None, note=None, as_=None):
    """Append one decision on a candidate of `result`. Returns the entry."""
    if verdict not in VERDICTS:
        raise ValueError("a verdict is one of %s" % ", ".join(VERDICTS))
    if not str(by or "").strip():
        raise ValueError("a decision needs --by: one nobody made cannot be counted or asked about")
    candidate = _candidate(result, term)
    if candidate is None:
        raise ValueError("%r is not a candidate of the current survey: decide on what it proposed" % term)
    entry = {"term": candidate["term"], "verdict": verdict, "kind": candidate["kind"],
             "stage": candidate.get("stage"), "via": list(candidate.get("via") or []),
             "by": by.strip(), "at": at or datetime.date.today().isoformat()}
    if note:
        entry["note"] = note
    if as_:
        entry["as"] = as_
    with open(path(project), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def apply(result, decided):
    """The review list after decisions: rejected candidates set aside, accepted ones marked. Returns
    a new result; the one passed in is not changed."""
    shown, rejected = [], []
    for candidate in result.get("candidates") or []:
        decision = decided.get(candidate["term"].lower())
        if decision and decision["verdict"] == "rejected":
            rejected.append(dict(candidate, decision=decision))
            continue
        shown.append(dict(candidate, decision=decision) if decision else candidate)
    out = dict(result, candidates=shown, rejected=rejected)
    for key in ("terms", "codes", "acronyms"):
        out[key] = [c for c in shown if c["kind"] == {"terms": "phrase", "codes": "code", "acronyms": "acronym"}[key]]
    return out


def stats(decided, result=None):
    """Acceptance per stage and per fix: {"stage": {name: counts}, "via": {fix: counts}}, where counts
    are accepted, rejected, rate (accepted among decided), and per stage how many are undecided."""
    def bucket(table, name):
        return table.setdefault(name, {"accepted": 0, "rejected": 0, "undecided": 0, "rate": None})

    out = {"stage": {}, "via": {}}
    for entry in decided.values():
        for table, names in ((out["stage"], [entry.get("stage") or "unknown"]), (out["via"], entry.get("via") or [])):
            for name in names:
                bucket(table, name)[entry["verdict"]] += 1
    for candidate in (result or {}).get("candidates") or []:
        if candidate["term"].lower() not in decided:
            bucket(out["stage"], candidate.get("stage") or "unknown")["undecided"] += 1
    for table in out.values():
        for counts in table.values():
            decided_n = counts["accepted"] + counts["rejected"]
            counts["rate"] = counts["accepted"] / decided_n if decided_n else None
    for counts in out["via"].values():
        counts.pop("undecided")
    return out


def report(entries, figures):
    lines = ["acceptance by stage (accepted among decided):"]
    for stage, c in sorted(figures["stage"].items()):
        lines.append("  %-12s accepted %d, rejected %d, undecided %d, rate %s"
                     % (stage, c["accepted"], c["rejected"], c["undecided"], "-" if c["rate"] is None else "%.2f" % c["rate"]))
    if figures["via"]:
        lines.append("acceptance by the fix that brought the candidate:")
        for fix, c in sorted(figures["via"].items()):
            lines.append("  %-12s accepted %d, rejected %d, rate %s"
                         % (fix, c["accepted"], c["rejected"], "-" if c["rate"] is None else "%.2f" % c["rate"]))
    lines.append("")
    lines.append("%d decision(s), latest last:" % len(entries))
    for entry in entries[-20:]:
        lines.append("  %-10s %-9s %-28s by %s%s%s" % (entry["at"], entry["verdict"], entry["term"], entry["by"],
                                                      (" as %s" % entry["as"]) if entry.get("as") else "",
                                                      ("  (%s)" % entry["note"]) if entry.get("note") else ""))
    lines.append("A stage or a fix whose candidates are mostly rejected is producing noise.")
    return "\n".join(lines)
