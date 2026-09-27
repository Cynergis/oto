# -*- coding: utf-8 -*-
"""Turn everything in the inbox into corpus markdown, one run at a time, with nothing lost.

Raw files move through four directories, and where a file sits says what happened to it:

    inbox/        dropped in by a person; unclaimed
    processing/   claimed by a run; extracted, but the graph does not hold its facts yet
    errors/<run>/ the run could not extract it, and a .error.json beside it says why
    archive/      the graph holds it, and the run that put it there is closed

A run claims the whole inbox by renaming each file into `processing/` (atomic on one filesystem,
so a crash at any point leaves every file exactly one place). It then extracts each file. A
failure moves the file to `errors/<run>/`; a success writes the corpus markdown and leaves the file
in `processing/`. So an empty `processing/` after `complete` means everything is in the graph, and
anything still there is work not finished.

Files reach `archive/` only through `complete`, which runs after the facts are curated and built,
never from extraction. Extraction is code and takes seconds; authoring the facts is judgment and
takes longer. A file in `processing/` is the visible sign that the second half is still owed.

Every run writes `runs/<run>.json`: each file it claimed, its size and content hash, and its
outcome. The hash is what tells a re-ingest from a new version: the same filename with different
bytes is a new version of a document the graph already cites, and the facts that cite it may need
supersession. `runs/index.json` remembers the last archived hash per filename for that comparison.

A lock in `processing/` refuses a second run while one is open. Runs are serial by design.

Within a run, order matters. Each document is extracted, rendered, given figure descriptions, then
scanned for personal data and credentials. It reaches the corpus only if the scan allows it. The
corpus files themselves carry no timestamp, so two runs over the same input produce identical
markdown; the manifests are bookkeeping, not corpus.
"""
import datetime
import hashlib
import importlib
import json
import os
import shutil

from ..validate.privacy import blocking, scan, summarize
from .descriptions import inject, needs_injection
from .document import IntakeStyle, slugify
from .registry import find, load_builtins, supported_extensions

DESCRIPTIONS_NAME = "diagram_descriptions.json"
LOCK_NAME = ".lock"
INDEX_NAME = "index.json"
ERROR_SUFFIX = ".error.json"

EXTRACTED = "extracted"
UNSUPPORTED = "unsupported"
MISSING_PARSER = "missing-parser"
BLOCKED = "blocked"
FAILED = "extraction-failed"


class IngestLocked(Exception):
    """Another run holds the processing directory."""


class NotReady(Exception):
    """`complete` was asked for before the graph holds the run's facts."""


# ---- small helpers ----

def style_for(project):
    """Header wording. A project with an existing corpus pins its own, so re-extraction is stable."""
    cfg = project.config()
    intake = cfg.get("intake") or {}
    return IntakeStyle(source_ref=intake.get("source_ref", "inbox/{filename}"),
                       pipeline_name=intake.get("pipeline_name", "OTO"))


def _curated(project):
    path = os.path.join(project.data, DESCRIPTIONS_NAME)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _render(extractor, doc, style):
    module = importlib.import_module("oto.intake.extractors.%s" % extractor.name)
    return module.render(doc, style)


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, payload):
    """Write to a sibling and rename, so a crash never leaves a half-written manifest."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def _files(directory):
    """Regular, non-hidden files in a directory, sorted. Missing directory means none."""
    if not os.path.isdir(directory):
        return []
    return sorted(n for n in os.listdir(directory)
                  if os.path.isfile(os.path.join(directory, n)) and not n.startswith("."))


def new_run_id(runs_dir):
    """Timestamp-based, unique within the directory even for two runs in one second."""
    base = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id, n = base, 1
    while os.path.exists(os.path.join(runs_dir, run_id + ".json")):
        n += 1
        run_id = "%s-%d" % (base, n)
    return run_id


class Lock:
    """One run at a time. The lock file names the holder, so a stale one can be diagnosed."""

    def __init__(self, processing_dir, run_id):
        self.path = os.path.join(processing_dir, LOCK_NAME)
        self.run_id = run_id

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = _read_json(self.path, {})
            raise IngestLocked("a run is already open: %s (started %s, pid %s). If it is not running, "
                               "remove %s." % (holder.get("run_id", "?"), holder.get("started", "?"),
                                                holder.get("pid", "?"), self.path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"run_id": self.run_id, "pid": os.getpid(), "started": _now()}, f)
        return self

    def __exit__(self, *_exc):
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


# ---- the run ----

def claim(inbox, processing, move=True):
    """Bring every file in the inbox into processing. Returns (names now in processing, collisions).

    The project's own inbox is a queue, so its files are MOVED: a claimed file leaves the queue.
    Any other directory is somebody's originals, so its files are COPIED and the directory is left
    exactly as it was. Emptying a folder a person pointed at would be the kind of surprise this
    layout exists to prevent.

    Files already in processing are leftovers from a run that did not finish. They are claimed
    again: extraction is idempotent, so re-running them is the recovery. An inbox file whose name
    is already in processing stays where it is and is reported, because writing over the leftover
    would lose one of the two.
    """
    os.makedirs(processing, exist_ok=True)
    collisions = []
    for name in _files(inbox):
        target = os.path.join(processing, name)
        if os.path.exists(target):
            collisions.append(name)
            continue
        if move:
            os.rename(os.path.join(inbox, name), target)
        else:
            shutil.copy2(os.path.join(inbox, name), target)
    return _files(processing), collisions


def _fail(processing, errors_dir, run_id, name, outcome, reason, extra=None):
    """Move a file to errors/<run>/ and write the reason beside it."""
    dest_dir = os.path.join(errors_dir, run_id)
    os.makedirs(dest_dir, exist_ok=True)
    os.rename(os.path.join(processing, name), os.path.join(dest_dir, name))
    record = {"run_id": run_id, "file": name, "outcome": outcome, "reason": reason, "at": _now()}
    if extra:
        record.update(extra)
    _write_json(os.path.join(dest_dir, name + ERROR_SUFFIX), record)


def ingest(project, inbox=None, allow_personal_data=False, strict_privacy=False, write_assets=True):
    """Claim the inbox, extract every file, write the run manifest. Returns a summary dict.

    Successes stay in processing/ until `complete` moves them to the archive.
    """
    load_builtins()
    style = style_for(project)
    curated = _curated(project)
    layout = project.layout

    inbox = os.path.abspath(inbox) if inbox else layout.inbox
    external = os.path.normcase(inbox) != os.path.normcase(os.path.abspath(layout.inbox))
    processing, errors_dir, runs_dir = layout.processing, layout.errors, layout.runs
    for d in (processing, errors_dir, runs_dir, layout.corpus):
        os.makedirs(d, exist_ok=True)
    assets_root = os.path.join(layout.corpus, "assets")
    index = _read_json(os.path.join(runs_dir, INDEX_NAME), {})

    run_id = new_run_id(runs_dir)
    manifest = {"run_id": run_id, "started": _now(), "inbox": inbox, "copied": external,
                "files": [], "completed": False}
    result = {"run_id": run_id, "written": [], "blocked": [], "skipped": [], "unsupported": [],
              "failed": [], "collisions": [], "new_versions": []}

    with Lock(processing, run_id):
        claimed, result["collisions"] = claim(inbox, processing, move=not external)
        print("run %s: claimed %d file(s) into processing/%s"
              % (run_id, len(claimed), " (copied from %s; the originals are untouched)" % inbox if external else ""))
        for name in result["collisions"]:
            print("  left in inbox: %s (a file of that name is already in processing/)" % name)

        for name in claimed:
            path = os.path.join(processing, name)
            entry = {"file": name, "size": os.path.getsize(path), "sha256": _sha256(path)}
            previous = index.get(name)
            if previous and previous.get("sha256") != entry["sha256"]:
                entry["previous_sha256"] = previous["sha256"]
                entry["previous_run"] = previous.get("run_id")
                result["new_versions"].append(name)

            extractor = find(path)
            if extractor is None:
                reason = "no extractor for this file type (supported: %s)" % ", ".join(supported_extensions())
                entry["outcome"] = UNSUPPORTED
                entry["reason"] = reason
                _fail(processing, errors_dir, run_id, name, UNSUPPORTED, reason)
                result["unsupported"].append(name)
                print("  UNSUPPORTED %s -> errors/%s/" % (name, run_id))
            elif not extractor.available():
                reason = "missing %s" % ", ".join(extractor.missing())
                entry["outcome"] = MISSING_PARSER
                entry["reason"] = reason
                _fail(processing, errors_dir, run_id, name, MISSING_PARSER, reason)
                result["skipped"].append((name, reason))
                print("  SKIPPED %s: %s -> errors/%s/" % (name, reason, run_id))
            else:
                try:
                    _extract_one(layout, style, curated, extractor, path, name, entry, run_id,
                                 assets_root if write_assets else None,
                                 allow_personal_data, strict_privacy, result)
                except Exception as exc:                      # noqa: BLE001 - recorded, not masked
                    reason = "%s: %s" % (type(exc).__name__, exc)
                    entry["outcome"] = FAILED
                    entry["reason"] = reason
                    _fail(processing, errors_dir, run_id, name, FAILED, reason)
                    result["failed"].append((name, reason))
                    print("  FAILED %s: %s -> errors/%s/" % (name, reason[:120], run_id))
                else:
                    if entry["outcome"] == BLOCKED:
                        _fail(processing, errors_dir, run_id, name, BLOCKED, entry["reason"],
                              {"findings": entry.get("findings")})
            manifest["files"].append(entry)

        manifest["finished"] = _now()
        manifest["summary"] = _summary(manifest["files"])
        _write_json(os.path.join(runs_dir, run_id + ".json"), manifest)

    s = manifest["summary"]
    print("\nrun %s: extracted %d, blocked %d, unsupported %d, missing parser %d, failed %d"
          % (run_id, s[EXTRACTED], s[BLOCKED], s[UNSUPPORTED], s[MISSING_PARSER], s[FAILED]))
    if result["new_versions"]:
        print("new version of %d document(s) the graph already cites: %s. Facts citing them may "
              "need supersession." % (len(result["new_versions"]), ", ".join(result["new_versions"])))
    if s[EXTRACTED]:
        print("%d file(s) wait in processing/ until the graph holds their facts. After `oto curate "
              "apply` and `oto build`: oto ingest complete --run %s" % (s[EXTRACTED], run_id))
    if s[EXTRACTED] < len(manifest["files"]):
        print("the rest are in errors/%s/ with a .error.json beside each. Fix and drop back in inbox/."
              % run_id)
    result["manifest"] = os.path.join(runs_dir, run_id + ".json")
    return result


def _extract_one(layout, style, curated, extractor, path, name, entry, run_id, assets_root,
                 allow_personal_data, strict_privacy, result):
    # The slug comes from the filename, so the asset directory is known before extraction.
    assets_dir = os.path.join(assets_root, slugify(name)) if assets_root else None
    doc = extractor.extract(path, style, assets_dir=assets_dir)

    text = _render(extractor, doc, style)
    if needs_injection(text):
        text, n_curated, n_auto = inject(text, curated)
    else:
        n_curated = n_auto = 0

    findings = scan(text)
    hard = blocking(findings) if not allow_personal_data else []
    if strict_privacy and findings:
        hard = findings
    if hard:
        entry["outcome"] = BLOCKED
        entry["reason"] = "the privacy scan found %d blocking item(s)" % len(hard)
        entry["findings"] = summarize(findings)
        result["blocked"].append((name, findings))
        print("  BLOCKED %s -> errors/%s/" % (name, run_id))
        print(summarize(findings))
        return

    if findings:
        print("  warnings for %s:" % name)
        print(summarize(findings))

    with open(os.path.join(layout.corpus, doc.slug + ".md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    entry["outcome"] = EXTRACTED
    entry["slug"] = doc.slug
    result["written"].append(doc.slug)
    print("  %s -> documents/%s.md (%s, %d curated + %d auto figure descriptions)"
          % (name, doc.slug, extractor.name, n_curated, n_auto))


def _summary(entries):
    counts = {k: 0 for k in (EXTRACTED, BLOCKED, UNSUPPORTED, MISSING_PARSER, FAILED)}
    for e in entries:
        counts[e["outcome"]] = counts.get(e["outcome"], 0) + 1
    return counts


# ---- after the graph holds the facts ----

def runs(project):
    """Every run manifest, oldest first."""
    runs_dir = project.layout.runs
    out = []
    for name in os.listdir(runs_dir) if os.path.isdir(runs_dir) else []:
        if name.endswith(".json") and name != INDEX_NAME:
            out.append(_read_json(os.path.join(runs_dir, name), {}))
    # By start time, then id: "…-2" must follow its base run, which a name sort gets wrong.
    out.sort(key=lambda m: (m.get("started", ""), len(m.get("run_id", "")), m.get("run_id", "")))
    return out


def open_runs(project):
    """Runs with extracted files not yet archived."""
    return [m for m in runs(project)
            if not m.get("completed") and any(e.get("outcome") == EXTRACTED for e in m.get("files", []))]


def _corpus_newer_than_database(layout, slugs):
    if not os.path.exists(layout.database):
        return True
    built = os.path.getmtime(layout.database)
    for slug in slugs:
        path = os.path.join(layout.corpus, slug + ".md")
        if os.path.exists(path) and os.path.getmtime(path) > built:
            return True
    return False


def complete(project, run_id=None, force=False):
    """Move a run's extracted files from processing/ to archive/ and close the run.

    Refuses, unless forced, while a candidate is open or the build does not yet include the
    run's documents: "archived" must keep meaning "in the graph".
    """
    from ..curate import session as _session

    layout = project.layout
    candidates = open_runs(project)
    if run_id:
        matching = [m for m in runs(project) if m.get("run_id") == run_id]
        if not matching:
            raise NotReady("no run %s" % run_id)
        manifest = matching[0]
        if manifest.get("completed"):
            raise NotReady("run %s is already complete" % run_id)
    elif candidates:
        manifest = candidates[-1]
    else:
        raise NotReady("no open run: nothing waits in processing/")

    extracted = [e for e in manifest.get("files", []) if e.get("outcome") == EXTRACTED]
    slugs = [e["slug"] for e in extracted]
    if not force:
        from ..curate import reattest as _reattest

        problems = []
        if _session.exists(project):
            problems.append("a curate candidate is open; apply or abort it first")
        stale = [p for p in _reattest.pending(project, _session.live(project)) if p["slug"] in slugs]
        if stale:
            problems.append("%d fact(s) cite a document this run re-ingested and have not been "
                            "re-attested against the new text (first: %s citing %s); list them in "
                            "that document's proposal, or retire them"
                            % (len(stale), stale[0]["id"], stale[0]["slug"]))
        if not os.path.exists(layout.database):
            problems.append("no build yet: run `oto build`")
        elif _corpus_newer_than_database(layout, slugs):
            problems.append("the build predates this run's documents: run `oto build`")
        if problems:
            raise NotReady("run %s is not ready to complete:\n  - %s. Pass --force to archive anyway."
                           % (manifest["run_id"], "\n  - ".join(problems)))

    os.makedirs(layout.archive, exist_ok=True)
    index_path = os.path.join(layout.runs, INDEX_NAME)
    index = _read_json(index_path, {})
    archived, versioned, missing = [], [], []
    with Lock(layout.processing, manifest["run_id"]):
        for entry in extracted:
            name = entry["file"]
            source = os.path.join(layout.processing, name)
            if not os.path.exists(source):
                missing.append(name)
                continue
            target = os.path.join(layout.archive, name)
            if os.path.exists(target):
                if _sha256(target) == entry["sha256"]:
                    os.remove(source)                    # identical bytes already archived
                else:
                    # A new version of an archived document: keep both, run id as the directory.
                    versioned_dir = os.path.join(layout.archive, manifest["run_id"])
                    os.makedirs(versioned_dir, exist_ok=True)
                    target = os.path.join(versioned_dir, name)
                    shutil.move(source, target)
                    versioned.append(name)
            else:
                shutil.move(source, target)
            archived.append(name)
            index[name] = {"sha256": entry["sha256"], "run_id": manifest["run_id"],
                           "slug": entry.get("slug"), "archived_at": _now()}
        manifest["completed"] = True
        manifest["completed_at"] = _now()
        _write_json(os.path.join(layout.runs, manifest["run_id"] + ".json"), manifest)
        _write_json(index_path, index)

    return {"run_id": manifest["run_id"], "archived": archived, "versioned": versioned,
            "missing": missing, "remaining": _files(layout.processing)}
