# -*- coding: utf-8 -*-
"""What the engine reads, behind one interface with two implementations.

The engine's answers are text built from rows. Everything that fetches a row lives here, so the
same text code runs over the SQLite store (development, the plugin on every machine, the fallback)
and over a self-hosted Neo4j (production). Rows come back as plain dicts with the SQLite column
names, JSON fields as JSON text, so the text code cannot tell which store answered; a test runs
the same queries through both and diffs the output.

The SQLite store is loaded into memory and the file released, so a rebuild can swap the file
under a running server. The Neo4j store is a live connection; a load retires the previous build
in place, so it is always current.
"""
import json
import os
import re
import sqlite3


def fts_tokens(term):
    return re.findall(r"[A-Za-z0-9]+", term or "")


class Store:
    kind = "abstract"

    def close(self):
        pass

    def features(self):
        """Which optional tables this store carries: derived, changelog, policy, lexicon."""
        return set()


# ============================ SQLite ============================

class SqliteStore(Store):
    kind = "sqlite"

    def __init__(self, path):
        src = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        mem = sqlite3.connect(":memory:", check_same_thread=False)
        src.backup(mem)                       # every page, FTS included, into RAM
        src.close()                           # release the file so a rebuild can replace it
        mem.row_factory = sqlite3.Row
        self.con = mem
        self.path = path
        self._features = None

    def close(self):
        try:
            self.con.close()
        except Exception:
            pass

    def _has_table(self, name):
        return self.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def features(self):
        if self._features is None:
            out = set()
            if any(r[1] == "derived_by" for r in self.con.execute("PRAGMA table_info(edges)")):
                out.add("derived")
            for table, feature in (("changelog", "changelog"), ("policy_findings", "policy"), ("lexicon", "lexicon"),
                                   ("derived_attributes", "derived_attributes"), ("terms", "terms"),
                                   ("questions", "questions")):
                if self._has_table(table):
                    out.add(feature)
            self._features = out
        return self._features

    def _rows(self, query, params=()):
        return [dict(r) for r in self.con.execute(query, params).fetchall()]

    def _one(self, query, params=()):
        r = self.con.execute(query, params).fetchone()
        return dict(r) if r is not None else None

    def meta(self, key):
        r = self._one("SELECT value FROM meta WHERE key=?", (key,))
        return r["value"] if r else None

    def node(self, nid):
        return self._one("SELECT * FROM nodes WHERE id=?", (nid,))

    def label(self, nid):
        r = self._one("SELECT label FROM nodes WHERE id=?", (nid,))
        return r["label"] if r else nid

    def by_name(self, term):
        return [r["id"] for r in self._rows(
            "SELECT id FROM nodes WHERE label=? COLLATE NOCASE UNION SELECT node_id FROM aliases WHERE alias=? COLLATE NOCASE "
            "ORDER BY id", (term, term))]

    def by_text(self, term, limit=6):
        toks = fts_tokens(term)
        if not toks:
            return []
        try:
            return [r["id"] for r in self._rows(
                "SELECT f.id AS id FROM node_fts f JOIN nodes n ON n.id=f.id WHERE node_fts MATCH ? "
                "ORDER BY (CASE WHEN n.status='current' THEN 0 ELSE 1 END), bm25(node_fts) LIMIT ?",
                (" OR ".join(f'"{t}"' for t in toks), int(limit)))]
        except sqlite3.OperationalError:
            return []

    def aliases(self, nid):
        """What the node is also called, to show: not its labels in other languages, nor hidden labels."""
        return [r["alias"] for r in self._rows("SELECT alias FROM aliases WHERE node_id=? AND kind='alias'", (nid,))]

    def edges_out(self, nid, rel=None):
        cols = "rel,dst,status" + (",derived_by" if "derived" in self.features() else "")
        rels = _rels(rel)
        rows = self._rows(f"SELECT {cols} FROM edges WHERE src=?" + (" AND rel IN (%s)" % ",".join("?" * len(rels)) if rels else "")
                          + " ORDER BY rel, dst", (nid, *rels))
        for r in rows:
            r.setdefault("derived_by", None)
        return rows

    def edges_in(self, nid, rel=None):
        cols = "rel,src,status" + (",derived_by" if "derived" in self.features() else "")
        rels = _rels(rel)
        rows = self._rows(f"SELECT {cols} FROM edges WHERE dst=?" + (" AND rel IN (%s)" % ",".join("?" * len(rels)) if rels else "")
                          + " ORDER BY rel, src", (nid, *rels))
        for r in rows:
            r.setdefault("derived_by", None)
        return rows

    def edge(self, src, rel, dst):
        if "derived" not in self.features():
            r = self._one("SELECT status FROM edges WHERE src=? AND rel=? AND dst=?", (src, rel, dst))
            return dict(r, derived_by=None, premises=None) if r else None
        return self._one("SELECT status,derived_by,premises FROM edges WHERE src=? AND rel=? AND dst=?", (src, rel, dst))

    def derived_edges(self, nid, rel=None):
        if "derived" not in self.features():
            return []
        return self._rows("SELECT src,rel,dst,derived_by,premises FROM edges WHERE (src=? OR dst=?) AND status='derived'"
                          + (" AND rel=?" if rel else "") + " ORDER BY rel,src,dst",
                          (nid, nid, rel) if rel else (nid, nid))

    def derived_attributes(self, nid):
        if "derived_attributes" not in self.features():
            return []
        return self._rows("SELECT name,value,derived_by,premises FROM derived_attributes WHERE node_id=? ORDER BY name", (nid,))

    def predecessors(self, nid):
        return [r["id"] for r in self._rows("SELECT id FROM nodes WHERE superseded_by=?", (nid,))]

    def search(self, query, n=8):
        toks = fts_tokens(query)
        if not toks:
            return []
        try:
            return self._rows("SELECT path,title,bm25(docs_fts) r FROM docs_fts WHERE docs_fts MATCH ? ORDER BY r LIMIT ?",
                              (" OR ".join(f'"{t}"' for t in toks), int(n)))
        except sqlite3.OperationalError:
            return []

    def by_type(self, type_, state=None, limit=50):
        kinds = _kinds(type_)
        q, a = "SELECT id,label,status,type FROM nodes WHERE type IN (%s)" % ",".join("?" * len(kinds)), list(kinds)
        if state:
            q += " AND json_extract(attributes,'$.state')=?"; a.append(state)
        return self._rows(q + " ORDER BY label LIMIT ?", a + [int(limit)])

    def status_counts(self):
        return self._rows("SELECT status,count(*) c FROM nodes GROUP BY status ORDER BY c DESC, status")

    def superseded(self):
        return self._rows("SELECT id,label,valid_to,superseded_by FROM nodes WHERE status='superseded' ORDER BY id")

    def policy_findings(self, limit=50):
        if "policy" not in self.features():
            return None
        return self._rows("SELECT rule,severity,node_id,message FROM policy_findings "
                          "ORDER BY severity!='blocking', rule, node_id LIMIT ?", (int(limit),))

    def count(self, type_=None, tag=None, attr=None, value=None):
        q, a = "SELECT count(*) c FROM nodes WHERE 1=1", []
        kinds = _kinds(type_)
        if kinds:
            q += " AND type IN (%s)" % ",".join("?" * len(kinds)); a += kinds
        if tag:
            q += " AND tags LIKE ?"; a.append(f"%{tag}%")
        if attr and value is not None:
            q += f" AND json_extract(attributes,'$.{attr}')=?"; a.append(value)
        return self._one(q, a)["c"]

    def group_by(self, key, type_=None, tag=None, limit=200):
        col = key if key in ("type", "status") else f"json_extract(attributes,'$.{key}')"
        q, a = f"SELECT {col} g, count(*) c FROM nodes WHERE 1=1", []
        kinds = _kinds(type_)
        if kinds:
            q += " AND type IN (%s)" % ",".join("?" * len(kinds)); a += kinds
        if tag:
            q += " AND tags LIKE ?"; a.append(f"%{tag}%")
        q += " GROUP BY g ORDER BY c DESC, g LIMIT ?"; a.append(int(limit))
        return self._rows(q, a)

    def lexicon(self, phrase):
        if "lexicon" not in self.features():
            return []
        return self._rows("SELECT DISTINCT canonical,target,status,note FROM lexicon WHERE phrase=?", (phrase,))

    def lexicon_fuzzy(self, phrase):
        if "lexicon" not in self.features():
            return []
        return self._rows("SELECT DISTINCT canonical,target,status,note FROM lexicon "
                          "WHERE ? LIKE '%'||phrase||'%' OR phrase LIKE ? LIMIT 80", (phrase, f"%{phrase}%"))

    def terms(self):
        """The vocabulary: [{name, kind, owner, spec, rationale, iri}], spec and rationale parsed."""
        return [dict(r, spec=json.loads(r["spec"] or "{}"), rationale=json.loads(r["rationale"] or "{}"))
                for r in self._rows("SELECT name,kind,owner,spec,rationale,iri FROM terms ORDER BY kind,owner,name")]

    def questions(self):
        """The competency questions: {id: question}, in declaration order."""
        if "questions" not in self.features():
            return {}
        return {r["id"]: json.loads(r["spec"] or "{}") for r in self._rows("SELECT id, spec FROM questions ORDER BY rowid")}

    def documents(self, query=None, limit=200):
        q, a = "SELECT id,label,as_of,valid_from,attributes FROM nodes WHERE type='Document'", []
        if query:
            q += " AND (label LIKE ? OR id LIKE ?)"; a += [f"%{query}%", f"%{query}%"]
        return self._rows(q + " ORDER BY COALESCE(valid_from, as_of) DESC, label LIMIT ?", a + [int(limit)])

    def frontier(self):
        return self._one("SELECT max(as_of) m FROM nodes WHERE as_of IS NOT NULL")["m"]

    def counts(self):
        f = self.features()
        return {"nodes": self._one("SELECT count(*) c FROM nodes")["c"],
                "edges": self._one("SELECT count(*) c FROM edges")["c"],
                "superseded": self._one("SELECT count(*) c FROM nodes WHERE status='superseded'")["c"],
                "derived_edges": self._one("SELECT count(*) c FROM edges WHERE status='derived'")["c"] if "derived" in f else 0,
                "derived_attributes": self._one("SELECT count(*) c FROM derived_attributes")["c"] if "derived_attributes" in f else 0,
                "findings": self._one("SELECT count(*) c FROM policy_findings")["c"] if "policy" in f else 0}

    def types_current(self):
        return self._rows("SELECT type,count(*) c FROM nodes WHERE status='current' GROUP BY type ORDER BY c DESC, type")

    def rels_counts(self, limit=10):
        return self._rows("SELECT rel,count(*) c FROM edges GROUP BY rel ORDER BY c DESC, rel LIMIT ?", (int(limit),))

    def hubs(self, limit=10):
        return self._rows("SELECT id,label,type,degree FROM nodes WHERE status='current' ORDER BY degree DESC, id LIMIT ?", (int(limit),))

    def tags_current(self):
        return [r["tags"] for r in self._rows("SELECT tags FROM nodes WHERE status='current'")]

    def docs_count(self, prefix):
        return self._one("SELECT count(*) c FROM docs WHERE path LIKE ?", (prefix + "%",))["c"]

    def changelog(self, limit=10):
        if "changelog" not in self.features():
            return None
        return self._rows("SELECT * FROM changelog ORDER BY at DESC LIMIT ?", (int(limit),))

    # ---- the whole graph, for a payload ----
    def all_nodes(self):
        return self._rows("SELECT * FROM nodes ORDER BY id")

    def all_aliases(self):
        out = {}
        for r in self._rows("SELECT node_id, alias FROM aliases WHERE kind='alias' ORDER BY rowid"):
            out.setdefault(r["node_id"], []).append(r["alias"])
        return out

    def all_edges(self):
        cols = "src,rel,dst,status" + (",derived_by,premises" if "derived" in self.features() else "")
        rows = self._rows(f"SELECT {cols} FROM edges ORDER BY src, rel, dst")
        for r in rows:
            r.setdefault("derived_by", None)
            r.setdefault("premises", None)
        return rows

    def all_derived_attributes(self):
        if "derived_attributes" not in self.features():
            return []
        return self._rows("SELECT node_id,name,value,derived_by,premises FROM derived_attributes ORDER BY node_id, name")

    def all_lexicon(self):
        if "lexicon" not in self.features():
            return []
        return self._rows("SELECT phrase,canonical,target,status,note FROM lexicon ORDER BY phrase, canonical, target")

    def passages(self):
        return self._rows("SELECT path,title,body FROM docs ORDER BY path")


# ============================ Neo4j ============================

def _kinds(type_):
    """A class filter as a list: one class, or the classes a question about one covers."""
    if not type_:
        return []
    return list(type_) if isinstance(type_, (list, tuple, set)) else [type_]


def _rels(rel):
    if not rel:
        return []
    return list(rel) if isinstance(rel, (list, tuple, set)) else [rel]


def _plain(value):
    """A Neo4j value as JSON-able Python: temporal types to ISO strings."""
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class Neo4jStore(Store):
    kind = "neo4j"

    def __init__(self, uri, auth, database, project):
        import logging
        from neo4j import GraphDatabase
        # A property no node has yet (evidence on a graph without any) makes the server send a
        # notification per query; the driver would print each one to stderr, which is the
        # protocol channel's neighbour. They carry nothing a reader can act on.
        logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
        try:
            self.driver = GraphDatabase.driver(uri, auth=auth, notifications_min_severity="OFF")
        except TypeError:                                  # a driver older than 5.7
            self.driver = GraphDatabase.driver(uri, auth=auth)
        self.database = database
        self.project = project
        self.uri = uri
        self._features = None

    @classmethod
    def from_config(cls, project_config, project):
        """A store from a project config dict (its `neo4j` section) and the environment.

        Raises ValueError naming what is missing, so the caller can say so at startup.
        """
        from ..targets import neo4j as _target
        if not _target.available():
            raise ValueError("the neo4j driver is not installed: install the `neo4j` extra")
        conf = _target.connection((project_config or {}).get("neo4j"))
        if not conf["uri"]:
            raise ValueError("no Neo4j uri: set `neo4j.uri` in project.config.json or NEO4J_URI")
        auth = _target.credentials()
        if not auth:
            raise ValueError("no Neo4j credentials: set NEO4J_PASSWORD (and NEO4J_USER), or NEO4J_AUTH=user/password")
        return cls(conf["uri"], auth, conf["database"], project)

    def close(self):
        try:
            self.driver.close()
        except Exception:
            pass

    def _run(self, query, **params):
        params.setdefault("project", self.project)
        records, _summary, _keys = self.driver.execute_query(query, params, database_=self.database)
        return [r.data() if hasattr(r, "data") else dict(r) for r in records]

    def ping(self):
        """Raises when the database cannot be reached or the credentials are wrong."""
        self.driver.verify_connectivity()

    def loaded(self):
        """True once this project has been loaded at least once."""
        return self.meta("build_seq") is not None

    def features(self):
        if self._features is None:
            self._features = {"derived", "derived_attributes", "policy", "lexicon", "changelog", "terms", "questions"}
        return self._features

    def meta(self, key):
        rows = self._run("MATCH (p:OtoProject {key: $key}) RETURN p", key="%s:project" % self.project)
        return str(rows[0]["p"].get(key)) if rows and rows[0]["p"].get(key) is not None else None

    # ---- entities ----
    def _row(self, props, evidence=None):
        """The nodes-table shape from an entity's properties: JSON fields as JSON text, like SQLite."""
        props = {k: _plain(v) for k, v in props.items()}
        return {"id": props.get("id"), "type": props.get("_type"), "label": props.get("label"),
                "status": props.get("status", "current"), "as_of": props.get("as_of"),
                "valid_from": props.get("valid_from"), "valid_to": props.get("valid_to"),
                "source_doc": props.get("source_doc"),
                "supersedes": json.dumps(props["supersedes"]) if props.get("supersedes") else None,
                "superseded_by": props.get("superseded_by"), "summary": props.get("summary"),
                "attributes": props.get("attributes_json") or "{}",
                "tags": json.dumps(props.get("tags") or [], ensure_ascii=False),
                "sources": json.dumps(props.get("sources") or [], ensure_ascii=False),
                "degree": props.get("degree", 0),
                "evidence": json.dumps(evidence or [], ensure_ascii=False)}

    _ENTITY = ("MATCH (n:Entity {key: $key}) OPTIONAL MATCH (n)-[:EVIDENCED_BY]->(e:Evidence) "
               "WITH n, e ORDER BY e.index RETURN properties(n) AS props, [l IN labels(n) WHERE l <> 'Entity'][0] AS type, "
               "collect(CASE WHEN e IS NULL THEN NULL ELSE {doc: e.doc, where: e.where, quote: e.quote} END) AS evidence")

    def node(self, nid):
        rows = self._run(self._ENTITY, key="%s:%s" % (self.project, nid))
        if not rows:
            return None
        props = dict(rows[0]["props"]); props["_type"] = rows[0]["type"]
        return self._row(props, [e for e in rows[0]["evidence"] if e])

    def label(self, nid):
        rows = self._run("MATCH (n:Entity {key: $key}) RETURN n.label AS label", key="%s:%s" % (self.project, nid))
        return rows[0]["label"] if rows else nid

    def by_name(self, term):
        rows = self._run("MATCH (n:Entity {project: $project}) WHERE toLower(n.label) = toLower($term) "
                         "OR any(a IN n.names WHERE toLower(a) = toLower($term)) RETURN n.id AS id ORDER BY id", term=term)
        return [r["id"] for r in rows]

    def by_text(self, term, limit=6):
        toks = fts_tokens(term)
        if not toks:
            return []
        rows = self._run("CALL db.index.fulltext.queryNodes('oto_entity_text', $q) YIELD node, score "
                         "WHERE node.project = $project "
                         "RETURN node.id AS id ORDER BY (CASE WHEN node.status = 'current' THEN 0 ELSE 1 END), score DESC, node.id "
                         "LIMIT $limit", q=" OR ".join('"%s"' % t for t in toks), limit=int(limit))
        return [r["id"] for r in rows]

    def aliases(self, nid):
        rows = self._run("MATCH (n:Entity {key: $key}) RETURN n.aliases AS aliases", key="%s:%s" % (self.project, nid))
        return list(rows[0]["aliases"] or []) if rows else []

    def edges_out(self, nid, rel=None):
        rows = self._run("MATCH (a:Entity {key: $key})-[r]->(b:Entity) WHERE r.kind IN ['asserted', 'derived'] "
                         + ("AND type(r) IN $rels " if rel else "")
                         + "RETURN type(r) AS rel, b.id AS dst, r.status AS status, r.derived_by AS derived_by ORDER BY rel, dst",
                         key="%s:%s" % (self.project, nid), rels=_rels(rel))
        return rows

    def edges_in(self, nid, rel=None):
        rows = self._run("MATCH (a:Entity)-[r]->(b:Entity {key: $key}) WHERE r.kind IN ['asserted', 'derived'] "
                         + ("AND type(r) IN $rels " if rel else "")
                         + "RETURN type(r) AS rel, a.id AS src, r.status AS status, r.derived_by AS derived_by ORDER BY rel, src",
                         key="%s:%s" % (self.project, nid), rels=_rels(rel))
        return rows

    def edge(self, src, rel, dst):
        rows = self._run("MATCH (a:Entity {key: $a})-[r]->(b:Entity {key: $b}) WHERE type(r) = $rel AND r.kind IN ['asserted', 'derived'] "
                         "RETURN r.status AS status, r.derived_by AS derived_by, r.premises AS premises LIMIT 1",
                         a="%s:%s" % (self.project, src), b="%s:%s" % (self.project, dst), rel=rel)
        if not rows:
            return None
        r = rows[0]
        return {"status": r["status"], "derived_by": r["derived_by"],
                "premises": json.dumps(list(r["premises"] or []), ensure_ascii=False)}

    def derived_edges(self, nid, rel=None):
        rows = self._run("MATCH (a:Entity)-[r {kind: 'derived'}]->(b:Entity) WHERE (a.key = $key OR b.key = $key) "
                         + ("AND type(r) = $rel " if rel else "")
                         + "RETURN a.id AS src, type(r) AS rel, b.id AS dst, r.derived_by AS derived_by, r.premises AS premises "
                         "ORDER BY rel, src, dst", key="%s:%s" % (self.project, nid), rel=rel)
        for r in rows:
            r["premises"] = json.dumps(list(r["premises"] or []), ensure_ascii=False)
        return rows

    def derived_attributes(self, nid):
        rows = self._run("MATCH (a:DerivedAttribute)-[:DERIVED_ON]->(n:Entity {key: $key}) "
                         "RETURN a.name AS name, a.value AS value, a.derived_by AS derived_by, a.premises AS premises ORDER BY name",
                         key="%s:%s" % (self.project, nid))
        for r in rows:
            r["premises"] = json.dumps(list(r["premises"] or []), ensure_ascii=False)
        return rows

    def predecessors(self, nid):
        rows = self._run("MATCH (n:Entity {project: $project}) WHERE n.superseded_by = $nid RETURN n.id AS id ORDER BY id", nid=nid)
        return [r["id"] for r in rows]

    def search(self, query, n=8):
        toks = fts_tokens(query)
        if not toks:
            return []
        rows = self._run("CALL db.index.fulltext.queryNodes('oto_passage_text', $q) YIELD node, score "
                         "WHERE node.project = $project RETURN node.path AS path, node.title AS title, -score AS r "
                         "ORDER BY score DESC, path LIMIT $n", q=" OR ".join('"%s"' % t for t in toks), n=int(n))
        return rows

    def by_type(self, type_, state=None, limit=50):
        rows = self._run("MATCH (n:Entity {project: $project}) WHERE any(t IN $types WHERE t IN labels(n)) "
                         + ("AND n.state = $state " if state else "")
                         + "RETURN n.id AS id, n.label AS label, n.status AS status, "
                         "[l IN labels(n) WHERE l <> 'Entity'][0] AS type ORDER BY label LIMIT $limit",
                         types=_kinds(type_), state=state, limit=int(limit))
        return rows

    def status_counts(self):
        return self._run("MATCH (n:Entity {project: $project}) RETURN n.status AS status, count(n) AS c ORDER BY c DESC, status")

    def superseded(self):
        return self._run("MATCH (n:Entity {project: $project, status: 'superseded'}) "
                         "RETURN n.id AS id, n.label AS label, n.valid_to AS valid_to, n.superseded_by AS superseded_by ORDER BY id")

    def policy_findings(self, limit=50):
        rows = self._run("MATCH (f:PolicyFinding {project: $project}) OPTIONAL MATCH (f)-[:FLAGS]->(n:Entity) "
                         "RETURN f.rule AS rule, f.severity AS severity, n.id AS node_id, f.message AS message "
                         "ORDER BY (f.severity <> 'blocking'), rule, (node_id IS NOT NULL), node_id LIMIT $limit", limit=int(limit))
        return rows

    def count(self, type_=None, tag=None, attr=None, value=None):
        where = ["n.project = $project"]
        if type_:
            where.append("any(t IN $types WHERE t IN labels(n))")
        if tag:
            where.append("any(t IN n.tags WHERE t CONTAINS $tag)")
        if attr and value is not None:
            where.append("n[$attr] = $value")
        rows = self._run("MATCH (n:Entity) WHERE " + " AND ".join(where) + " RETURN count(n) AS c",
                         types=_kinds(type_), tag=tag, attr=attr, value=value)
        return rows[0]["c"]

    def group_by(self, key, type_=None, tag=None, limit=200):
        where = ["n.project = $project"]
        if type_:
            where.append("any(t IN $types WHERE t IN labels(n))")
        if tag:
            where.append("any(t IN n.tags WHERE t CONTAINS $tag)")
        if key == "type":
            g = "[l IN labels(n) WHERE l <> 'Entity'][0]"
        elif key == "status":
            g = "n.status"
        else:
            g = "n[$key]"
        rows = self._run("MATCH (n:Entity) WHERE " + " AND ".join(where) + f" RETURN {g} AS g, count(n) AS c "
                         "ORDER BY c DESC, (g IS NOT NULL), g LIMIT $limit", key=key, types=_kinds(type_), tag=tag, limit=int(limit))
        for r in rows:
            r["g"] = _plain(r["g"])
        return rows

    def lexicon(self, phrase):
        return self._run("MATCH (l:Lexicon {project: $project, phrase: $phrase}) "
                         "RETURN DISTINCT l.canonical AS canonical, l.target AS target, l.status AS status, l.note AS note",
                         phrase=phrase)

    def lexicon_fuzzy(self, phrase):
        return self._run("MATCH (l:Lexicon {project: $project}) WHERE $phrase CONTAINS l.phrase OR l.phrase CONTAINS $phrase "
                         "RETURN DISTINCT l.canonical AS canonical, l.target AS target, l.status AS status, l.note AS note LIMIT 80",
                         phrase=phrase)

    def terms(self):
        rows = self._run("MATCH (t:Term {project: $project}) RETURN t.name AS name, t.kind AS kind, t.owner AS owner, "
                         "t.spec AS spec, t.rationale AS rationale, t.iri AS iri ORDER BY kind, owner, name")
        return [dict(r, spec=json.loads(r["spec"] or "{}"), rationale=json.loads(r["rationale"] or "{}")) for r in rows]

    def questions(self):
        rows = self._run("MATCH (q:Question {project: $project}) RETURN q.id AS id, q.spec AS spec")
        return {r["id"]: json.loads(r["spec"] or "{}") for r in rows}

    def documents(self, query=None, limit=200):
        rows = self._run("MATCH (n:Entity:Document {project: $project}) "
                         + ("WHERE n.label CONTAINS $q OR n.id CONTAINS $q " if query else "")
                         + "RETURN properties(n) AS props, [l IN labels(n) WHERE l <> 'Entity'][0] AS type "
                         "ORDER BY coalesce(n.valid_from, n.as_of) DESC, n.label LIMIT $limit", q=query, limit=int(limit))
        out = []
        for r in rows:
            props = dict(r["props"]); props["_type"] = r["type"]
            row = self._row(props)
            out.append({k: row[k] for k in ("id", "label", "as_of", "valid_from", "attributes")})
        return out

    def frontier(self):
        rows = self._run("MATCH (n:Entity {project: $project}) WHERE n.as_of IS NOT NULL RETURN max(n.as_of) AS m")
        return rows[0]["m"] if rows else None

    def counts(self):
        rows = self._run(
            "MATCH (n:Entity {project: $project}) WITH count(n) AS nodes, sum(CASE WHEN n.status = 'superseded' THEN 1 ELSE 0 END) AS sup "
            "OPTIONAL MATCH (:Entity {project: $project})-[r]->(:Entity) WHERE r.kind IN ['asserted', 'derived'] "
            "WITH nodes, sup, count(r) AS edges, sum(CASE WHEN r.kind = 'derived' THEN 1 ELSE 0 END) AS derived "
            "OPTIONAL MATCH (a:DerivedAttribute {project: $project}) WITH nodes, sup, edges, derived, count(a) AS attrs "
            "OPTIONAL MATCH (f:PolicyFinding {project: $project}) "
            "RETURN nodes, sup, edges, derived, attrs, count(f) AS findings")
        r = rows[0] if rows else {}
        return {"nodes": r.get("nodes", 0), "edges": r.get("edges", 0), "superseded": r.get("sup", 0),
                "derived_edges": r.get("derived", 0), "derived_attributes": r.get("attrs", 0), "findings": r.get("findings", 0)}

    def types_current(self):
        return self._run("MATCH (n:Entity {project: $project, status: 'current'}) "
                         "WITH [l IN labels(n) WHERE l <> 'Entity'][0] AS type RETURN type, count(*) AS c ORDER BY c DESC, type")

    def rels_counts(self, limit=10):
        return self._run("MATCH (:Entity {project: $project})-[r]->(:Entity) WHERE r.kind IN ['asserted', 'derived'] "
                         "RETURN type(r) AS rel, count(r) AS c ORDER BY c DESC, rel LIMIT $limit", limit=int(limit))

    def hubs(self, limit=10):
        return self._run("MATCH (n:Entity {project: $project, status: 'current'}) "
                         "RETURN n.id AS id, n.label AS label, [l IN labels(n) WHERE l <> 'Entity'][0] AS type, "
                         "coalesce(n.degree, 0) AS degree ORDER BY degree DESC, id LIMIT $limit", limit=int(limit))

    def tags_current(self):
        rows = self._run("MATCH (n:Entity {project: $project, status: 'current'}) RETURN n.tags AS tags")
        return [json.dumps(list(r["tags"] or []), ensure_ascii=False) for r in rows]

    def docs_count(self, prefix):
        rows = self._run("MATCH (p:Passage {project: $project}) WHERE p.path STARTS WITH $prefix RETURN count(p) AS c", prefix=prefix)
        return rows[0]["c"] if rows else 0

    def changelog(self, limit=10):
        rows = self._run("MATCH (c:Changelog {project: $project}) RETURN c.at AS at, c.by AS by, c.note AS note, "
                         "c.nodes_added AS nodes_added, c.nodes_changed AS nodes_changed, c.edges_added AS edges_added, "
                         "c.retired AS retired, c.sources AS sources ORDER BY at DESC LIMIT $limit", limit=int(limit))
        return rows

    # ---- the whole graph, for a payload ----
    def all_nodes(self):
        rows = self._run("MATCH (n:Entity {project: $project}) OPTIONAL MATCH (n)-[:EVIDENCED_BY]->(e:Evidence) "
                         "WITH n, e ORDER BY n.id, e.index RETURN properties(n) AS props, "
                         "[l IN labels(n) WHERE l <> 'Entity'][0] AS type, "
                         "collect(CASE WHEN e IS NULL THEN NULL ELSE {doc: e.doc, where: e.where, quote: e.quote} END) AS evidence "
                         "ORDER BY props.id")
        out = []
        for r in rows:
            props = dict(r["props"]); props["_type"] = r["type"]
            out.append(self._row(props, [e for e in r["evidence"] if e]))
        return out

    def all_aliases(self):
        rows = self._run("MATCH (n:Entity {project: $project}) RETURN n.id AS id, n.aliases AS aliases ORDER BY id")
        return {r["id"]: list(r["aliases"] or []) for r in rows if r["aliases"]}

    def all_edges(self):
        rows = self._run("MATCH (a:Entity {project: $project})-[r]->(b:Entity) WHERE r.kind IN ['asserted', 'derived'] "
                         "RETURN a.id AS src, type(r) AS rel, b.id AS dst, r.status AS status, r.derived_by AS derived_by, "
                         "r.premises AS premises ORDER BY src, rel, dst")
        for r in rows:
            r["premises"] = json.dumps(list(r["premises"] or []), ensure_ascii=False) if r["premises"] is not None else None
        return rows

    def all_derived_attributes(self):
        rows = self._run("MATCH (a:DerivedAttribute {project: $project})-[:DERIVED_ON]->(n:Entity) "
                         "RETURN n.id AS node_id, a.name AS name, a.value AS value, a.derived_by AS derived_by, "
                         "a.premises AS premises ORDER BY node_id, name")
        for r in rows:
            r["premises"] = json.dumps(list(r["premises"] or []), ensure_ascii=False)
        return rows

    def all_lexicon(self):
        return self._run("MATCH (l:Lexicon {project: $project}) RETURN l.phrase AS phrase, l.canonical AS canonical, "
                         "l.target AS target, l.status AS status, l.note AS note ORDER BY phrase, canonical, target")

    def passages(self):
        return self._run("MATCH (p:Passage {project: $project}) RETURN p.path AS path, p.title AS title, p.body AS body "
                         "ORDER BY path")
