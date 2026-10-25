# -*- coding: utf-8 -*-
"""Connectors: how a built graph reaches a store, behind one interface the core calls.

OTO's model is store-neutral. A connector translates it into one store and says in its manifest what
that store can do. Two modes exist: **materialize**, OTO pushes nodes and edges into a store it owns
(SQLite, Neo4j); **overlay**, OTO defines a graph over tables that already exist (BigQuery graph,
Postgres), the data semantic layer's way in. This package ships the materialize connectors; the
build stages call them and nothing else of OTO talks to a store directly.

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

A connector is listed (`oto connectors`) only with a manifest that validates and a conformance run
(`conformance.py`): round trip, idempotency, IRI stability across two stores, retirement. The suite
runs the kit for SQLite on every machine and for Neo4j where one is reachable (CI's neo4j job).
"""
import importlib

KIT_VERSION = 1
MODES = ("materialize", "overlay")
CAPABILITIES = ("named_graphs", "schema_constraints", "transactions", "vector_index", "full_text")
MANIFEST_KEYS = ("name", "version", "modes", "query_language", "capabilities", "auth", "conformance")
METHODS = ("settings", "connect", "close", "apply_schema", "schema_snapshot", "plan", "publish", "read_back", "snapshot", "drop")
REGISTRY = {"neo4j": "oto.connectors.neo4j", "sqlite": "oto.connectors.sqlite"}


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
    """The methods a connector class or instance does not implement."""
    cls = connector if isinstance(connector, type) else type(connector)
    return ["%s does not implement %s" % (getattr(connector, "name", None) or cls.__name__, method)
            for method in METHODS if getattr(cls, method, None) is getattr(Connector, method)]


def available():
    """The connectors shipped, by name."""
    return sorted(REGISTRY)


def get(name):
    """One connector, an instance, or None."""
    module = REGISTRY.get(name)
    if not module:
        return None
    return importlib.import_module(module).connector()
