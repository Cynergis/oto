# -*- coding: utf-8 -*-
"""Run the compile stages so a failure cannot leave a broken build.

The stages write as they go, and later stages read what earlier ones wrote, so a failure part-way
through leaves a directory that looks complete but is not. Pre-flight catches the common causes, but
not a disk error or a bug.

The fix is a transaction. The previous generated layers are *renamed* aside, which is instant on one
filesystem, then the stages run. On success the saved copy is deleted; on failure it is moved back, so
the project keeps the last good build.

The corpus under `documents/` is left alone: it is an input to these stages, produced by ingest.
A partial build (`--only`) stashes only what the stages it runs own, so a later stage run alone,
`--only site` or `--only neo4j`, still reads what the earlier ones wrote.
"""
import importlib
import os
import shutil

SAVE_DIR = ".oto-previous"

# Individual files the stages write inside the graph directory. The directories they own
# (entities, cards, ontology) come from the layout.
GRAPH_FILES = ("knowledge-graph.json", "entity-index.json", "triples.nt",
               "entities.csv", "relationships.csv", "derived.json")


def generated_paths(project, only=None):
    """Every path the stages own, as absolute paths; with `only`, the paths those stages own.

    The layout is the authority. The graph directory is entirely generated, but the files are
    named individually so the transaction can restore exactly what it stashed.

    The corpus is absent: it is produced by ingest from the inbox, not by the compile stages, and a
    test asserts that.
    """
    layout = project.layout
    graph_files = [os.path.join(layout.graph, name) for name in GRAPH_FILES]
    owns = {"knowledge": [layout.entities] + graph_files, "rules": graph_files, "ontology": [layout.ontology],
            "semantic": [layout.cards], "sqlite": [layout.database], "neo4j": [], "site": [layout.site]}
    out = []
    for name, _path in STAGES:
        if only and name not in only:
            continue
        for path in owns[name]:
            if path not in out:
                out.append(path)
    return out


STAGES = (
    ("knowledge", "oto.compile.knowledge"),
    ("rules", "oto.compile.rules"),
    ("ontology", "oto.compile.ontology"),
    ("semantic", "oto.compile.semantic"),
    ("sqlite", "oto.targets.sqlite"),
    ("neo4j", "oto.targets.neo4j"),          # optional: skipped unless the project configures it
    ("site", "oto.targets.site"),            # optional: the static site, when targeted
)


def _save_dir(project):
    return os.path.join(project.src, SAVE_DIR)


def _stash(project, only=None):
    """Rename each generated artifact aside. Returns the paths actually saved, as (source, saved)."""
    saved = []
    save_root = _save_dir(project)
    if os.path.exists(save_root):
        shutil.rmtree(save_root)                  # a leftover from a hard kill
    for index, source in enumerate(generated_paths(project, only)):
        if not os.path.exists(source):
            continue
        # Flat numbered slots: the paths may sit in different trees, so their names can collide.
        target = os.path.join(save_root, "%02d-%s" % (index, os.path.basename(source)))
        os.makedirs(save_root, exist_ok=True)
        os.rename(source, target)
        saved.append((source, target))
    return saved


def _restore(project, saved):
    for source, stashed in saved:
        if os.path.isdir(source):
            shutil.rmtree(source)
        elif os.path.exists(source):
            os.remove(source)
        os.makedirs(os.path.dirname(source), exist_ok=True)
        os.rename(stashed, source)
    shutil.rmtree(_save_dir(project), ignore_errors=True)


def _discard(project):
    shutil.rmtree(_save_dir(project), ignore_errors=True)


def build(project, only=None, transactional=True):
    """Run the stages. Returns the list of stage names that ran."""
    stages = [(name, path) for name, path in STAGES if not only or name in only]

    if not transactional:
        for name, path in stages:
            print("--- %s" % name)
            importlib.import_module(path).run(project)
        return [n for n, _ in stages]

    saved = _stash(project, only)
    try:
        for name, path in stages:
            print("--- %s" % name)
            importlib.import_module(path).run(project)
    except BaseException:
        print("build failed; restoring the previous build")
        _restore(project, saved)
        raise
    _discard(project)
    return [n for n, _ in stages]

def clean(project, dry_run=False):
    """Delete everything the build owns. Returns the paths removed.

    The whole build directory is generated, so it goes in one step. That is only safe because the
    layout keeps authored files out of it; a layout that mixed them destroyed authored work once
    during development, which is why it no longer exists.
    """
    build_root = project.layout.build_root()
    targets = [build_root] if os.path.isdir(build_root) else []

    if dry_run:
        return targets
    for path in targets:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    shutil.rmtree(_save_dir(project), ignore_errors=True)
    return targets
