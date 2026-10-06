"""Warm query engine over an OTO knowledge store: SQLite, or a self-hosted Neo4j.

Every answer is text built from rows, and every row comes from one store interface (`store.py`)
with two implementations. The SQLite store is loaded ONCE into memory and the file released, so a
rebuild can swap the file under a running server; before each query the engine stats the file and
reloads if it changed. The Neo4j store is a live connection to the production graph: a load
retires the previous build in place, so it is always current, and one server can be shared.

The backend is chosen at startup, in this order: `OTO_STORE` in the environment (`oto serve
--backend` sets it), then `"serve": {"backend": "neo4j"}` in the project config, then SQLite.
With Neo4j the engine verifies the connection at startup and says so on stderr; if the database
is unreachable it keeps running, answers every call with the reason, and retries the connection on
the next call. It never falls back to SQLite on its own: a production setting that silently served
a stale local file would be worse than an honest error.

Stdlib only for SQLite; the `neo4j` extra for Neo4j. A hand-rolled JSON-RPC 2.0 loop over stdin
and stdout, no MCP package. All diagnostics go to stderr, so stdout stays a clean protocol channel.

Two modes, one implementation:

  server   newline-delimited JSON-RPC 2.0 over stdio, for a host that speaks MCP
  CLI      one query per invocation, for a host where the shell is allowed but tool calls are gated

Every tool is temporality-aware and returns current facts by default.
"""
import os, sys, json, sqlite3, re

from .store import SqliteStore, Neo4jStore
from ..model import vocabulary as _vocab

# MCP requires UTF-8; Windows consoles default to cp1252 which breaks chars like "→".
try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
except Exception:
    pass

# ---- project identity and database resolution ----
# Nothing here derives from this file's location. An installed engine lives in site-packages, so a
# `__file__`-relative lookup would resolve to the wrong place, or to nothing at all.
#
# Identity comes from a project config named by OTO_PROJECT_CONFIG. Without one the engine still
# runs, using neutral names, so pointing OTO_DB at a database is enough to query it.
def _load_project_cfg():
    path = os.environ.get("OTO_PROJECT_CONFIG")
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}

_pcfg = _load_project_cfg()
#: The project's root, when the config lives in a project (not in a published store checkout):
#: the pending lane reads proposals and the candidate from there. None otherwise.
PROJECT_ROOT = None
if os.environ.get("OTO_PROJECT_CONFIG") and os.path.exists(os.path.join(os.path.dirname(os.path.abspath(os.environ["OTO_PROJECT_CONFIG"])), "ontology.config.json")):
    PROJECT_ROOT = os.path.dirname(os.path.abspath(os.environ["OTO_PROJECT_CONFIG"]))
#: How the store is being served: live, or a preview (built on command, or on every change).
MODE = {"regime": "live"}
SLUG = _pcfg.get("slug") or "oto"
NAME = _pcfg.get("name") or "OTO"
SERVER_NAME = _pcfg.get("server_name") or ("%s-kg" % SLUG)
DB_NAME = _pcfg.get("db_name") or ("%s.db" % SLUG)
CACHE_DIR = os.path.expanduser(_pcfg.get("cache_dir") or ("~/.%s-kg" % SLUG))
ENV_DB = "%s_DB" % SLUG.upper()          # e.g. ACME_DB; kept for existing installs
BACKENDS = ("sqlite", "neo4j")
BACKEND = (os.environ.get("OTO_STORE") or (_pcfg.get("serve") or {}).get("backend") or "sqlite").lower()
if BACKEND not in BACKENDS:
    sys.stderr.write("%s: unknown store backend %r; serving sqlite\n" % (SERVER_NAME, BACKEND))
    BACKEND = "sqlite"


#: The highest database shape this engine understands. Keep in step with
#: `oto.targets.sqlite.SCHEMA_VERSION`, and read the reasoning there.
UNDERSTOOD_SCHEMA = 6


def _meta(path, key, default=None):
    """One value from the meta table, or `default` if the database or the row is not there."""
    try:
        c = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True)
        r = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        c.close()
        return r[0] if r else default
    except Exception:
        return default


def _db_seq(path):
    """Freshness stamp written by the sqlite target. Higher means newer content."""
    value = _meta(path, "build_seq")
    return int(value) if value is not None and str(value).isdigit() else -1


def _db_schema(path):
    """The database shape. 0 means a build from before versioning, which is readable."""
    value = _meta(path, "schema_version")
    return int(value) if value is not None and str(value).isdigit() else 0


def schema_complaint(path):
    """Why this engine must not answer from this database, or None.

    Refuse the future, tolerate the past. A database newer than the engine may hold columns whose
    meaning changed, and answering from it would produce confident wrong answers rather than an
    error. An older or unversioned database still contains what this engine knows how to read.
    """
    found = _db_schema(path)
    if found > UNDERSTOOD_SCHEMA:
        return ("%s was built with database schema %d, and this engine understands %d. Answering "
                "from it could produce wrong answers rather than errors, so it will not. Upgrade "
                "the engine, or rebuild with a matching version."
                % (path, found, UNDERSTOOD_SCHEMA))
    return None


def _resolve_db():
    """OTO_DB wins, then <SLUG>_DB, then the synced cache directory.

    Returning the cache path when nothing exists is deliberate: startup then reports "no database
    yet" instead of silently answering from stale data.
    """
    for var in ("OTO_DB", ENV_DB):
        value = os.environ.get(var)
        if value:
            return value
    return os.path.join(CACHE_DIR, DB_NAME)


DB = _resolve_db()
#: A refusal is recorded, not raised at import: the module is imported by tools that never query.
#: Every entry point checks it, so nothing answers from a database it cannot read.
DB_REFUSAL = schema_complaint(DB) if BACKEND == "sqlite" and DB and os.path.exists(DB) else None
#: Why the Neo4j store is not serving, when it is not: unreachable, unloaded, or from the future.
NEO4J_COMPLAINT = None
try:
    if BACKEND == "neo4j":
        pass                                              # reported by ensure_fresh() below
    elif DB_REFUSAL:
        sys.stderr.write("%s: REFUSING %s\n  %s\n" % (SERVER_NAME, DB, DB_REFUSAL))
    elif DB and os.path.exists(DB):
        sys.stderr.write("%s: serving %s (build_seq=%s, schema=%s)\n"
                         % (SERVER_NAME, DB, _db_seq(DB), _db_schema(DB)))
    else:
        sys.stderr.write("%s: no knowledge database at %s. Build one with `oto build`, or set "
                         "OTO_DB.\n" % (SERVER_NAME, DB))
except Exception:
    pass
SERVER_INFO = {"name": SERVER_NAME, "version": "2.1.0"}   # 2.1.0: store interface, Neo4j backend
DEFAULT_PROTOCOL = "2024-11-05"


def log(*a):
    print("[%s]" % SERVER_NAME, *a, file=sys.stderr, flush=True)


# ---- the warm store, with AUTO-REFRESH ----
# SQLite: the store is an in-memory copy and the file handle is released at once; before each query
# the file is stat()ed and reloaded if it changed (atomic rebuild swap, git pull) or appeared since
# startup, so a fresh build is served on the next call with no restart. Holding the file open would
# lock it on Windows and the build could not replace it. The check is one stat(); a reload happens
# only when the file actually changes.
# Neo4j: the store is a live connection, current by construction. A failed connection is retried
# on the next call, so a server started before the database came up recovers by itself.
STORE = None
_db_sig = None        # (path, mtime_ns, size) of the currently-loaded sqlite file
_pinned = False       # True when a caller installed a store with use(); freshness checks are then off


def use(store):
    """Serve from this store and stop watching the filesystem. For tests and embedders."""
    global STORE, _pinned
    STORE, _pinned = store, store is not None


def _sig(path):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _open_db(path):
    global STORE, _db_sig, DB_REFUSAL
    # Checked on every open, not only at startup: a rebuild while the server runs can hand it a
    # newer schema, and that is exactly when refusing matters. The previous database stays loaded.
    DB_REFUSAL = schema_complaint(path)
    if DB_REFUSAL:
        log("refusing", path, DB_REFUSAL)
        return
    try:
        sig = _sig(path)                                          # stamp before the brief read
        fresh = SqliteStore(path)
        old, STORE, _db_sig = STORE, fresh, sig
        if old is not None:
            old.close()
        log("loaded into memory:", path)
    except Exception as e:
        log("failed to open DB", path, repr(e))


def _open_neo4j():
    """Connect, check the project is loaded and its schema readable; record why when not."""
    global STORE, NEO4J_COMPLAINT
    try:
        store = Neo4jStore.from_config(_pcfg, SLUG)
    except ValueError as exc:
        NEO4J_COMPLAINT = str(exc)
        log("neo4j:", NEO4J_COMPLAINT)
        return
    try:
        store.ping()
    except Exception as exc:                                   # noqa: BLE001 - the driver's own hierarchy
        NEO4J_COMPLAINT = "cannot reach Neo4j at %s: %s" % (store.uri, exc)
        store.close()
        log("neo4j:", NEO4J_COMPLAINT)
        return
    if not store.loaded():
        NEO4J_COMPLAINT = ("Neo4j at %s (%s) holds no load of project %r yet. Run `oto build --target neo4j`."
                           % (store.uri, store.database, SLUG))
        store.close()
        log("neo4j:", NEO4J_COMPLAINT)
        return
    schema = store.meta("schema_version")
    found = int(schema) if schema is not None and str(schema).isdigit() else 0
    if found > UNDERSTOOD_SCHEMA:
        NEO4J_COMPLAINT = ("Neo4j holds project %r at schema %d and this engine understands %d. Upgrade the engine, "
                           "or reload with a matching version." % (SLUG, found, UNDERSTOOD_SCHEMA))
        store.close()
        log("neo4j: REFUSING", NEO4J_COMPLAINT)
        return
    old, STORE, NEO4J_COMPLAINT = STORE, store, None
    if old is not None:
        old.close()
    log("serving Neo4j %s (%s), project %s, build_seq=%s, schema=%s"
        % (store.uri, store.database, SLUG, store.meta("build_seq"), schema))


def ensure_fresh():
    """Make the store current: reload a changed sqlite file, or connect to Neo4j if not yet
    connected. A cheap no-op when nothing changed. Re-resolves the sqlite path each time so a
    higher-priority db (env / local) that shows up later is picked up too."""
    global DB
    if _pinned:
        return
    if BACKEND == "neo4j":
        if STORE is None:
            _open_neo4j()
        return
    path = _resolve_db()
    cur = _sig(path)
    if cur is None:
        return            # not present right now (e.g. mid-swap) — keep serving what we have
    if STORE is None or cur != _db_sig:
        DB = path
        _open_db(path)


ensure_fresh()            # initial load
if STORE is None and BACKEND == "sqlite":
    log("DB not found:", DB, "- build one with `oto build`, or `oto sync --repo <query repository>`; "
        "it will load on the next query (no restart).")


def no_data_message():
    """Why there is nothing to answer from, computed at use time.

    Each cause needs its own instruction. An absent database means build one. A refused database
    means the file is there and this engine is the stale part, so telling the reader to rebuild
    would send them the wrong way. An unreachable Neo4j is an operations problem, not a build one.
    """
    if BACKEND == "neo4j":
        return ("%s serves from Neo4j and cannot right now:\n  %s\nThe engine retries on every call. "
                "To serve the local build instead, start it with `--backend sqlite` (or OTO_STORE=sqlite)."
                % (NAME, NEO4J_COMPLAINT or "not connected"))
    if DB_REFUSAL:
        return ("%s has a knowledge database that this engine will not read:\n  %s\n"
                "Fix: upgrade the engine, or rebuild the database with a matching version. "
                "Rebuilding with this engine will not help." % (NAME, DB_REFUSAL))
    return ("%s has no knowledge database yet. The engine looked for:\n"
            "  %s\n"
            "Fix: run `oto build` in the project, or set OTO_DB to an existing %s. The engine picks "
            "it up on the next query, with no restart." % (NAME, DB, DB_NAME))


# ============================ the vocabulary, as the store carries it ============================
_vocabulary = (None, None)        # (the store it was read from, the Vocabulary)


def vocabulary():
    """What the terms are called and mean, read once per loaded store."""
    global _vocabulary
    if _vocabulary[0] is not STORE:
        from ..model.terms import Vocabulary
        _vocabulary = (STORE, Vocabulary.of_store(STORE))
    return _vocabulary[1]


# ============================ query helpers (return text) ============================
def node(nid):
    return STORE.node(nid)


def label(nid):
    return STORE.label(nid)


def resolve(term, prefer_current=True):
    if node(term):
        return term, []
    ids = STORE.by_name(term)
    if ids:
        return ids[0], ids[1:6]
    ids = STORE.by_text(term, 6)
    return (ids[0], ids[1:]) if ids else (None, [])


def valid_on(n, date):
    if n["valid_from"] and date < n["valid_from"]:
        return False
    if n["valid_to"] and date >= n["valid_to"]:
        return False
    return True


def entity_text(term, history=False, as_of=None):
    nid, alts = resolve(term, prefer_current=(as_of is None))
    if not nid:
        return f"No entity matched '{term}'. Try kg_search for passages, or kg_stale."
    return _card(nid, history, None, as_of) + (
        ("\n\nOther matches: " + ", ".join(f"{label(a)} ({a})" for a in alts)) if alts else "")


def relation_name(rel):
    """A relation as the caller names it, by name or by label ("part of" is part_of)."""
    if not rel:
        return rel
    words = vocabulary()
    if rel in words.relations:
        return rel
    names = [key for kind, key in words.find(rel) if kind == "relation"]
    return names[0] if names else rel


def neighbors_text(term, rel=None):
    nid, _ = resolve(term)
    if not nid:
        return f"No entity matched '{term}'."
    rels = vocabulary().relation_covers(relation_name(rel)) if rel else None
    return _card(nid, False, (rels[0] if len(rels) == 1 else rels) if rels else None, None)


def _card(nid, history, rel, as_of):
    n = node(nid)
    words = vocabulary()
    L = [f"=== {n['label']}  [{words.classed(n['type'])}]  ({nid}) ==="]
    if n["status"] == "superseded" and not history and not as_of and n["superseded_by"] and node(n["superseded_by"]):
        L.append(f"⚠️ SUPERSEDED (valid_to={n['valid_to']}). Current → {label(n['superseded_by'])}. Showing current.")
        return "\n".join(L) + "\n\n" + _card(n["superseded_by"], history, rel, as_of)
    prov = [f"status={n['status']}"] + [f"{k}={n[k]}" for k in
            ("as_of", "valid_from", "valid_to", "source_doc") if n[k]]
    L.append("  ·  ".join(prov))
    if n["status"] == "intended":
        L.append("🔵 INTENDED: asserted as a plan, not yet observed. Not the current state; an action's "
                 "recorded run is what would make it so (kg_actions).")
    al = STORE.aliases(nid)
    ancestors = words.ancestors(n["type"])
    if al or ancestors:
        L.append("  ·  ".join(x for x in ("aka: " + ", ".join(dict.fromkeys(al)) if al else "",
                                          "a kind of " + ", ".join(ancestors) if ancestors else "") if x))
    if n["summary"]:
        L.append("\n" + n["summary"])
    attrs = json.loads(n["attributes"] or "{}")
    if attrs:
        L.append("\nAttributes:")
        L += [f"  - {words.attribute_label(n['type'], k)}: {words.value_text(n['type'], k, v)}" for k, v in attrs.items() if v not in (None, "", [], {})]

    def keep(o):
        m = node(o)
        if not m:
            return True
        if as_of is not None:
            return valid_on(m, as_of)
        return history or m["status"] != "superseded"

    derived_marks = "derived" in STORE.features()

    def mark(e):
        """A derived edge says so, with the rule; kg_explain gives the chain."""
        return f"  [derived by {e['derived_by']}]" if derived_marks and e.get("derived_by") else ""

    out = [(e["rel"], e["dst"], mark(e)) for e in STORE.edges_out(nid, rel)
           if (history or as_of is not None or e["status"] != "superseded") and keep(e["dst"])]
    inc = [(e["rel"], e["src"], mark(e)) for e in STORE.edges_in(nid, rel)
           if (history or as_of is not None or e["status"] != "superseded") and keep(e["src"])]
    # Each relation reads as the vocabulary labels it; an incoming edge reads from this entity's
    # side when the relation declares an inverse ("contains → Payment API"), and as the other
    # entity's statement otherwise ("Payments team → owns").
    if out:
        L.append("\nRelationships (outgoing):")
        L += [f"  {words.relation_label(rl)} → {label(t)}"
              + ("" if node(t) and node(t)['status'] == 'current' else f"  [{node(t)['status']}]" if node(t) else "") + m
              for rl, t, m in out[:50]]
    if inc:
        L.append("\nRelationships (incoming):")
        L += [(f"  {words.inverse_label(rl)} → {label(s)}" if words.inverse_label(rl) else f"  {label(s)} → {words.relation_label(rl)}") + m
              for rl, s, m in inc[:50]]
    rows = STORE.derived_attributes(nid)
    if rows:
        L.append("\nAttributes (derived):")
        L += [f"  - {r['name']}: {json.loads(r['value'])}  [derived by {r['derived_by']}]" for r in rows]
    if history:
        preds = STORE.predecessors(nid)
        if n["supersedes"]:
            sv = json.loads(n["supersedes"]); preds += sv if isinstance(sv, list) else [sv]
        preds = [p for p in dict.fromkeys(preds) if node(p)]
        if preds:
            L.append("\nHistory (superseded predecessors):")
            L += [f"  - {node(p)['label']} ({p})  valid {node(p)['valid_from']}→{node(p)['valid_to']}" for p in preds]
    src = json.loads(n["sources"] or "[]")
    if src:
        L.append("\nSources: " + ", ".join(src))
    # Schema 1 databases have no evidence column; they still answer, just without the locator.
    evidence = json.loads(n["evidence"] or "[]") if "evidence" in n.keys() else []
    if evidence:
        L.append("\nEvidence:")
        for item in evidence:
            where = f" {item['where']}" if item.get("where") else ""
            quote = f': "{item["quote"]}"' if item.get("quote") else ""
            L.append(f"  - {item.get('doc', '?')}{where}{quote}")
    return "\n".join(L)


def define_text(term):
    """What a class, relation or attribute is called and means, with the reasoning behind it."""
    words = vocabulary()
    found = words.find(term)
    if not found:
        known = sorted(set(list(words.classes) + list(words.relations)))
        return (f"No class, relation or attribute is called '{term}'. The vocabulary declares: "
                + (", ".join(known) if known else "nothing the store carries (built without a vocabulary?)") + ".")
    out = []
    for kind, key in found:
        d = words.describe(kind, key)
        head = d["name"] if not d["owner"] else f"{d['owner']}.{d['name']}"
        if kind == "concept":
            head = f"{d['owner']}.{d['name']}"
        out.append(f"=== {d['labels'].get(words.language) or d['name']}  [{kind} {head}]" + (f"  <{d['iri']}>" if d.get("iri") else "") + " ===")
        if len(d["labels"]) > 1 or d["alt_labels"]:
            out.append("labels: " + "; ".join(f"{lang} \"{text}\"" for lang, text in d["labels"].items())
                       + ("".join(f"; also {lang} " + ", ".join(f"\"{x}\"" for x in items) for lang, items in d["alt_labels"].items())))
        if d.get("definition"):
            out.append("definition: " + d["definition"].get(words.language, next(iter(d["definition"].values()))))
        for field, title in (("scope_note", "scope"), ("example", "example")):
            if d.get(field):
                out.append(f"{title}: " + d[field].get(words.language, next(iter(d[field].values()))))
        if kind == "relation":
            arrow = f"from: {d.get('domain') or 'any class'}  →  to: {d.get('range') or 'any class'}"
            if d.get("inverse"):
                arrow += f"\ninverse: {d['inverse']} (\"{d['inverse_label'].get(words.language, '')}\")"
            out.append(arrow)
            if d.get("specialises"):
                out.append("specialises: " + ", ".join(d["specialises"]))
            if d.get("specialised_by"):
                out.append("specialised by: " + ", ".join(d["specialised_by"]))
            counts = {r["rel"]: r["c"] for r in STORE.rels_counts(10000)}
            own = counts.get(d["name"], 0)
            under = sum(counts.get(r, 0) for r in d.get("specialised_by") or [])
            out.append(f"in the graph: {own} edge(s)" + (f", {own + under} with the relations that specialise it" if under else ""))
        elif kind == "class":
            if d.get("ancestors"):
                out.append("a kind of: " + ", ".join(d["ancestors"]))
            if d.get("kinds"):
                out.append("kinds of it: " + ", ".join(d["kinds"]))
            own = STORE.count(d["name"])
            covered = STORE.count(words.covers(d["name"])) if d.get("kinds") else own
            out.append(f"in the graph: {own} node(s)" + (f", {covered} with the kinds of it" if d.get("kinds") else ""))
        elif kind == "attribute":
            out.append(f"type: {d.get('type')}  ·  declared on {d['owner']}")
        elif kind == "temporal":
            out.append(f"type: {d.get('type')}  ·  a temporal field every fact may carry")
        elif kind == "scheme":
            out.append("concepts:")
            out += [f"  - {c['key']}: {c['label']}" + (f" — {c['definition']}" if c["definition"] else "")
                    + (f"  (narrower than {c['broader']})" if c.get("broader") else "") for c in d["concepts"]]
            out.append("values of: " + ", ".join(f"{o}.{a}" for o, a in d["used_by"]) if d["used_by"] else "values of: no attribute yet")
        elif kind == "concept":
            out.append(f"a concept of {d['owner']}" + (f", narrower than {', '.join(d['broader'])}" if d["broader"] else "")
                       + (f"; narrower concepts: {', '.join(d['narrower'])}" if d["narrower"] else ""))
            used = [f"{STORE.count(words.covers(owner), None, attr, d['name'])} {owner}" for owner, attr in d["used_by"]]
            out.append("in the graph: " + (", ".join(used) if used else "no attribute takes it"))
        why = d["rationale"]
        if why.get("question") or why.get("why"):
            out.append("why it exists: " + (why.get("why") or "").strip())
            if why.get("question"):
                out.append("the question it answers: " + why["question"].strip())
            if why.get("alternatives"):
                out.append("alternatives considered: " + why["alternatives"].strip())
            out.append("confirmed by: " + (why.get("validated_by").strip() if (why.get("validated_by") or "").strip()
                                           else "nobody yet (validated_by is empty)"))
        elif kind == "class":
            out.append("why it exists: not recorded (ontology.rationale.json)")
        out.append("")
    return "\n".join(out).rstrip()


def search_text(query, n=8):
    rows = STORE.search(query, int(n))
    if not rows:
        return f"No passages matched '{query}'."
    return f"Passage search: {query}\n" + "\n".join(
        f"  {r['r']:.3f}  {r['title'][:58]:<58}  {r['path']}" for r in rows)


def kinds_of(type_):
    """The classes a question about `type_` covers, by name or label."""
    words = vocabulary()
    if type_ not in words.classes:
        found = [key for kind, key in words.find(type_) if kind == "class"]
        type_ = found[0] if found else type_
    return type_, words.covers(type_)


def by_type_text(type_, state=None, limit=50):
    type_, kinds = kinds_of(type_)
    rows = STORE.by_type(kinds, state, int(limit))
    if not rows:
        return f"No nodes of type '{type_}'" + (f" with state '{state}'" if state else "") + "."
    head = f"{type_} ({len(rows)}" + (f"; covers {', '.join(k for k in kinds if k != type_)}" if len(kinds) > 1 else "") + "):"
    return head + "\n" + "\n".join(
        f"  {r['label']}  ({r['id']})" + (f"  [{r['type']}]" if len(kinds) > 1 else "")
        + ("" if r['status'] == 'current' else f"  [{r['status']}]") for r in rows)


def stale_text():
    sc = STORE.status_counts()
    out = ["status_counts: " + ", ".join(f"{r['status']}={r['c']}" for r in sc)]
    sup = STORE.superseded()
    out.append(f"Superseded ({len(sup)}):")
    out += [f"  - {r['label']} ({r['id']})  valid_to={r['valid_to']} → {r['superseded_by'] or '?'}" for r in sup] \
        or ["  (none — every fact is current)"]
    return "\n".join(out)


def explain_text(term, rel=None):
    """Why the graph holds a derived fact: the rule, then each premise down to its evidence."""
    nid, _alts = resolve(term)
    if not nid or not node(nid):
        return f"'{term}' does not resolve to an entity."
    if "derived" not in STORE.features():
        return "This store predates rules; rebuild to record derivations."
    rows = STORE.derived_edges(nid, rel)
    attrs = STORE.derived_attributes(nid)
    if not rows and not attrs:
        return f"Nothing about {label(nid)} ({nid}) is derived; every fact shown is asserted by a document."
    L = [f"Derived facts about {label(nid)} ({nid}):"]

    def premise_lines(premises, indent):
        for p in json.loads(premises or "[]"):
            if " -" in p and "-> " in p:
                src, rest = p.split(" -", 1)
                relname, dst = rest.split("-> ", 1)
                row = STORE.edge(src, relname, dst)
                if row and row["status"] == "derived":
                    L.append(f"{indent}{p}  (derived by {row['derived_by']})")
                    premise_lines(row["premises"], indent + "  ")
                else:
                    L.append(f"{indent}{p}  (asserted)")
            else:
                n = node(p)
                if n:
                    ev = json.loads(n["evidence"] or "[]") if "evidence" in n.keys() else []
                    where = f"  source: {ev[0].get('doc', '')} {ev[0].get('where', '')}".rstrip() if ev else (
                        f"  source: {n['source_doc']}" if n["source_doc"] else "")
                    L.append(f"{indent}{p}  [{n['type']}] {n['label']}{where}")

    for r in rows:
        L.append(f"\n{r['src']} -{r['rel']}-> {r['dst']}  derived by rule {r['derived_by']}; rests on:")
        premise_lines(r["premises"], "  ")
    for r in attrs:
        L.append(f"\n{nid}.{r['name']} = {json.loads(r['value'])!r}  derived by rule {r['derived_by']}; rests on:")
        premise_lines(r["premises"], "  ")
    L.append("\nA derived fact is recomputed on every build; supersede a premise and it goes.")
    return "\n".join(L)


def policy_text(limit=50):
    rows = STORE.policy_findings(int(limit))
    if rows is None:
        return "This store predates rules; rebuild to record policy findings."
    if not rows:
        return "No policy findings: every rule of kind policy is satisfied."
    L = [f"Policy findings ({len(rows)}):"]
    for r in rows:
        who = f"{label(r['node_id'])} ({r['node_id']})" if r["node_id"] else "(graph)"
        L.append(f"  [{r['severity']:8s}] {r['rule']}: {who}: {r['message']}")
    return "\n".join(L)


def overview_text(limit=10):
    """The map of the whole graph, with no model involved: what it holds, what is most connected,
    what the corpus covers and how recent it is, what changed lately and what was retired.

    This is the deterministic half of a global question. The synthesis is the reader's, and the
    query-knowledge playbook says how to write it and how to label it.
    """
    L = []
    counts = STORE.counts()
    sc = STORE.status_counts()
    L.append(f"=== Overview: {counts['nodes']} nodes, {counts['edges']} edges  ("
             + ", ".join(f"{r['status']}={r['c']}" for r in sc) + ") ===")
    frontier = STORE.frontier()
    if frontier:
        L.append(f"most recent fact recorded: {frontier}")

    L.append("\nBy class (current facts):")
    for r in STORE.types_current():
        L.append(f"  {r['c']:5d}  {r['type']}")

    L.append("\nBy relation:")
    for r in STORE.rels_counts(limit):
        L.append(f"  {r['c']:5d}  {r['rel']}")

    L.append("\nMost connected (current):")
    for r in STORE.hubs(limit):
        L.append(f"  {r['degree']:4d}  {r['label']}  [{r['type']}]  ({r['id']})")

    tags = {}
    for text in STORE.tags_current():
        for t in json.loads(text or "[]"):
            tags[t] = tags.get(t, 0) + 1
    if tags:
        top = sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
        L.append("\nTop tags: " + ", ".join(f"{t} ({n})" for t, n in top))

    L.append("\nCorpus in the index:")
    for prefix in ("documents/", "notes/", "entities/", "cards/"):
        n = STORE.docs_count(prefix)
        if n:
            L.append(f"  {n:5d}  {prefix}")

    sup = counts["superseded"]
    L.append(f"\nSuperseded facts: {sup}" + ("  (kg_stale lists them with their successors)" if sup else ""))
    if "derived" in STORE.features():
        nf = counts["findings"]
        L.append(f"Derived by rules: {counts['derived_edges']} edge(s), {counts['derived_attributes']} attribute(s); "
                 f"policy findings: {nf}" + ("  (kg_policy lists them)" if nf else ""))

    rows = STORE.changelog(limit)
    if rows is not None:
        L.append("\nRecent changes (the ledger):" if rows else "\nRecent changes: none recorded")
        for r in rows:
            who = f"  by {r['by']}" if r["by"] else ""
            L.append(f"  {r['at']}  +{r['nodes_added']} nodes, {r['nodes_changed']} changed, "
                     f"+{r['edges_added']} edges{who}")
            for item in json.loads(r["retired"] or "[]")[:3]:
                L.append(f"      retired {item.get('id')} -> {item.get('superseded_by') or '?'}"
                         + (f": {item['change_note']}" if item.get("change_note") else ""))
            if r["note"]:
                L.append(f"      {r['note']}")
    L.append("\nThis is a map, not an answer. A synthesis drawn from it must say which of these facts "
             "it rests on.")
    return "\n".join(L)


def count_text(type_=None, tag=None, attr=None, value=None):
    key = re.sub(r"[^A-Za-z0-9_]", "", attr) if attr else None
    type_, kinds = kinds_of(type_) if type_ else (None, [])
    n = STORE.count(kinds or None, tag, key, value)
    covered = f" (covers {', '.join(k for k in kinds if k != type_)})" if len(kinds) > 1 else ""
    filt = ", ".join(p for p in (f"type={type_}{covered}" if type_ else None, f"tag~{tag}" if tag else None,
                                 f"{attr}={value}" if attr and value is not None else None) if p)
    return f"count = {n}" + (f"  ({filt})" if filt else "  (all nodes)")


def scheme_for(key, type_=None):
    """The scheme an attribute's values come from, on `type_` or on any class declaring it."""
    words = vocabulary()
    owners = [type_] if type_ else sorted({owner for owner, name in words.attributes if name == key})
    for owner in owners:
        scheme = words.scheme_of(owner, key)
        if scheme:
            return scheme
    return None


def group_by_rows(by, type_=None, tag=None, limit=200, level=None):
    """The groups, each value of a scheme read with its label; `level="top"` rolls a value up to
    the concept at the top of its broader chain."""
    key = re.sub(r"[^A-Za-z0-9_]", "", by or "")
    type_, kinds = kinds_of(type_) if type_ else (None, [])
    rows = STORE.group_by(key, kinds or None, tag, int(limit))
    words, scheme = vocabulary(), scheme_for(key, type_)
    if scheme and level == "top":
        rolled = {}
        for r in rows:
            top = words.top_of(scheme, r["g"]) if isinstance(r["g"], str) else r["g"]
            rolled[top] = rolled.get(top, 0) + r["c"]
        rows = sorted(({"g": g, "c": c} for g, c in rolled.items()), key=lambda r: (-r["c"], str(r["g"])))
    for r in rows:
        concept = words.concept(scheme, r["g"]) if scheme and isinstance(r["g"], str) else None
        r["label"] = _vocab.label(concept, r["g"], words.language, words.language) if concept is not None else None
    return key, type_, scheme, rows


def group_by_text(by, type_=None, tag=None, limit=200, level=None):
    """Aggregate: GROUP BY a node column (type/status) or an attribute key (e.g. state, region)."""
    key, type_, scheme, rows = group_by_rows(by, type_, tag, limit, level)
    if not rows:
        return f"No nodes to group by '{by}'" + (f" (type={type_})" if type_ else "") + "."
    total = sum(r["c"] for r in rows)
    head = f"group by {key}" + (f", type={type_}" if type_ else "") + (f", tag~{tag}" if tag else "") \
        + (f", values of {scheme}" + (" rolled up to the top concepts" if level == "top" else "") if scheme else "")
    return f"{head} — {total} nodes in {len(rows)} group(s):\n" + "\n".join(
        f"  {r['c']:5}  {r['g'] if r['g'] is not None else '(none)'}" + (f"  ({r['label']})" if r.get("label") and r["label"] != r["g"] else "")
        for r in rows)


def resolve_text(term):
    """Translate a user phrase / jargon into the CANONICAL graph entities via the lexicon, and report
    whether each target is actually ingested — so a query can tell 'not ingested' from 'filed
    elsewhere'. Falls back to alias/label/FTS entity resolution when the phrase isn't in the lexicon."""
    t = (term or "").strip().lower()
    if not t:
        return "kg_resolve: empty term."
    rows = STORE.lexicon(t)
    if not rows:                                  # fuzzy: phrase contained in the term, or vice-versa
        rows = STORE.lexicon_fuzzy(t)
    groups, order = {}, []
    for r in rows:
        k = (r["canonical"], r["status"], r["note"])
        if k not in groups:
            groups[k] = []; order.append(k)
        if r["target"]:
            groups[k].append(r["target"])
    out = []
    for (canon, status, note) in order:
        targets = list(dict.fromkeys(groups[(canon, status, note)]))
        head = f"• '{term}' → {canon}" + (f"  [{status.upper()}]" if status and status != "current" else "")
        out.append(head)
        if note:
            out.append(f"    note: {note}")
        for tg in targets:
            n = node(tg)
            out.append(f"    {'✓' if n else '✗'} {tg}" +
                       (f"  — {n['label']}  [{n['status']}]" if n else "  — NOT in the graph (not ingested)"))
        if not targets and status != "not_ingested":
            out.append("    (no entity mapped)")
    if not rows:                                  # lexicon didn't recognize the phrase — best-effort entity match
        nid, alts = resolve(term)
        if nid:
            out.append(f"• closest entity: {label(nid)}  ({nid})  [{node(nid)['status']}]")
            if alts:
                out.append("    other: " + ", ".join(f"{label(a)} ({a})" for a in alts))
    if not out:
        return (f"'{term}' didn't resolve to known jargon or an entity — it may not be ingested, or is "
                f"phrased differently. Try kg_search, kg_docs, or add it to lexicon.json.")
    return f"resolve '{term}':\n" + "\n".join(out)


def pending_text(limit=40):
    """What is on its way into the graph and where it stands: inbox, processing, proposals, the
    candidate, each fact with its verdict. Reads the project's files; a store served without its
    project beside it cannot know."""
    if not PROJECT_ROOT:
        return ("Pending knowledge is not known here: this store is served without its project (a published "
                "store, or a database path). Serve the project directory to see the lane.")
    from ..curate import pending as _pending
    return _pending.text(_pending.collect(PROJECT_ROOT), limit=int(limit))


def _graph_from_store():
    """The store's graph as node and edge dicts, the shape the catalog and the matcher read."""
    nodes = []
    for r in STORE.all_nodes():
        n = dict(r)
        attrs = n.get("attributes")
        if isinstance(attrs, str):
            try:
                n["attributes"] = json.loads(attrs)
            except ValueError:
                n["attributes"] = {}
        n.setdefault("status", "current")
        nodes.append(n)
    edges = [{"from": r["src"], "rel": r["rel"], "to": r["dst"], "status": r.get("status") or "current"}
             for r in STORE.all_edges()]
    return nodes, edges


_questions = (None, None)         # (the store they were read from, {id: question})


def questions():
    """The competency questions the store carries, read once per loaded store."""
    global _questions
    if _questions[0] is not STORE:
        _questions = (STORE, STORE.questions() if "questions" in STORE.features() else {})
    return _questions[1]


def _derived_attributes_from_store():
    out = {}
    for r in STORE.all_derived_attributes():
        value = r.get("value")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        out.setdefault(r["node_id"], {})[r["name"]] = value
    return out


def ask_data(qid, params=None):
    """One competency question, run: {id, question, who, status, gate, params, rows, gaps}, or an
    error. `params` maps NAME -> an entity (id, label or alias), resolved the way kg_resolve does."""
    from ..reason import questions as _questions_model
    from ..model.vocabulary import covers as _covers
    declared = questions()
    if not declared:
        return {"error": "No competency questions: the store carries none (questions.json absent or empty at build).", "rows": []}
    question = declared.get(qid)
    if question is None:
        return {"error": "No question %r; declared: %s" % (qid, ", ".join(declared)), "rows": []}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except ValueError:
            return {"error": "params must be an object NAME -> entity, not %r" % params, "rows": []}
    bound, unresolved = {}, []
    for name, spec in (question.get("params") or {}).items():
        given = (params or {}).get(name)
        if given in (None, ""):
            unresolved.append("%s (a %s)" % (name, (spec or {}).get("type") or "node"))
            continue
        nid, _alts = resolve(str(given))
        if not nid:
            return {"error": "No entity matched %r for %s." % (given, name), "rows": []}
        bound[name] = nid
    if unresolved:
        return {"error": "Question %s needs %s. Pass it as params." % (qid, ", ".join(unresolved)), "rows": []}
    nodes, edges = _graph_from_store()
    result = _questions_model.run(qid, question, bound, nodes, edges, _covers(vocabulary().classes),
                                  _derived_attributes_from_store())
    result["labels"] = {v: (label(v) or v) for row in result["rows"] for v in row.values()
                        if isinstance(v, str) and node(v)}
    return result


def ask_text(qid, params=None):
    """What the graph answers to one of its competency questions, with the gaps when it cannot."""
    from ..reason import questions as _questions_model
    result = ask_data(qid, params)
    if result.get("error"):
        return result["error"]
    return _questions_model.result_text(result, result.get("labels"))


def questions_data():
    """Every competency question and whether the live graph answers it."""
    from ..reason import questions as _questions_model
    from ..model.vocabulary import covers as _covers
    declared = questions()
    if not declared:
        return {"rows": []}
    nodes, edges = _graph_from_store()
    return {"rows": _questions_model.survey(declared, nodes, edges, _covers(vocabulary().classes),
                                            _derived_attributes_from_store())}


def questions_text():
    """The questions this graph exists to answer, and whether it does: the ontology's health."""
    from ..reason import questions as _questions_model
    return _questions_model.survey_text(questions_data()["rows"])


def actions_data(action=None, on=None, ready=False, due=False):
    """The catalog as data: every action, one action, or the actions bound to one entity."""
    from ..actions import catalog as _catalog
    from ..model.vocabulary import covers as _covers
    nodes, edges = _graph_from_store()
    definitions = _catalog.definitions_from_nodes(nodes)
    covers = _covers(vocabulary().classes)
    if on:
        nid, _alts = resolve(on)
        if not nid:
            return {"error": f"No entity matched '{on}'.", "actions": []}
        subject = next(n for n in nodes if n["id"] == nid)
        return {"on": nid, "actions": _catalog.for_entity(definitions, nodes, edges, subject, covers=covers)}
    if action:
        chosen = [a for a in definitions if a["id"] == action]
        if not chosen:
            return {"error": "No action %r; declared: %s" % (action, ", ".join(a["id"] for a in definitions) or "none"), "actions": []}
        return {"actions": _catalog.catalog(chosen, nodes, edges, covers=covers)}
    return {"actions": _catalog.catalog(definitions, nodes, edges, ready_only=bool(ready), due_only=bool(due), covers=covers)}


def actions_text(action=None, on=None, ready=False, due=False):
    """What can be done here. OTO lists the actions, with their readiness and bound inputs; the
    caller invokes them through the declared transport and records the result."""
    from ..actions import catalog as _catalog
    data = actions_data(action, on, ready, due)
    if data.get("error"):
        return data["error"]
    if on:
        heading = "Actions on %s (%d):" % (data["on"], len(data["actions"]))
        if not data["actions"]:
            return heading + "\n  none: no action declares this entity's class as its subject."
        return _catalog.text(data["actions"], heading=heading)
    if due and not data["actions"]:
        return "No scheduled read-only action is due and ready now (kg_actions without `due` says when each runs next)."
    if ready and not data["actions"]:
        return "No action is ready: every declared action's preconditions fail on the current graph (kg_actions without `ready` says why)."
    return _catalog.text(data["actions"])


def docs_text(query=None, limit=200):
    """Document inventory: list ingested Document nodes (newest first) + the ingest frontier (latest
    as_of), so a user can confirm coverage and tell 'not ingested' from 'phrased differently'."""
    rows = STORE.documents(query, int(limit))
    frontier = STORE.frontier()
    if not rows:
        return (f"No Document nodes" + (f" matching '{query}'" if query else "") +
                f".\nIngest frontier (latest as_of in the graph): {frontier}.")
    out = [f"Documents ({len(rows)}" + (f" matching '{query}'" if query else "") +
           f")  ·  ingest frontier (latest as_of): {frontier}"]
    for r in rows:
        at = json.loads(r["attributes"] or "{}")
        dt = r["valid_from"] or at.get("date") or r["as_of"] or "?"
        out.append(f"  {dt}  {r['label']}  ({r['id']})")
    return "\n".join(out)


# ============================ MCP tool registry ============================
TOOLS = [
    {"name": "kg_entity",
     "description": "Look up an entity by id/label/alias and return its current state, provenance "
                    "(status/as_of/valid_from/source) and relationships. Current-only unless history/as_of given.",
     "inputSchema": {"type": "object", "properties": {
         "term": {"type": "string", "description": "Entity id, label, or alias."},
         "history": {"type": "boolean", "description": "Include superseded predecessors."},
         "as_of": {"type": "string", "description": "ISO date YYYY-MM-DD for a valid-time slice."}},
         "required": ["term"]},
     "fn": lambda a: entity_text(a["term"], a.get("history", False), a.get("as_of"))},
    {"name": "kg_neighbors",
     "description": "Show an entity's relationships, optionally filtered to one relation type.",
     "inputSchema": {"type": "object", "properties": {
         "term": {"type": "string"}, "rel": {"type": "string", "description": "e.g. led_by, raised_in, owned_by."}},
         "required": ["term"]},
     "fn": lambda a: neighbors_text(a["term"], a.get("rel"))},
    {"name": "kg_count",
     "description": "Count nodes, optionally filtered by type, tag, or an attribute=value. "
                    "E.g. how many open claims: type='Claim', attr='state', value='open'.",
     "inputSchema": {"type": "object", "properties": {
         "type": {"type": "string", "description": "a declared class, e.g. Claim, Role, Procedure"},
         "tag": {"type": "string", "description": "substring of a tag"},
         "attr": {"type": "string", "description": "attribute key to filter on, e.g. state, region"},
         "value": {"type": "string", "description": "value the attribute must equal"}}},
     "fn": lambda a: count_text(a.get("type"), a.get("tag"), a.get("attr"), a.get("value"))},
    {"name": "kg_group_by",
     "description": "Aggregate/group nodes and count each bucket. Group by a column (type, status) or an "
                    "attribute key (e.g. state, region). E.g. claims by state: by='state', type='Claim'.",
     "inputSchema": {"type": "object", "properties": {
         "by": {"type": "string", "description": "field to group by: type | status | or an attribute key like state, region"},
         "type": {"type": "string", "description": "optional node-type filter"},
         "tag": {"type": "string", "description": "optional tag substring filter"},
         "limit": {"type": "integer", "description": "max groups to return (default 200)"},
         "level": {"type": "string", "description": "for values of a scheme: 'top' rolls each value up to the top concept of its broader chain"}},
         "required": ["by"]},
     "fn": lambda a: group_by_text(a["by"], a.get("type"), a.get("tag"), a.get("limit", 200), a.get("level"))},
    {"name": "kg_search",
     "description": "Full-text (FTS5) passage search across documents, knowledge-base notes and semantic cards.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "n": {"type": "integer", "description": "max results (default 8)"}},
         "required": ["query"]},
     "fn": lambda a: search_text(a["query"], a.get("n", 8))},
    {"name": "kg_by_type",
     "description": "List nodes of a declared class (e.g. Claim, Role, Procedure, Decision), "
                    "optionally filtered by lifecycle state (open/done/...).",
     "inputSchema": {"type": "object", "properties": {
         "type": {"type": "string"}, "state": {"type": "string"}, "limit": {"type": "integer"}},
         "required": ["type"]},
     "fn": lambda a: by_type_text(a["type"], a.get("state"), a.get("limit", 50))},
    {"name": "kg_define",
     "description": "What a class, relation or attribute of the vocabulary is called and means: its labels in every "
                    "language, definition, scope note and example, domain, range and inverse, the question it "
                    "answers and why it exists, who confirmed it, and how much of the graph uses it. Use when an "
                    "answer names a term and the reader asks what it means, or before using a term in a question.",
     "inputSchema": {"type": "object", "properties": {
         "term": {"type": "string", "description": "a class, relation or attribute: its name or its label"}},
         "required": ["term"]},
     "fn": lambda a: define_text(a["term"])},
    {"name": "kg_explain",
     "description": "Why the graph holds a derived fact about an entity: the rule that derived it and every "
                    "premise down to the document evidence. Use when an answer shows [derived by <rule>].",
     "inputSchema": {"type": "object", "properties": {
         "term": {"type": "string"}, "rel": {"type": "string", "description": "limit to one relation"}},
         "required": ["term"]},
     "fn": lambda a: explain_text(a["term"], a.get("rel"))},
    {"name": "kg_policy",
     "description": "Standing policy findings: every rule of kind policy the current graph violates, with the "
                    "entity and the message. Blocking findings first.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
     "fn": lambda a: policy_text(a.get("limit", 50))},
    {"name": "kg_overview",
     "description": "The map of the whole graph, for a question that starts from no entity: counts by "
                    "class, relation and status, the most connected entities, top tags, what the corpus "
                    "covers and how recent it is, superseded facts, and the recent ledger of changes. "
                    "Use FIRST for 'what is going on', 'what are the themes', 'what changed'; then read "
                    "the entities it surfaces. It is a map: a synthesis must cite the facts it rests on.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "description": "rows per section (default 10)"}}},
     "fn": lambda a: overview_text(a.get("limit", 10))},
    {"name": "kg_stale",
     "description": "Audit: status counts plus every superseded fact and its successor.",
     "inputSchema": {"type": "object", "properties": {}},
     "fn": lambda a: stale_text()},
    {"name": "kg_resolve",
     "description": "Translate a user phrase / jargon / acronym into the canonical graph entities it "
                    "refers to (via the maintained lexicon), and say whether each is actually ingested. "
                    "Use FIRST when a question names things colloquially (an acronym, a nickname, "
                    "'the press') to map them to entity ids and distinguish NOT-INGESTED from "
                    "filed-elsewhere before retrieving.",
     "inputSchema": {"type": "object", "properties": {
         "term": {"type": "string", "description": "a word/phrase from the user's question"}},
         "required": ["term"]},
     "fn": lambda a: resolve_text(a["term"])},
    {"name": "kg_pending",
     "description": "What is on its way into the graph and not yet believed, by station: files in the inbox, "
                    "documents extracted but not drafted, facts in proposals (as `curate add --dry-run` would merge "
                    "them, refusals with their reason), and the open candidate's changes against the live graph. "
                    "Use to answer 'is this being added' or 'what is in review' without mistaking it for a fact.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "description": "rows per station (default 40)"}}},
     "fn": lambda a: pending_text(a.get("limit", 40))},
    {"name": "kg_actions",
     "description": "What can be done here: the actions the graph declares, as MCP tool definitions bound to the "
                    "graph, with whether each is ready and on which entities, the inputs filled from an entity, the "
                    "declared way to invoke it, and the environment variables the caller must hold. OTO never invokes; "
                    "the caller does, then records the result with `oto actions record`. Use with `on` for one entity "
                    "(\"what can I do about X?\"), `action` for one action, `ready` to list only what is ready now.",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "description": "one action id, e.g. action.check-repository"},
         "on": {"type": "string", "description": "an entity (id or label): the actions on it, inputs bound"},
         "ready": {"type": "boolean", "description": "only the actions ready on at least one entity"},
         "due": {"type": "boolean", "description": "only the scheduled read-only actions whose run is due and that are ready"}}},
     "fn": lambda a: actions_text(a.get("action"), a.get("on"), bool(a.get("ready")), bool(a.get("due")))},
    {"name": "kg_docs",
     "description": "Document inventory — list ingested Document nodes (newest first) with dates, plus the "
                    "ingest frontier (latest as_of). Use to confirm coverage / answer 'do you have the X doc' "
                    "and to tell 'not ingested yet' from 'phrased differently'. Optional query filters by title/id.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "optional substring to filter document title/id"},
         "limit": {"type": "integer", "description": "max docs (default 200)"}}},
     "fn": lambda a: docs_text(a.get("query"), a.get("limit", 200))},
    {"name": "kg_questions",
     "description": "The competency questions this graph exists to answer, and whether it does: each question's id, "
                    "who asks it, and its status on the live graph (answered, unanswered with the gap, violated, "
                    "clean). Use FIRST to learn what the graph is for and where it is thin, before asking one.",
     "inputSchema": {"type": "object", "properties": {}},
     "fn": lambda a: questions_text()},
    {"name": "kg_ask",
     "description": "Run one competency question by id (see kg_questions) with its parameters bound to entities "
                    "(id, label or alias), and return the rows the graph answers with, or the gap that explains "
                    "an empty answer. Use for 'can the graph answer X about Y' and for the question's own answer.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "description": "the question id, e.g. CQ3"},
         "params": {"type": "object", "description": "NAME -> entity, one per declared parameter, e.g. {\"CLAIM\": \"claim.c-5001\"}"}},
         "required": ["id"]},
     "fn": lambda a: ask_text(a["id"], a.get("params") if "params" in a else {k: v for k, v in a.items() if k != "id"})},
]
TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


# ============================ JSON-RPC plumbing ============================
def respond(req):
    """The JSON-RPC response to one request, or None for a notification. Transport-free: stdio
    writes it to stdout, HTTP writes it to the response body, so the two cannot disagree."""
    method = req.get("method")
    mid = req.get("id")
    params = req.get("params") or {}

    def message(result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        return msg

    if method == "initialize":
        proto = params.get("protocolVersion", DEFAULT_PROTOCOL)
        return message({"protocolVersion": proto, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO})
    if method == "notifications/initialized":
        return None                      # notification, no reply
    if method == "ping":
        return message({})
    if method == "tools/list":
        return message({"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]})
    if method == "tools/call":
        name = params.get("name"); args = params.get("arguments") or {}
        tool = TOOL_BY_NAME.get(name)
        if not tool:
            return message(error={"code": -32601, "message": f"unknown tool: {name}"})
        ensure_fresh()        # auto-pick-up a freshly-built/synced db (no restart needed)
        if STORE is None:
            return message({"content": [{"type": "text", "text": no_data_message()}], "isError": True})
        try:
            text = tool["fn"](args)
            return message({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:
            log("tool error", name, e)
            return message({"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    if mid is not None:
        return message(error={"code": -32601, "message": f"method not found: {method}"})
    return None                          # unknown notification: ignored


def handle(req):
    msg = respond(req)
    if msg is not None:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


# ============================ CLI mode ============================
# The SAME query logic, exposed as a one-shot CLI for hosts where the shell is allowed but MCP
# tool calls are gated by policy (no per-call "allow" prompts). `oto query <cmd> ...`.
CLI_USAGE = """oto query — the same data as the server tools, one query per invocation
  entity <term> [--history] [--as-of YYYY-MM-DD]   neighbors <term> [rel]
  search <query> [n]                               by-type <Type> [state] [limit]
  count [--type T] [--tag G] [--attr A --value V]  group <by> [--type T] [--tag G] [--level top]
  stale   resolve <term>   docs [query] [limit]   overview [limit]   define <term>
  explain <term> [rel]   policy [limit]   pending [limit]   actions [--on <term>] [--action <id>] [--ready] [--due]
  questions   ask <id> [NAME=<entity> ...]"""

CLI_COMMANDS = {"entity", "neighbors", "search", "by-type", "count", "group", "define", "questions", "ask",
                "stale", "resolve", "docs", "overview", "explain", "policy", "pending", "actions", "help", "--help", "-h"}

def _flag(a, name):
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else None

def cli(argv):
    cmd, a = argv[0], argv[1:]
    if cmd in ("help", "--help", "-h"):
        print(CLI_USAGE); return 0
    ensure_fresh()
    if STORE is None:
        print(no_data_message()); return 1
    pos = [x for x in a if not x.startswith("--")]          # positional (non-flag) args
    try:
        if cmd == "entity":
            print(entity_text(pos[0], "--history" in a, _flag(a, "--as-of")))
        elif cmd == "neighbors":
            print(neighbors_text(pos[0], pos[1] if len(pos) > 1 else None))
        elif cmd == "search":
            print(search_text(pos[0], int(pos[1]) if len(pos) > 1 else 8))
        elif cmd == "by-type":
            print(by_type_text(pos[0], pos[1] if len(pos) > 1 else None, int(pos[2]) if len(pos) > 2 else 50))
        elif cmd == "count":
            print(count_text(_flag(a, "--type"), _flag(a, "--tag"), _flag(a, "--attr"), _flag(a, "--value")))
        elif cmd == "group":
            print(group_by_text(pos[0], _flag(a, "--type"), _flag(a, "--tag"), 200, _flag(a, "--level")))
        elif cmd == "stale":
            print(stale_text())
        elif cmd == "overview":
            print(overview_text(int(pos[0]) if pos else 10))
        elif cmd == "explain":
            print(explain_text(pos[0], pos[1] if len(pos) > 1 else None))
        elif cmd == "policy":
            print(policy_text(int(pos[0]) if pos else 50))
        elif cmd == "pending":
            print(pending_text(int(pos[0]) if pos else 40))
        elif cmd == "actions":
            print(actions_text(_flag(a, "--action"), _flag(a, "--on"), "--ready" in a, "--due" in a))
        elif cmd == "resolve":
            print(resolve_text(" ".join(pos)))
        elif cmd == "define":
            print(define_text(" ".join(pos)))
        elif cmd == "questions":
            print(questions_text())
        elif cmd == "ask":
            print(ask_text(pos[0], dict(p.split("=", 1) for p in pos[1:] if "=" in p)))
        elif cmd == "docs":
            print(docs_text(pos[0] if pos else None, int(pos[1]) if len(pos) > 1 else 200))
    except IndexError:
        print(f"missing argument for '{cmd}'.\n{CLI_USAGE}")
        return 2
    return 0


def main():
    log("ready; tools:", ", ".join(TOOL_BY_NAME), "| store:", BACKEND)
    for line in sys.stdin:
        line = line.lstrip("﻿").strip()  # tolerate a leading BOM
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log("bad json:", line[:120]); continue
        try:
            handle(req)
        except Exception as e:
            log("handler error:", e)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in CLI_COMMANDS:
        cli(sys.argv[1:])          # CLI mode: one query per invocation
    else:
        main()                     # JSON-RPC stdio server mode (default)
