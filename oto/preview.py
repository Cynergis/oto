# -*- coding: utf-8 -*-
"""The preview: what the graph would be if everything pending went through.

`oto preview` composes the live graph, the open candidate and every proposal (merged as
`curate add --dry-run` would, refusals left out) and runs the compile stages over the result
into `build/preview/`, a second store beside the live one. `oto serve --http --preview` serves
that store; `--watch` rebuilds it whenever an authored file changes. The live store, the
candidate and the proposals are never written: the preview is a way to look, and the gates keep
their meaning. Rules run on the composed graph, so derived facts and policy findings for pending
knowledge appear here and nowhere else before apply.

The preview is built as a throwaway project: a temporary data directory holding the composed
graph and copies of the authored inputs, whose build directory is `build/preview/` and whose
corpus is the real one, linked in. `preview.json` beside the store records what it rests on.
"""
import datetime
import json
import os
import shutil
import tempfile
import time

from . import builder as _builder
from .curate import pending as _pending
from .project import Project, ProjectError

DIR_NAME = "preview"
META_NAME = "preview.json"
STAGES = {"knowledge", "rules", "ontology", "semantic", "sqlite"}
AUTHORED = ("project.config.json", "ontology.config.json", "ontology.rationale.json", "rules.json", "lexicon.json",
            "changelog.jsonl", "assertions.jsonl")
WATCHED = ("graph.json", "graph.candidate.json", "ontology.config.json", "rules.json", "lexicon.json", "proposals", "actions")


def directory(project):
    return os.path.join(project.src, DIR_NAME)


def database(project):
    return os.path.join(directory(project), project.identity()["db_name"])


def meta_path(project):
    return os.path.join(directory(project), META_NAME)


def read_meta(project):
    path = meta_path(project)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _link_or_copy(source, target):
    if os.path.lexists(target):
        if os.path.islink(target):
            os.remove(target)
        else:
            shutil.rmtree(target, ignore_errors=True)
    if not os.path.isdir(source):
        os.makedirs(target, exist_ok=True)
        return
    try:
        os.symlink(source, target, target_is_directory=True)
    except (OSError, NotImplementedError):
        shutil.copytree(source, target)


def build(project, today=None):
    """Compose and build the preview. Returns its meta dict."""
    root = os.path.dirname(project.src)
    pending = _pending.collect(root, today)
    out = directory(project)
    os.makedirs(out, exist_ok=True)
    started = time.time()
    scratch = tempfile.mkdtemp(prefix="oto-preview-")
    try:
        for name in AUTHORED:
            source = os.path.join(root, name)
            if os.path.exists(source):
                shutil.copyfile(source, os.path.join(scratch, name))
        with open(os.path.join(scratch, "graph.json"), "w", encoding="utf-8") as f:
            json.dump(pending["composed"], f, ensure_ascii=False)
        _link_or_copy(project.layout.corpus, os.path.join(out, "documents"))
        throwaway = Project(data=scratch, src=out)
        throwaway.options = {"targets": set(), "verify": False, "app": None}
        _builder.build(throwaway, only=STAGES, transactional=False)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    meta = {"built_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
            "seconds": round(time.time() - started, 2),
            "base_build_seq": project.build_seq(),
            "live_database": project.layout.database,
            "counts": pending["counts"], "stations": pending["stations"], "differs": pending["differs"],
            "nodes": len(pending["composed"].get("nodes") or []), "edges": len(pending["composed"].get("edges") or [])}
    with open(meta_path(project), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def signature(root):
    """A stamp of the authored inputs; when it changes, the preview is stale."""
    parts = []
    for name in WATCHED:
        path = os.path.join(root, name)
        if os.path.isdir(path):
            for entry in sorted(os.listdir(path)):
                full = os.path.join(path, entry)
                if os.path.isfile(full) and not entry.startswith("."):
                    st = os.stat(full)
                    parts.append((full, st.st_mtime_ns, st.st_size))
        elif os.path.isfile(path):
            st = os.stat(path)
            parts.append((path, st.st_mtime_ns, st.st_size))
    return tuple(parts)


class Watcher:
    """Rebuilds the preview when an authored file changes, on a thread; `quiet` seconds after the
    last change, so a burst of edits builds once."""

    def __init__(self, project, quiet=1.5, poll=0.5, on_built=None, log=None):
        self.project = project
        self.root = os.path.dirname(project.src)
        self.quiet = quiet
        self.poll = poll
        self.on_built = on_built
        self.log = log or (lambda *a: None)
        self.last = signature(self.root)
        self.builds = 0
        self.error = None
        self._stop = False
        self.thread = None

    def start(self):
        import threading
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self._stop = True

    def _run(self):
        pending_since = None
        while not self._stop:
            time.sleep(self.poll)
            current = signature(self.root)
            if current != self.last:
                self.last = current
                pending_since = time.time()
                continue
            if pending_since is not None and time.time() - pending_since >= self.quiet:
                pending_since = None
                try:
                    meta = build(self.project)
                    self.builds += 1
                    self.error = None
                    self.log("preview rebuilt: %d node(s), %d edge(s), %d pending change(s)" % (meta["nodes"], meta["edges"], meta["differs"]))
                    if self.on_built:
                        self.on_built(meta)
                except Exception as exc:                                    # noqa: BLE001 - keep watching
                    self.error = str(exc)
                    self.log("preview rebuild failed: %s" % exc)
