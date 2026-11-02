# -*- coding: utf-8 -*-
"""The route a change takes into main, derived from what the pull request carries, and its gate
(docs/plans/graph-journeys.md).

Three routes. `session`: the one ledger entry the pull request adds carries a confirmation whose
fingerprint equals the fact-level diff between graph.json at the base and at the head, so a person
saw this exact change and confirmed it; it merges on its own once the confirmer is the author and
the commits are verified. `guardrailed`: the ingest runs the entries name came from the transcripts
folder the project declares (`routes.guardrailed.from` in project.config.json); it merges when the
guardrails pass (phase 3; until then a person approves). `reviewed`: everything else, and whatever
fails the other two; one approving review.

The engine reads the two trees with git and never calls GitHub: what only GitHub knows, the author,
the reviews, whether the commits are verified, comes into `check` as arguments. A route only moves
towards `reviewed`.
"""
import json
import os
import subprocess

from .curate import diff as _diff

SESSION = "session"
REVIEWED = "reviewed"
GUARDRAILED = "guardrailed"

LEDGER = "changelog.jsonl"
GRAPH = "graph.json"
CONFIG = "project.config.json"
RUNS = "runs"


class RouteError(Exception):
    pass


def _git(root, *args):
    done = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, done.stdout, done.stderr


def read_at(root, ref, path):
    """The file at `path` in the tree `ref`, or None when the tree has no such file."""
    code, out, _err = _git(root, "show", "%s:%s" % (ref, path.replace(os.sep, "/")))
    return out if code == 0 else None


def _json_at(root, ref, path, default):
    text = read_at(root, ref, path)
    if text is None:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def _ledger_at(root, ref):
    text = read_at(root, ref, LEDGER)
    if not text:
        return []
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except ValueError:
                entries.append({"_unreadable": line[:80]})
    return entries


def _resolve(root, ref):
    code, out, err = _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    if code != 0:
        raise RouteError("%s is not a commit this repository knows%s" % (ref, (": " + err.strip()) if err.strip() else ""))
    return out.strip()


def _relative(root, path):
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:
        return path
    return rel.replace(os.sep, "/")


def _transcripts_folder(config):
    settings = ((config or {}).get("routes") or {}).get("guardrailed") or {}
    folder = settings.get("from")
    return folder.strip("/").replace(os.sep, "/") if isinstance(folder, str) and folder.strip() else None


def show(root, base, head="HEAD"):
    """The route of the change between `base` and `head`, and why: {route, proposed, reasons,
    entries, confirmation, fingerprint, runs, base, head}. `proposed` is the route the content asks
    for; `route` is where it stands after the record is checked (a confirmation that does not hold
    sends it to reviewed before any gate runs)."""
    base_sha, head_sha = _resolve(root, base), _resolve(root, head)
    before, after = _ledger_at(root, base_sha), _ledger_at(root, head_sha)
    live = _json_at(root, base_sha, GRAPH, {"nodes": [], "edges": []})
    proposed_graph = _json_at(root, head_sha, GRAPH, {"nodes": [], "edges": []})
    fingerprint = _diff.fingerprint(_diff.canonical(live, proposed_graph))
    config = _json_at(root, head_sha, CONFIG, {})
    out = {"base": base_sha, "head": head_sha, "fingerprint": fingerprint, "entries": [], "confirmation": None,
           "runs": [], "reasons": [], "proposed": REVIEWED, "route": REVIEWED}

    if after[:len(before)] != before:
        out["reasons"].append("the ledger was rewritten: an entry the base holds is missing or changed at the head, so nothing about this change can be taken on record")
        return out
    added = after[len(before):]
    out["entries"] = added
    runs = []
    for entry in added:
        for run in entry.get("runs") or []:
            if run not in runs:
                runs.append(run)
    out["runs"] = runs

    confirmed = [e for e in added if isinstance(e.get("confirmation"), dict)]
    if len(added) == 1 and confirmed:
        confirmation = confirmed[0]["confirmation"]
        out["confirmation"] = confirmation
        out["proposed"] = SESSION
        if confirmation.get("fingerprint") == fingerprint:
            out["route"] = SESSION
            out["reasons"].append("one ledger entry, confirmed by %s at %s, and its fingerprint is the fact-level diff of this change (%s)"
                                  % (confirmation.get("by"), confirmation.get("at"), fingerprint[:12]))
        else:
            out["reasons"].append("the confirmation's fingerprint (%s) does not match the diff between the base and the head (%s): "
                                  "something changed after %s confirmed, so a person reviews it"
                                  % (str(confirmation.get("fingerprint"))[:12], fingerprint[:12], confirmation.get("by")))
        return out
    if confirmed:
        out["proposed"] = SESSION
        out["confirmation"] = confirmed[-1]["confirmation"]
        out["reasons"].append("%d ledger entries, %d of them confirmed: one confirmed change per pull request, so a person reviews this one"
                              % (len(added), len(confirmed)))
        return out

    folder = _transcripts_folder(config)
    if added and runs and folder:
        origins = {}
        for run in runs:
            manifest = _json_at(root, head_sha, "%s/%s.json" % (RUNS, run), None)
            inbox = (manifest or {}).get("inbox")
            origins[run] = _relative(root, inbox) if inbox else None
        if all(origin and (origin == folder or origin.startswith(folder + "/")) for origin in origins.values()):
            out["proposed"] = out["route"] = GUARDRAILED
            out["reasons"].append("the ingest run(s) %s came from %s/, the transcripts folder the project names" % (", ".join(runs), folder))
            return out
        elsewhere = sorted(run for run, origin in origins.items() if not origin or not (origin == folder or origin.startswith(folder + "/")))
        out["reasons"].append("run(s) %s did not come from %s/: a person reviews what documents drafted" % (", ".join(elsewhere), folder))
    if not added:
        out["reasons"].append("no ledger entry added: the graph did not change through an apply, so a person reviews it")
    elif not out["reasons"]:
        out["reasons"].append("no confirmation on the %d ledger entr%s: drafted from documents, so a person reviews it"
                              % (len(added), "y" if len(added) == 1 else "ies"))
    return out


def check(root, base, head="HEAD", authors=(), approved=False, verified=False):
    """The gate's verdict: {ok, route, proposed, reasons, ...} with everything `show` says. `authors`
    are the identities GitHub gives the pull request (the login, the commit emails); `approved` says a
    review approved it; `verified` says every commit is verified. A session record that does not hold
    against them moves the route to reviewed, and reviewed needs the approval."""
    out = show(root, base, head)
    route = out["route"]
    if route == SESSION:
        known = {str(a).strip().lower() for a in authors if str(a).strip()}
        who = str((out.get("confirmation") or {}).get("by") or "").strip().lower()
        holds = True
        if not verified:
            out["reasons"].append("the commits are not all verified, so the confirmation cannot be trusted to be %s's" % who)
            holds = False
        if who not in known:
            out["reasons"].append("the author of the pull request (%s) is not the person who confirmed (%s)"
                                  % (", ".join(sorted(known)) or "unknown", who or "nobody"))
            holds = False
        if holds:
            out["ok"] = True
            out["reasons"].append("passes: confirmed in a session by its author, on verified commits; no other approval is needed")
            return out
        route = REVIEWED
    if route == GUARDRAILED:
        out["reasons"].append("the guardrails are not built yet (docs/plans/graph-journeys.md, phase 3): a person approves a transcript's change until they are")
        route = REVIEWED
    out["route"] = route
    if approved:
        out["ok"] = True
        out["reasons"].append("passes: approved by a reviewer")
    else:
        out["ok"] = False
        out["reasons"].append("needs one approving review on the pull request")
    return out


def render(result):
    lines = ["route: %s%s" % (result["route"], ("  (proposed %s)" % result["proposed"]) if result.get("proposed") != result["route"] else "")]
    if "ok" in result:
        lines[0] += "  " + ("passes" if result["ok"] else "does not pass yet")
    lines.append("  base %s -> head %s, fingerprint %s" % (result["base"][:12], result["head"][:12], result["fingerprint"]))
    confirmation = result.get("confirmation")
    if confirmation:
        lines.append("  confirmed by %s at %s (fingerprint %s)" % (confirmation.get("by"), confirmation.get("at"), str(confirmation.get("fingerprint"))[:12]))
    if result.get("runs"):
        lines.append("  ingest run(s): %s" % ", ".join(result["runs"]))
    for reason in result.get("reasons") or []:
        lines.append("  - %s" % reason)
    return "\n".join(lines)
