# -*- coding: utf-8 -*-
"""Stage 5 of 5. Emit an indexed SQLite store (`layout.database`) from the graph and corpus, so queries
do indexed lookups and full-text search instead of re-parsing the JSON graph on every call.

Tables
  nodes(id PK, type, label, status, as_of, valid_from, valid_to, source_doc, summary,
        attributes, tags, sources, degree)   -- attributes/tags/sources are JSON text
  aliases(node_id, alias, kind, lang)   -- what else a node answers to: an alias, a label in another
                                        -- language, or a hidden label (resolution only)
  edges(src, rel, dst, status)                        -- indexed on src, dst, rel
  node_fts   FTS5(id, label, aliases, summary, tags)  -- entity search
  docs_fts   FTS5(path, title, body)                  -- passage search over the corpus
  terms(name, kind, owner, spec, rationale, iri)      -- the vocabulary, so answers can say what a term means

Dependency-free (sqlite3 + FTS5 ship with CPython). Idempotent: rebuilds the file each run.
Runs last: it reads knowledge-graph.json from the knowledge stage, and indexes the cards the
semantic stage wrote alongside the corpus and the authored notes.
"""

import os, json, sqlite3


#: The shape of this database. Raise it when a change would make an older server read the data
#: wrongly: a renamed or removed column, a changed meaning, a new table the server must consult.
#: Do NOT raise it for a change the server cannot notice, such as more rows.
#:
#: Semantics on the reading side: refuse the future, tolerate the past. A server refuses a database
#: whose version is HIGHER than it understands, because that database may mean something it cannot
#: see. It accepts a lower or absent version, because the data it knows how to read is still there.
#: A version nothing checks protects nothing, so `oto/serve/engine.py` checks this one at startup.
SCHEMA_VERSION = 5

SCHEMA_SQL = """
CREATE TABLE nodes (
  id TEXT PRIMARY KEY, type TEXT, label TEXT, status TEXT,
  as_of TEXT, valid_from TEXT, valid_to TEXT, source_doc TEXT,
  supersedes TEXT, superseded_by TEXT,
  summary TEXT, attributes TEXT, tags TEXT, sources TEXT,
  degree INTEGER,
  evidence TEXT
);
CREATE TABLE aliases (node_id TEXT, alias TEXT, kind TEXT, lang TEXT);
CREATE TABLE edges (src TEXT, rel TEXT, dst TEXT, status TEXT, derived_by TEXT, premises TEXT);
CREATE TABLE derived_attributes (node_id TEXT, name TEXT, value TEXT, derived_by TEXT, premises TEXT);
CREATE TABLE policy_findings (rule TEXT, severity TEXT, node_id TEXT, message TEXT);
CREATE INDEX idx_nodes_type   ON nodes(type);
CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_aliases_alias ON aliases(alias COLLATE NOCASE);
CREATE INDEX idx_edges_src ON edges(src);
CREATE INDEX idx_edges_dst ON edges(dst);
CREATE INDEX idx_edges_rel ON edges(rel);
CREATE VIRTUAL TABLE node_fts USING fts5(id UNINDEXED, label, aliases, summary, tags);
CREATE VIRTUAL TABLE docs_fts USING fts5(path UNINDEXED, title, body);
CREATE TABLE docs (path TEXT, title TEXT, body TEXT);   -- plain mirror for the FTS5-free (Node) server
CREATE TABLE meta (key TEXT, value TEXT);               -- build_seq, schema_version: see SCHEMA_VERSION
CREATE TABLE changelog (at TEXT, by TEXT, note TEXT, nodes_added INTEGER, nodes_changed INTEGER, edges_added INTEGER, retired TEXT, sources TEXT);   -- recent ledger, for kg_overview
CREATE TABLE lexicon (phrase TEXT, canonical TEXT, target TEXT, status TEXT, note TEXT);
CREATE INDEX idx_lexicon_phrase ON lexicon(phrase);     -- jargon/synonym -> canonical entity (kg_resolve)
CREATE TABLE terms (name TEXT, kind TEXT, owner TEXT, spec TEXT, rationale TEXT, iri TEXT);   -- the vocabulary (kg_define)
"""


def run(project):
    _layout = project.layout
    SEM = _layout.graph
    identity = project.identity()
    DB = _layout.database
    os.makedirs(os.path.dirname(DB), exist_ok=True)

    graph = json.load(open(os.path.join(SEM, "knowledge-graph.json"), encoding="utf-8"))
    nodes = graph["nodes"]
    edges = graph["edges"]
    from . import rows as _rows
    from ..model import vocabulary as _vocab
    language = _vocab.DEFAULT_LANGUAGE
    if os.path.exists(project.ontology_config_path):
        language = _vocab.languages(json.load(open(project.ontology_config_path, encoding="utf-8")))[0]

    # degree
    degree = {}
    for e in edges:
        degree[e["from"]] = degree.get(e["from"], 0) + 1
        degree[e["to"]] = degree.get(e["to"], 0) + 1

    # Build into a temp file, then atomically swap — so a locked or in-use database (e.g. the warm
    # MCP server holding it open on Windows) never leaves us with a half-written or deleted store.
    TMP = DB + ".new"
    if os.path.exists(TMP):
        os.remove(TMP)
    con = sqlite3.connect(TMP)
    con.execute("PRAGMA journal_mode=DELETE")  # self-contained file (no -wal/-shm) for immutable reads
    cur = con.cursor()

    cur.executescript(SCHEMA_SQL)

    for n in nodes:
        cur.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (n["id"], n.get("type"), n.get("label"), n.get("status", "current"),
             n.get("as_of"), n.get("valid_from"), n.get("valid_to"), n.get("source_doc"),
             json.dumps(n.get("supersedes")) if n.get("supersedes") else None,
             n.get("superseded_by"),
             n.get("summary"), json.dumps(n.get("attributes") or {}, ensure_ascii=False),
             json.dumps(n.get("tags") or [], ensure_ascii=False),
             json.dumps(n.get("sources") or [], ensure_ascii=False),
             degree.get(n["id"], 0),
             json.dumps(n.get("evidence") or [], ensure_ascii=False)))
        names = _rows.names_of(n, language)
        for name, kind, lang in names:
            cur.execute("INSERT INTO aliases VALUES (?,?,?,?)", (n["id"], name, kind, lang))
        cur.execute("INSERT INTO node_fts VALUES (?,?,?,?,?)",
                    (n["id"], n.get("label", ""), " ".join(name for name, _kind, _lang in names),
                     n.get("summary", "") or "", " ".join(n.get("tags") or [])))

    for e in edges:
        cur.execute("INSERT INTO edges VALUES (?,?,?,?,?,?)",
                    (e["from"], e["rel"], e["to"], e.get("status", "current"), None, None))

    # ---- what the rules derived, marked as such, and what policy flagged ----
    derived_path = os.path.join(SEM, "derived.json")
    nderived = 0
    if os.path.exists(derived_path):
        derived = json.load(open(derived_path, encoding="utf-8"))
        for e in derived.get("derived_edges") or []:
            cur.execute("INSERT INTO edges VALUES (?,?,?,?,?,?)",
                        (e["from"], e["rel"], e["to"], "derived", e["derived_by"],
                         json.dumps(e.get("premises") or [], ensure_ascii=False)))
            nderived += 1
        for a in derived.get("derived_attributes") or []:
            cur.execute("INSERT INTO derived_attributes VALUES (?,?,?,?,?)",
                        (a["node"], a["name"], json.dumps(a["value"], ensure_ascii=False), a["derived_by"],
                         json.dumps(a.get("premises") or [], ensure_ascii=False)))
            nderived += 1
        for x in derived.get("findings") or []:
            cur.execute("INSERT INTO policy_findings VALUES (?,?,?,?)",
                        (x["rule"], x["severity"], x.get("node"), x["message"]))

    # ---- passage index, lexicon and the recent ledger: the same rows the Neo4j target loads ----
    passages = _rows.passages(_layout)
    for p in passages:
        cur.execute("INSERT INTO docs_fts VALUES (?,?,?)", (p["path"], p["title"], p["body"]))
        cur.execute("INSERT INTO docs VALUES (?,?,?)", (p["path"], p["title"], p["body"]))
    ndocs = len(passages)

    lexicon = _rows.lexicon_rows(project)
    for r in lexicon:
        cur.execute("INSERT INTO lexicon VALUES (?,?,?,?,?)",
                    (r["phrase"], r["canonical"], r["target"], r["status"], r["note"]))
    nlex = len(lexicon)

    nterms = 0
    for r in _rows.term_rows(project):
        cur.execute("INSERT INTO terms VALUES (?,?,?,?,?,?)",
                    (r["name"], r["kind"], r["owner"], r["spec"], r["rationale"], r["iri"]))
        nterms += 1

    for r in _rows.changelog_rows(project):
        cur.execute("INSERT INTO changelog VALUES (?,?,?,?,?,?,?,?)",
                    (r["at"], r["by"], r["note"], r["nodes_added"], r["nodes_changed"], r["edges_added"],
                     r["retired"], r["sources"]))

    # Freshness stamp so the server can pick the fresher of two databases. Resolved from the
    # PROJECT, not from this file: an installed engine is not inside a git repository.
    _seq = project.build_seq()
    cur.execute("INSERT INTO meta VALUES ('build_seq', ?)", (_seq,))
    # What shape this database is, so a server can refuse one it cannot read. See SCHEMA_VERSION.
    cur.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    con.commit()
    cur.execute("SELECT count(*) FROM nodes"); nn = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM edges"); ne = cur.fetchone()[0]
    con.execute("PRAGMA optimize")
    con.close()

    try:
        os.replace(TMP, DB)  # atomic on the same volume
    except PermissionError:
        print(f"WARNING: '{os.path.relpath(DB, project.src)}' is locked - is the {identity['server_name']} "
              f"server running? Fresh build left at '{os.path.relpath(TMP, project.src)}'. Stop the server "
              f"and rename it over {identity['db_name']}, or rerun without the server. "
              f"(CI is unaffected.)")
        raise SystemExit(0)
    print(f"{os.path.basename(DB)}: {nn} nodes, {ne} edges ({nderived} derived), {ndocs} passages, {nlex} lexicon rows, "
          f"{nterms} terms -> {os.path.relpath(DB, project.src)}")
