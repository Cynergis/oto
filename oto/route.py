# -*- coding: utf-8 -*-
"""The route a change takes into main, derived from what the pull request carries, and its gate
(docs/plans/graph-journeys.md).

Three routes. `session`: the one ledger entry the pull request adds carries a confirmation whose
fingerprint equals the fact-level diff between graph.json at the base and at the head, so a person
saw this exact change and confirmed it; it merges on its own once the confirmer is the author and
the commits are verified. `guardrailed`: the ingest runs the entries name came from the transcripts
folder the project declares (`routes.guardrailed.from` in project.config.json); it merges when the
five guardrails hold on the fact-level diff: additive only, cited and attributed as the speaker's
assertions, in scope, clean, bounded (`guardrails`). `reviewed`: everything else, and whatever fails
the other two; one approving review.

The engine reads the two trees with git and never calls GitHub: what only GitHub knows, the author,
the reviews, whether the commits are verified, comes into `check` as arguments. A route only moves
towards `reviewed`.
"""
import json
import os
import shlex
import subprocess

from .curate import diff as _diff

SESSION = "session"
REVIEWED = "reviewed"
GUARDRAILED = "guardrailed"

LEDGER = "changelog.jsonl"
GRAPH = "graph.json"
CONFIG = "project.config.json"
LOCK = "oto.lock.json"
PREVIOUS = "graph.previous.json"
#: what `rebase` rewrites from both sides: the branch's own diff of these is not carried over as a file
REBASED_FILES = (GRAPH, LEDGER, "audit.jsonl", "assertions.jsonl", PREVIOUS)
REPOSITORY_FILES = ".github/"
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


def allowed_of(config):
    """The routes the project's policy allows; every route when it says nothing. `reviewed` is always in."""
    allowed = ((config or {}).get("routes") or {}).get("allowed")
    if not isinstance(allowed, list) or not allowed:
        return {SESSION, REVIEWED, GUARDRAILED}
    return {r for r in allowed if isinstance(r, str)} | {REVIEWED}


def session_classes_of(config):
    """The classes a session may add or change without review, or None when the policy names none."""
    classes = (((config or {}).get("routes") or {}).get("session") or {}).get("classes")
    return [c for c in classes if isinstance(c, str)] if isinstance(classes, list) and classes else None


def _policy(out, config, canon):
    """The policy the project derived from its pack (phase 6), applied to the route the content asks
    for: a route not allowed, or a session change outside its classes, moves to reviewed."""
    proposed = out["proposed"]
    if proposed != REVIEWED and proposed not in allowed_of(config):
        out["route"] = REVIEWED
        out["reasons"].append("the %s route is not allowed on this project (routes.allowed: %s): a person reviews it"
                              % (proposed, ", ".join(sorted(allowed_of(config)))))
        return
    classes = session_classes_of(config)
    if out["route"] == SESSION and classes:
        touched = sorted({n.get("type") for n in canon["nodes_added"]} | {i["node"].get("type") for i in canon["nodes_changed"]})
        outside = [c for c in touched if c not in classes]
        if outside:
            out["route"] = REVIEWED
            out["reasons"].append("a session changes %s only without review (routes.session.classes); this change touches %s: a person reviews it"
                                  % (", ".join(classes), ", ".join(str(c) for c in outside)))


def show(root, base, head="HEAD"):
    """The route of the change between `base` and `head`, and why: {route, proposed, reasons,
    entries, confirmation, fingerprint, runs, base, head}. `proposed` is the route the content asks
    for; `route` is where it stands after the record is checked (a confirmation that does not hold
    sends it to reviewed before any gate runs). The policy that decides is the base's: a pull request
    is never judged by a policy it rewrites, and one that changes what the gate itself reads or runs
    on (the routes, the lock, the repository's workflows and rules) goes to a person."""
    out = _show(root, base, head)
    _own_inputs(out, root)
    return out


def _own_inputs(out, root):
    """What the gate reads or runs on, changed by the pull request since it left its base: the routes'
    policy in project.config.json, the lock that pins the engine the workflows install, and the
    repository's workflows and rules under .github/. Each is a person's to approve (ADR-0013: an
    engine upgrade is a reviewed change), and until it merges the base's decide."""
    base_sha, head_sha = out["base"], out["head"]
    code, merge_base, _err = _git(root, "merge-base", base_sha, head_sha)
    since = merge_base.strip() if code == 0 and merge_base.strip() else base_sha
    reasons = []
    before = (_json_at(root, since, CONFIG, {}) or {}).get("routes")
    after = (_json_at(root, head_sha, CONFIG, {}) or {}).get("routes")
    if before != after:
        reasons.append("this change rewrites the routes' policy (routes in %s): a person reviews it, and the base's policy decides until it merges" % CONFIG)
    code, names, _err = _git(root, "diff", "--name-only", since, head_sha)
    touched = sorted(n for n in (names.splitlines() if code == 0 else []) if n == LOCK or n.startswith(REPOSITORY_FILES))
    if touched:
        reasons.append("this change touches what the gate runs on (%s): the engine the workflows install, or the workflows and rules themselves, "
                       "so a person reviews it" % ", ".join(touched))
    if reasons:
        out["route"] = REVIEWED
        out["reasons"].extend(reasons)


def _show(root, base, head):
    base_sha, head_sha = _resolve(root, base), _resolve(root, head)
    before, after = _ledger_at(root, base_sha), _ledger_at(root, head_sha)
    live = _json_at(root, base_sha, GRAPH, {"nodes": [], "edges": []})
    proposed_graph = _json_at(root, head_sha, GRAPH, {"nodes": [], "edges": []})
    canon = _diff.canonical(live, proposed_graph)
    fingerprint = _diff.fingerprint(canon)
    config = _json_at(root, base_sha, CONFIG, {})        # the base's policy: a change never judges itself by its own
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
            _policy(out, config, canon)
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
            _policy(out, config, canon)
            return out
        elsewhere = sorted(run for run, origin in origins.items() if not origin or not (origin == folder or origin.startswith(folder + "/")))
        out["reasons"].append("run(s) %s did not come from %s/: a person reviews what documents drafted" % (", ".join(elsewhere), folder))
    if not added:
        out["reasons"].append("no ledger entry added: the graph did not change through an apply, so a person reviews it")
    elif not out["reasons"]:
        out["reasons"].append("no confirmation on the %d ledger entr%s: drafted from documents, so a person reviews it"
                              % (len(added), "y" if len(added) == 1 else "ies"))
    return out


def settings_of(config):
    """The guardrailed route's settings, {} when the project declares none: `from` (the transcripts
    folder), `classes` (the kinds a transcript may add), `max_facts`, `additive_only`, `attributed`."""
    settings = ((config or {}).get("routes") or {}).get("guardrailed")
    return settings if isinstance(settings, dict) else {}


def _assertions_at(root, ref):
    text = read_at(root, ref, "assertions.jsonl") or ""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("id"):
                out[entry["id"]] = entry
    return out


def _duplicates_brought(root, base, head):
    """Assertion ids the log at `head` repeats and the log at `base` does not: damage already on main is not this pull request's."""
    from .curate import assertions as _assertions

    def repeated(ref):
        entries = []
        for line in (read_at(root, ref, _assertions.LOG_NAME) or "").splitlines():
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
        return set(_assertions.duplicates([e for e in entries if isinstance(e, dict)]))
    return sorted(repeated(head) - repeated(base))


def _run_manifests_at(root, ref):
    """{run_id: manifest} for every run manifest the tree holds."""
    code, out, _err = _git(root, "ls-tree", "--name-only", ref, RUNS + "/")
    manifests = {}
    if code != 0:
        return manifests
    for path in out.split():
        if path.endswith(".json") and not path.endswith("/index.json"):
            manifest = _json_at(root, ref, path, None)
            if isinstance(manifest, dict) and manifest.get("run_id"):
                manifests[manifest["run_id"]] = manifest
    return manifests


def _document_names(manifest):
    """Every name a corpus document of the run may be cited by: its slug, its file name, the name without extension."""
    from .intake.document import slugify
    names = set()
    for entry in manifest.get("files") or []:
        name = entry.get("file") or ""
        if entry.get("slug"):
            names.add(entry["slug"])
        if name:
            names.add(name)
            names.add(os.path.splitext(name)[0])
            names.add(slugify(name))
    return names


def guardrails(root, base, head="HEAD", shown=None):
    """The five guardrails on the change between `base` and `head`: {ok, guardrails: [{name, ok,
    detail}], settings, runs, base, head, fingerprint}. Raises RouteError when the project declares
    no guardrailed route. The settings are the base's, so a change cannot loosen the guardrails it is
    held to; the graph, the ledger, the assertions and the run manifests are read at the head; the
    earlier runs at the base."""
    from .curate import assertions as _assertions
    shown = shown or show(root, base, head)
    base_sha, head_sha = shown["base"], shown["head"]
    config = _json_at(root, base_sha, CONFIG, {})
    settings = settings_of(config)
    if not settings:
        raise RouteError("the project declares no guardrailed route: `routes.guardrailed` in project.config.json names the transcripts "
                         "folder (`from`), the classes a transcript may add (`classes`), `max_facts`, `additive_only` and `attributed`")
    folder = _transcripts_folder(config) or "inbox/transcripts"
    live = _json_at(root, base_sha, GRAPH, {"nodes": [], "edges": []})
    after = _json_at(root, head_sha, GRAPH, {"nodes": [], "edges": []})
    canon = _diff.canonical(live, after)
    added = canon["nodes_added"]
    log = _assertions_at(root, head_sha)
    manifests_now = _run_manifests_at(root, head_sha)
    manifests = {run: manifests_now.get(run) for run in shown["runs"]}
    earlier = {run: m for run, m in _run_manifests_at(root, base_sha).items() if run not in manifests}
    results = []

    def record(name, problems, held, skipped=None):
        if skipped:
            results.append({"name": name, "ok": True, "detail": skipped})
        elif problems:
            results.append({"name": name, "ok": False, "detail": "; ".join(problems)})
        else:
            results.append({"name": name, "ok": True, "detail": held})

    # additive only: nothing the graph believed is changed, removed or retired
    problems = []
    if settings.get("additive_only", True):
        for item in canon["nodes_changed"]:
            problems.append("%s changed (%s)" % (item["id"], ", ".join(item["fields"])))
        for nid in canon["nodes_removed"]:
            problems.append("%s removed" % nid)
        for key in canon["edges_removed"]:
            problems.append("edge %s -%s-> %s removed" % tuple(key))
        for node in added:
            if node.get("status") == "superseded" or node.get("supersedes") or node.get("superseded_by"):
                problems.append("%s retires or is superseded: a contradiction with what the graph believed" % node.get("id"))
        record("additive", problems, "%d node(s) and %d edge(s) added, nothing changed, removed or retired" % (len(added), len(canon["edges_added"])))
    else:
        record("additive", [], "", skipped="not required by the project (additive_only is off)")

    # cited and attributed: every fact is the speaker's assertion, citing a transcript of the run
    problems = []
    transcript_docs = set()
    for manifest in manifests.values():
        if manifest:
            transcript_docs |= _document_names(manifest)
    if settings.get("attributed", True):
        for node in added:
            nid = node.get("id")
            cited = _assertions.cited_ids(node)
            if node.get("source_type") != _assertions.HUMAN_ASSERTION or not cited:
                problems.append("%s is not a human assertion citing an entry of the assertions log (oto curate assert --by <speaker>)" % nid)
                continue
            for identifier in sorted(cited):
                entry = log.get(identifier)
                if not entry:
                    problems.append("%s cites %s, which the assertions log does not hold" % (nid, identifier))
                elif not (entry.get("by") or "").strip():
                    problems.append("%s cites %s, which names no speaker" % (nid, identifier))
            docs = [d for d in list(node.get("sources") or []) + [node.get("source_doc")] if d and not str(d).startswith(_assertions.PREFIX)]
            if not any(d in transcript_docs for d in docs):
                problems.append("%s cites no transcript document of run(s) %s" % (nid, ", ".join(shown["runs"]) or "none"))
        record("attributed", problems, "every added fact is a speaker's assertion citing a transcript of the run")
    else:
        record("attributed", [], "", skipped="not required by the project (attributed is off)")

    # in scope: only the classes allowed, and the vocabulary untouched
    problems = []
    classes = settings.get("classes")
    if isinstance(classes, list) and classes:
        outside = sorted({node.get("type") for node in added if node.get("type") not in classes})
        if outside:
            problems.append("class(es) %s are not among the ones a transcript may add (%s)" % (", ".join(str(c) for c in outside), ", ".join(classes)))
    vocab_before = _json_at(root, base_sha, "ontology.config.json", None)
    vocab_after = _json_at(root, head_sha, "ontology.config.json", None)
    if vocab_before != vocab_after:
        problems.append("the vocabulary changed (ontology.config.json): a transcript never changes the words")
    record("scope", problems, "classes %s; the vocabulary untouched" % (", ".join(classes) if isinstance(classes, list) and classes else "any"))

    # clean: the strict privacy scan ran, and no transcript was ingested before
    problems = []
    if not manifests:
        problems.append("no ingest run recorded on the ledger entries")
    for run, manifest in manifests.items():
        if not manifest:
            problems.append("run %s has no manifest at the head" % run)
            continue
        if manifest.get("strict_privacy") is not True:
            problems.append("run %s was not ingested with --strict-privacy" % run)
        for entry in manifest.get("files") or []:
            sha = entry.get("sha256")
            if not sha:
                continue
            for old_run, old in earlier.items():
                if any(e.get("sha256") == sha for e in old.get("files") or []):
                    problems.append("%s (sha256 %s) was ingested before, in run %s" % (entry.get("file"), sha[:8], old_run))
    record("clean", problems, "the strict privacy scan ran on run(s) %s; no transcript ingested twice" % ", ".join(manifests) )

    # bounded
    problems = []
    count = len(added) + len(canon["edges_added"])
    limit = settings.get("max_facts")
    if isinstance(limit, int) and limit > 0 and count > limit:
        problems.append("%d facts added, the limit is %d" % (count, limit))
    record("bounded", problems, "%d fact(s) added%s" % (count, (", the limit is %d" % limit) if isinstance(limit, int) and limit > 0 else ", no limit set"))

    return {"ok": all(g["ok"] for g in results), "guardrails": results, "settings": settings, "runs": shown["runs"],
            "base": base_sha, "head": head_sha, "fingerprint": shown["fingerprint"], "folder": folder}


def transcript_findings(project, live, candidate):
    """For `oto curate check`: while an ingest run from the transcripts folder is open and the project
    asks for attribution, every new node of the candidate must be a human assertion citing the log.
    Returns [(node id, detail)]."""
    from .curate import assertions as _assertions
    from .intake import pipeline as _pipeline
    try:
        config = project.config()
    except Exception:                                   # noqa: BLE001 - no config, nothing to hold the candidate to
        return []
    settings = settings_of(config)
    folder = _transcripts_folder(config)
    if not settings or not folder or not settings.get("attributed", True):
        return []
    open_transcripts = []
    for manifest in _pipeline.open_runs(project):
        origin = _relative(project.data, manifest.get("inbox") or "")
        if origin == folder or origin.startswith(folder + "/"):
            open_transcripts.append(manifest.get("run_id"))
    if not open_transcripts:
        return []
    live_ids = {n.get("id") for n in live.get("nodes") or []}
    out = []
    for node in candidate.get("nodes") or []:
        nid = node.get("id")
        if not nid or nid in live_ids:
            continue
        if node.get("source_type") != _assertions.HUMAN_ASSERTION or not _assertions.cited_ids(node):
            out.append((nid, "drafted while the transcript run(s) %s are open: a fact from a transcript is the speaker's assertion, "
                             "recorded with oto curate assert --by <speaker> --at <date> --text ... and cited (source_type human_assertion)"
                        % ", ".join(open_transcripts)))
    return out


def check(root, base, head="HEAD", authors=(), approved=False, verified=False):
    """The gate's verdict: {ok, route, proposed, reasons, ...} with everything `show` says. `authors`
    are the identities GitHub gives the pull request (the login, the commit emails); `approved` says a
    review approved it; `verified` says every commit is verified. A session record that does not hold
    against them moves the route to reviewed, and reviewed needs the approval."""
    out = show(root, base, head)
    brought = _duplicates_brought(root, out["base"], out["head"])
    if brought:
        out["ok"] = False
        out["route"] = REVIEWED
        out["reasons"].append("the assertion log holds %s more than once, so a fact citing it could mean either statement. No approval can pass "
                              "this: a person gives each statement its own id, and points each fact at the right one" % ", ".join(brought))
        return out
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
        try:
            held = guardrails(root, base, head, shown=out)
        except RouteError as exc:
            out["reasons"].append(str(exc))
            held = None
        if held:
            out["guardrails"] = held["guardrails"]
            if held["ok"]:
                out["ok"] = True
                out["reasons"].append("passes: the five guardrails hold on this change (additive, attributed, scope, clean, bounded); no approval is needed")
                return out
            for item in held["guardrails"]:
                if not item["ok"]:
                    out["reasons"].append("guardrail %s: %s" % (item["name"], item["detail"]))
        route = REVIEWED
    out["route"] = route
    if approved:
        out["ok"] = True
        out["reasons"].append("passes: approved by a reviewer")
    else:
        out["ok"] = False
        named, teams = _named_at(root, out["base"])
        who = "someone with write access who didn't write it"
        if named is not None:
            wrote = {str(a).strip().lower() for a in authors}
            may = sorted(login for login in named if login not in wrote) + ["the team %s" % t for t in teams]
            who = "someone the access file names who didn't write it"
            if may:
                who += ": %s" % ", ".join(may)
            else:
                out["reasons"].append("the access file at the base names nobody else who could approve this: add a reviewer to it first, by a pull request someone else writes and a steward approves")
        out["reasons"].append("needs one approving review on the pull request, of its head commit, from %s" % who)
    return out


def qualified_reviewers(reviews, head_sha, authors=()):
    """The logins whose standing decision approves `head_sha`, from the reviews GitHub lists for a pull
    request, oldest first, and none of them an author: an approval of an earlier commit is of something
    else, and a person's own doesn't count. A comment leaves a decision standing. Whether a login may
    write here is the workflow's to ask, since only GitHub knows; the engine never calls it."""
    known = {str(a).strip().lower() for a in authors if str(a).strip()}
    standing = {}
    for review in reviews if isinstance(reviews, list) else []:
        login = (review.get("user") or {}).get("login") if isinstance(review, dict) else None
        if login and review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            standing[login] = review
    return sorted(login for login, review in standing.items()
                  if review["state"] == "APPROVED" and review.get("commit_id") == head_sha and login.lower() not in known)


def _named_at(root, ref):
    """(logins lowercased, teams) whose approval the base's access file counts, or (None, None) with no such file, or none filled in.
    The base's, because a pull request never names its own reviewer."""
    from . import access as _access
    text = read_at(root, ref, _access.FILE.replace(os.sep, "/"))
    try:
        found = json.loads(text) if text else None
    except ValueError:
        found = None
    logins, teams = _access.who_may_approve(found if isinstance(found, dict) else None)
    return ({l.lower() for l in logins}, teams) if logins is not None else (None, None)


def approver_lines(root, reviews, head_sha, base, authors=()):
    """Who the workflow should ask GitHub about, one per line: `login` when that's all it takes, or `login org/team ...` when they count
    only as a member of one of those teams. Someone the base's access file doesn't name, and no team could make count, isn't listed."""
    logins = qualified_reviewers(reviews, head_sha, authors)
    named, teams = _named_at(root, _resolve(root, base))
    if named is None:
        return logins
    out = []
    for login in logins:
        if login.lower() in named:
            out.append(login)
        elif teams:
            out.append("%s %s" % (login, " ".join(teams)))
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


def render_guardrails(result):
    lines = ["guardrails: %s   (run(s) %s, from %s/)" % ("pass" if result["ok"] else "fail", ", ".join(result["runs"]) or "none", result["folder"])]
    for item in result["guardrails"]:
        lines.append("  %-4s %s: %s" % ("ok" if item["ok"] else "FAIL", item["name"], item["detail"]))
    return "\n".join(lines)


def _merge_base(root, a, b):
    code, out, err = _git(root, "merge-base", a, b)
    if code != 0:
        raise RouteError("no common commit between %s and %s%s" % (a, b, (": " + err.strip()) if err.strip() else ""))
    return out.strip()


def _blob(root, ref, path):
    """The id of a file at a commit, or None where it has no such file."""
    code, out, _err = _git(root, "rev-parse", "--verify", "--quiet", "%s:%s" % (ref, path))
    return out.strip() if code == 0 and out.strip() else None


def _changed(root, a, b):
    code, out, _err = _git(root, "diff", "--name-only", a, b)
    return set(out.splitlines()) if code == 0 else set()


def _audit_records_at(root, ref):
    from . import audit as _audit
    out = []
    for line in (read_at(root, ref, _audit.NAME) or "").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("hash"):
            out.append(record)
    return out


def _rechained_audit(root, onto_sha, base_sha, head_sha, graph_version):
    """The audit log at `onto`, with the records this change added re-chained onto it. A record already
    on `onto` stays exactly as it was. A moved one takes its new place and the graph as it now stands,
    and says where it came from: `rebased_from` is its old hash, `rebased_onto` the commit."""
    from . import audit as _audit
    kept = _audit_records_at(root, onto_sha)
    before = {r["hash"] for r in _audit_records_at(root, base_sha)}
    prev = kept[-1]["hash"] if kept else ""
    seq = (kept[-1].get("seq") or len(kept)) if kept else 0
    out = list(kept)
    for record in _audit_records_at(root, head_sha):
        if record["hash"] in before:
            continue
        seq += 1
        moved = {k: v for k, v in record.items() if k != "hash"}
        moved.update(seq=seq, prev=prev, graph=graph_version, rebased_from=record["hash"], rebased_onto=onto_sha)
        moved["hash"] = _audit.digest(moved)
        prev = moved["hash"]
        out.append(moved)
    return out


def rebase(root, onto, head="HEAD", verified=False):
    """For a pull request that fell behind: re-apply the facts it adds over its base onto `onto` (the
    new main), through the gates, in the working tree. The fact-level diff from the merge base to
    `head` is applied to the graph at `onto`: the nodes added, the nodes changed (when `onto` still
    holds the base's version), the nodes removed, the edges added and removed; a fact that moved on
    both sides is a conflict and nothing is written, and so is another file both sides changed, or two
    statements under one id. The ledger becomes `onto`'s with the pull request's entries on top, each
    marked `rebased_onto`; the audit log `onto`'s with this change's records re-chained on top; the
    assertions the head added join `onto`'s. Returns {ok, holds, fingerprint, conflicts, findings,
    entries, onto, base, head, steps}: `holds` says the confirmation's fingerprint still equals the
    diff, None without a confirmation, and `steps` are the git commands that put this change on
    `onto` as one commit. The person (or their skill) runs them, because the session route trusts
    commits by the confirmer; nothing here touches git. With `verified`, the steps end in a commit
    GitHub makes (`oto repo commit`), which is verified with no key on this computer."""
    from . import audit as _audit
    from .curate import assertions as _assertions
    from .project import Project
    onto_sha, head_sha = _resolve(root, onto), _resolve(root, head)
    base_sha = _merge_base(root, onto_sha, head_sha)
    shown = show(root, base_sha, head_sha)
    canon = _diff.canonical(_json_at(root, base_sha, GRAPH, {"nodes": [], "edges": []}), _json_at(root, head_sha, GRAPH, {"nodes": [], "edges": []}))
    base_graph = _json_at(root, base_sha, GRAPH, {"nodes": [], "edges": []})
    target = _json_at(root, onto_sha, GRAPH, {"nodes": [], "edges": []})
    base_nodes, target_nodes = _diff.index_nodes(base_graph), _diff.index_nodes(target)
    out = {"ok": False, "holds": None, "fingerprint": None, "conflicts": [], "findings": [], "entries": len(shown["entries"]),
           "onto": onto_sha, "base": base_sha, "head": head_sha, "route": shown["proposed"], "steps": []}
    if onto_sha == base_sha:
        out["ok"] = True
        out["fingerprint"] = shown["fingerprint"]
        out["holds"] = (shown["confirmation"] or {}).get("fingerprint") == shown["fingerprint"] if shown["confirmation"] else None
        out["conflicts"].append("nothing to do: %s is the base of this change already" % onto[:12])
        return out
    if _resolve(root, "HEAD") != head_sha:
        out["conflicts"].append("the steps act on the branch checked out here, and that is not %s: check it out first" % head[:12])
        return out
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")[1]
    if dirty.strip():
        out["conflicts"].append("uncommitted changes here, which the steps would throw away: commit them or set them aside first (%s)"
                                % ", ".join(line[3:] for line in dirty.splitlines()[:5]))
        return out
    others = _changed(root, base_sha, head_sha) - set(REBASED_FILES)
    for path in sorted(others & _changed(root, base_sha, onto_sha)):
        if _blob(root, onto_sha, path) != _blob(root, head_sha, path):
            out["conflicts"].append("%s changed here and on %s: this file isn't facts, so a person settles it" % (path, onto[:12]))

    nodes = [json.loads(json.dumps(n)) for n in target.get("nodes") or []]
    by_id = {n.get("id"): n for n in nodes}
    for node in canon["nodes_added"]:
        nid = node.get("id")
        if nid in by_id and by_id[nid] != node:
            out["conflicts"].append("%s was added on both sides with different facts" % nid)
        elif nid not in by_id:
            nodes.append(json.loads(json.dumps(node)))
            by_id[nid] = nodes[-1]
    for item in canon["nodes_changed"]:
        nid = item["id"]
        if nid not in by_id:
            out["conflicts"].append("%s changed here but is gone from %s" % (nid, onto[:12]))
        elif by_id[nid] != base_nodes.get(nid) and by_id[nid] != item["node"]:
            out["conflicts"].append("%s changed here and on %s" % (nid, onto[:12]))
        else:
            by_id[nid].clear()
            by_id[nid].update(json.loads(json.dumps(item["node"])))
    for nid in canon["nodes_removed"]:
        if nid in by_id and by_id[nid] != base_nodes.get(nid):
            out["conflicts"].append("%s removed here but changed on %s" % (nid, onto[:12]))
        elif nid in by_id:
            nodes = [n for n in nodes if n.get("id") != nid]
            del by_id[nid]
    edges = [dict(e) for e in target.get("edges") or []]
    keys = {_diff.edge_key(e) for e in edges}
    for key in canon["edges_added"]:
        if tuple(key) not in keys:
            edges.append({"from": key[0], "rel": key[1], "to": key[2]})
            keys.add(tuple(key))
    removed = {tuple(key) for key in canon["edges_removed"]}
    edges = [e for e in edges if _diff.edge_key(e) not in removed]
    onto_assertions = _assertions_at(root, onto_sha)
    head_assertions = _assertions_at(root, head_sha)
    base_assertions = _assertions_at(root, base_sha)
    added_assertions = {k: v for k, v in head_assertions.items() if k not in base_assertions}
    for identifier in sorted(k for k, v in added_assertions.items() if k in onto_assertions and onto_assertions[k] != v):
        out["conflicts"].append("assertion %s says one thing here and another on %s: an id from an older engine, so a person gives each statement its own" % (identifier, onto[:12]))
    if out["conflicts"]:
        return out

    project = Project.standard(root)
    new_graph = dict(target, nodes=nodes, edges=edges)
    try:
        with open(project.ontology_config_path, encoding="utf-8") as f:
            vocabulary = json.load(f)
    except (OSError, ValueError):
        vocabulary = None
    known = set(onto_assertions) | set(added_assertions)
    findings = _diff.check(target, new_graph, vocabulary, known_assertions=known)
    blocking = _diff.blocking(findings)
    if blocking:
        out["findings"] = ["%s: %s" % (f.subject, f.detail) for f in blocking]
        return out

    # write: the graph, the previous graph (so undo works), the ledger, the audit log, the assertions
    with open(project.graph_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(new_graph, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(root, "graph.previous.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(target, f, indent=2, ensure_ascii=False)
        f.write("\n")
    lines = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in _ledger_at(root, onto_sha)]
    for entry in shown["entries"]:
        entry = dict(entry, rebased_onto=onto_sha)
        lines.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    with open(os.path.join(root, LEDGER), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    records = _rechained_audit(root, onto_sha, base_sha, head_sha, _audit.graph_version(project))
    if records:
        with open(_audit.path(project), "w", encoding="utf-8", newline="\n") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    if onto_assertions or added_assertions:
        with open(_assertions.log_path(project), "w", encoding="utf-8", newline="\n") as f:
            for entry in list(onto_assertions.values()) + [v for k, v in added_assertions.items() if k not in onto_assertions]:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    fingerprint = _diff.fingerprint(_diff.canonical(target, new_graph))
    out["ok"] = True
    out["fingerprint"] = fingerprint
    confirmation = shown.get("confirmation")
    out["holds"] = (confirmation.get("fingerprint") == fingerprint) if confirmation else None
    out["steps"] = _steps(root, onto_sha, others, shown["entries"], verified=verified)
    return out


def git_steps(onto_sha, paths, note, verified_on=None):
    """Put a change on `onto` as one commit, holding the working tree as a rebase left it. The index starts
    from `onto`, so a file main changed meanwhile stays main's: only what this change touches is added. The
    last checkout brings main's other files into the working tree. With `verified_on`, a branch, the commit
    is made by GitHub (`oto repo commit`), so it is verified with no key on this computer."""
    if verified_on:
        return ["git reset -q %s" % onto_sha,
                "git add -- %s" % " ".join(shlex.quote(p) for p in paths),
                "oto repo commit --replace --message %s" % shlex.quote(note),
                "git checkout -q -- ."]
    return ["git reset -q %s" % onto_sha,
            "git add -- %s" % " ".join(shlex.quote(p) for p in paths),
            "git commit -q -m %s" % shlex.quote(note),
            "git checkout -q -- .",
            "git push --force-with-lease origin HEAD"]


def _steps(root, onto_sha, others, entries, verified=False):
    paths = [p for p in REBASED_FILES if p != PREVIOUS and os.path.exists(os.path.join(root, p))]
    paths += [p for p in sorted(others) if os.path.exists(os.path.join(root, p)) or _blob(root, onto_sha, p)]
    note = next((e.get("note") for e in reversed(entries) if e.get("note")), None) or "This change, on the new main"
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1].strip() if verified else None
    return git_steps(onto_sha, paths, note, verified_on=branch)


def render_rebase(result):
    lines = ["rebase onto %s: %s" % (result["onto"][:12], "re-applied" if result["ok"] else "refused")]
    lines.append("  base %s -> head %s, %d ledger entr%s" % (result["base"][:12], result["head"][:12], result["entries"], "y" if result["entries"] == 1 else "ies"))
    for conflict in result["conflicts"]:
        lines.append("  conflict: %s" % conflict)
    for finding in result["findings"]:
        lines.append("  blocked at the gate: %s" % finding)
    if result["ok"]:
        if result["holds"] is True:
            lines.append("  the confirmation holds: the fact-level diff is the same (%s)" % result["fingerprint"][:12])
        elif result["holds"] is False:
            lines.append("  the confirmation no longer holds: the fact-level diff changed (%s); a person reviews it" % result["fingerprint"][:12])
        else:
            lines.append("  fingerprint %s (no confirmation on this change)" % result["fingerprint"][:12])
        lines.append("  written: the graph, the ledger, the audit log and the assertions. Review them, then put this change on the new main, as yourself:")
        lines += ["    %s" % step for step in result["steps"]]
    else:
        lines.append("  nothing written: resolve on the branch, or let a person review the pull request")
    return "\n".join(lines)
