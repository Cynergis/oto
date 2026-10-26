# -*- coding: utf-8 -*-
"""Connectors: how a built graph reaches a store, behind one interface the core calls.

OTO's model is store-neutral. A connector translates it into one store and says in its manifest what
that store can do. Two modes exist: **materialize**, OTO pushes nodes and edges into a store it owns
(SQLite, Neo4j); **overlay**, OTO reads a store that already exists, in place, and never copies a
row: its catalog, its query log, a read-only query. The overlay is the data semantic layer's way in
(roadmap C1): `oto data introspect` turns the catalog into Table and Column facts. SQLite is both,
the reference overlay every machine can run; Postgres (`postgres` extra) and BigQuery (`bigquery`
extra) are overlays. The build stages, `oto data` and the served `kg_read` call connectors and
nothing else of OTO talks to a store directly.

    MANIFEST        name, version, modes, query_language, capabilities, auth, conformance ("kit@N")
    settings        what the project config says about the store
    connect / close a session: a path, a driver
    apply_schema    the vocabulary compiled to the store's constraints and indexes; applying the
                    same vocabulary again changes nothing (schema_snapshot proves it)
    plan            everything one build writes, as rows, from the project's build directory
    publish         the plan into the store, idempotent, keyed by the stable id every IRI derives from
    read_back       what differs between the store and the plan, [] when nothing
    snapshot        the store's contents in one canonical shape, to compare two publishes or two stores
    drop            a plan without one node and its edges, for the retirement check

    introspect      (overlay) the store's catalog: tables and views, columns with type, nullability,
                    key and the column a foreign key references; the same catalog read twice is equal
    query_log       (overlay) what was asked of the store, when the store keeps a log; [] when it does not
    native_read     (overlay) one read-only query, refused unless it is a SELECT and cannot write

A connector is listed (`oto connectors`) only with a manifest that validates and a conformance run
(`conformance.py`): round trip, idempotency, IRI stability across two stores, retirement. The suite
runs the kit for SQLite on every machine and for Neo4j where one is reachable (CI's neo4j job).
"""
import importlib
import re

KIT_VERSION = 1
MODES = ("materialize", "overlay")
CAPABILITIES = ("named_graphs", "schema_constraints", "transactions", "vector_index", "full_text")
MANIFEST_KEYS = ("name", "version", "modes", "query_language", "capabilities", "auth", "conformance")
METHODS = ("settings", "connect", "close", "apply_schema", "schema_snapshot", "plan", "publish", "read_back", "snapshot", "drop")
SESSION_METHODS = ("settings", "connect", "close")                 # every mode opens a session
MATERIALIZE_METHODS = ("apply_schema", "schema_snapshot", "plan", "publish", "read_back", "snapshot", "drop")
OVERLAY_METHODS = ("introspect", "query_log", "native_read")
REGISTRY = {"bigquery": "oto.connectors.bigquery", "neo4j": "oto.connectors.neo4j", "postgres": "oto.connectors.postgres",
            "sqlite": "oto.connectors.sqlite"}


def select_only(sql):
    """The one statement a native read may run, cleaned: a SELECT (or a WITH that selects), alone.
    ValueError, in words, for anything else; the store's own read-only mode then catches what the
    words let through."""
    text = (sql or "").strip().rstrip(";").strip()
    if ";" in text:
        raise ValueError("read-only: one statement at a time")
    if not re.match(r"(?is)^(select|with)\b", text):
        raise ValueError("read-only: a native read is a SELECT (or a WITH ... SELECT); %r is not" % text[:40])
    return text


class Connector:
    """The interface. A connector subclasses it and implements every method; `interface_problems`
    names what one left out."""
    name = None
    MANIFEST = {}

    def settings(self, project):
        raise NotImplementedError

    def connect(self, settings):
        raise NotImplementedError

    def close(self, session):
        raise NotImplementedError

    def apply_schema(self, session, vocabulary):
        raise NotImplementedError

    def schema_snapshot(self, session):
        raise NotImplementedError

    def plan(self, project):
        raise NotImplementedError

    def publish(self, session, plan):
        raise NotImplementedError

    def read_back(self, session, plan):
        raise NotImplementedError

    def snapshot(self, session, plan):
        raise NotImplementedError

    def drop(self, plan, node_id):
        raise NotImplementedError

    # ---- overlay ----
    def introspect(self, session):
        """{"store": name, "tables": [{"name", "kind": table|view, "columns": [{"name", "type", "nullable", "key", "references"}]}]}, sorted."""
        raise NotImplementedError

    def query_log(self, session, since=None):
        """[{"at", "sql", ...}] the store recorded, or [] when it keeps no log."""
        raise NotImplementedError

    def native_read(self, session, sql, limit=100):
        """{"columns", "rows", "truncated"} for one SELECT; ValueError for anything that could write."""
        raise NotImplementedError

    def from_deploy(self, project, overlay):
        """Settings from the deploy config's `overlay` section (oto/deploy.py); the project's own
        settings when the connector has nothing to read there."""
        return self.settings(project)


def manifest_problems(manifest):
    """What is wrong with a manifest, in words. [] when it validates."""
    if not isinstance(manifest, dict):
        return ["the manifest must be an object"]
    out = []
    for key in MANIFEST_KEYS:
        if key not in manifest:
            out.append("`%s` is required" % key)
    if "modes" in manifest:
        modes = manifest["modes"]
        if not isinstance(modes, list) or not modes:
            out.append("`modes` needs at least one mode: %s" % " or ".join(MODES))
        else:
            for mode in modes:
                if mode not in MODES:
                    out.append("mode %r is not one of %s" % (mode, ", ".join(MODES)))
    capabilities = manifest.get("capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, dict):
            out.append("`capabilities` must be an object of true or false")
        else:
            for key, value in capabilities.items():
                if key not in CAPABILITIES:
                    out.append("unknown capability %r (the kit knows %s)" % (key, ", ".join(CAPABILITIES)))
                elif not isinstance(value, bool):
                    out.append("capability %r must be true or false" % key)
    if "auth" in manifest and not (isinstance(manifest["auth"], list) and all(isinstance(a, str) for a in manifest["auth"])):
        out.append("`auth` must be a list of methods")
    conformance = manifest.get("conformance")
    if conformance is not None and conformance != "kit@%d" % KIT_VERSION:
        out.append("`conformance` must be %r, the kit this connector passed" % ("kit@%d" % KIT_VERSION))
    for key in ("name", "version", "query_language"):
        if key in manifest and not (isinstance(manifest[key], str) and manifest[key]):
            out.append("`%s` must be a non-empty string" % key)
    return out


def interface_problems(connector):
    """The methods a connector does not implement of the modes its manifest declares: a session
    always, the materialize methods for `materialize`, the overlay methods for `overlay`."""
    cls = connector if isinstance(connector, type) else type(connector)
    modes = (getattr(connector, "MANIFEST", None) or {}).get("modes") or list(MODES)
    wanted = list(SESSION_METHODS)
    if "materialize" in modes:
        wanted += MATERIALIZE_METHODS
    if "overlay" in modes:
        wanted += OVERLAY_METHODS
    return ["%s does not implement %s (%s)" % (getattr(connector, "name", None) or cls.__name__, method,
                                              "overlay" if method in OVERLAY_METHODS else "materialize" if method in MATERIALIZE_METHODS else "session")
            for method in wanted if getattr(cls, method, None) is getattr(Connector, method)]


def available():
    """The connectors shipped, by name."""
    return sorted(REGISTRY)


def get(name):
    """One connector, an instance, or None."""
    module = REGISTRY.get(name)
    if not module:
        return None
    return importlib.import_module(module).connector()
