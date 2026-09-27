# -*- coding: utf-8 -*-
"""Project resolution.

An OTO *project* holds data only. It never holds engine code. This module tells a compile stage
where that data lives, so a stage no longer derives paths from its own file location.

Two directories matter:

  data  the curated inputs: project.config.json, ontology.config.json, the curated graph
  src   the corpus and the generated layers under build/; see `layout.py`
"""
import json
import os

from . import layout as _layout

CONFIG_NAME = "project.config.json"
ONTOLOGY_CONFIG_NAME = "ontology.config.json"


class ProjectError(Exception):
    """The project layout or configuration is not usable."""


class Project:
    """Where a project's data lives, plus its identity config."""

    def __init__(self, data, src):
        self.data = os.path.abspath(data)
        self.src = os.path.abspath(src)
        self.options = {}                      # per-invocation switches a command sets, e.g. build targets
        self._layout = None
        if not os.path.isdir(self.data):
            raise ProjectError("data directory not found: %s" % self.data)
        if not os.path.isdir(self.src):
            # `oto clean` deletes the whole generated tree, so its absence is normal for a project
            # and must not lock every command out. Only a directory holding a project config is
            # a project, though: recreating build/ inside an arbitrary folder would be a surprise.
            if os.path.exists(os.path.join(self.data, CONFIG_NAME)):
                os.makedirs(self.src, exist_ok=True)
            else:
                raise ProjectError("not an OTO project: no %s in %s (run `oto init` there)"
                                   % (CONFIG_NAME, self.data))

    # ---- constructors ----
    @classmethod
    def standard(cls, root):
        """The layout `oto init` creates: data at the root, generated artifacts under build/."""
        return cls(data=root, src=os.path.join(root, "build"))

    # ---- layout ----
    @property
    def layout(self):
        """Where each artifact lives. Resolved once, because it depends on the database name."""
        if self._layout is None:
            self._layout = _layout.Layout(os.path.dirname(self.src), self.src, self.identity()["db_name"])
        return self._layout

    # ---- config ----
    @property
    def config_path(self):
        return os.path.join(self.data, CONFIG_NAME)

    @property
    def ontology_config_path(self):
        return os.path.join(self.data, ONTOLOGY_CONFIG_NAME)

    def config(self):
        """Identity config. Required: a missing config must fail, never fall back to a default."""
        if not os.path.exists(self.config_path):
            raise ProjectError(
                "%s not found in %s. Run `oto init` to create a project." % (CONFIG_NAME, self.data))
        with open(self.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        for key in ("slug", "name"):
            if not cfg.get(key):
                raise ProjectError("%s is missing the required key '%s'" % (CONFIG_NAME, key))
        return cfg

    # ---- the curated graph ----
    GRAPH_NAME = "graph.json"

    @property
    def graph_path(self):
        """Path to the curated graph."""
        candidate = os.path.join(self.data, self.GRAPH_NAME)
        if os.path.exists(candidate):
            return candidate
        raise ProjectError("no curated graph found in %s (looked for %s). Run `oto init` to create one."
                           % (self.data, self.GRAPH_NAME))

    def identity(self):
        """Normalized project identity. Every generated name derives from here.

        `slug` and `name` are required. The rest default from the slug, so multiple knowledge bases
        coexist on one machine without collisions. A stage must never carry its own default: that is
        how one project's vocabulary leaks into another's build.
        """
        cfg = self.config()
        slug = cfg["slug"]
        return {
            "slug": slug,
            "name": cfg["name"],
            "namespace": cfg.get("namespace") or "https://%s.example/kg/" % slug,
            "prefix": cfg.get("prefix") or slug,
            "db_name": cfg.get("db_name") or "%s.db" % slug,
            "server_name": cfg.get("server_name") or "%s-kg" % slug,
        }

    # ---- freshness ----
    def build_seq(self):
        """Monotonic freshness stamp, so a server can pick the fresher of two databases.

        Derived from the PROJECT, never from the engine's own file location. An installed engine
        lives in site-packages, which is not a git repository, so a `__file__`-based stamp would
        always be zero. Prefers the project's git HEAD commit time, which is deterministic per
        commit. Falls back to the newest modification time among the curated inputs, which keeps the
        stamp monotonic for a project that is not under git.
        """
        import subprocess
        for git in ("git", r"C:\\Program Files\\Git\\cmd\\git.exe"):
            try:
                r = subprocess.run([git, "-C", self.data, "show", "-s", "--format=%ct", "HEAD"],
                                   capture_output=True, text=True, timeout=10)
                if r.stdout.strip().isdigit():
                    return r.stdout.strip()
            except Exception:
                pass
        newest = 0
        for name in (CONFIG_NAME, ONTOLOGY_CONFIG_NAME, "graph.json"):
            path = os.path.join(self.data, name)
            if os.path.exists(path):
                newest = max(newest, int(os.path.getmtime(path)))
        return str(newest)

    def __repr__(self):
        return "Project(data=%r, src=%r)" % (self.data, self.src)
