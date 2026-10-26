# -*- coding: utf-8 -*-
"""Usage (roadmap C4): who reads a table and how, read from the store's query log, never guessed.

    oto data usage --log <file> | --connector postgres|bigquery [--reader principal=node.id ...] --store datastore.<id> --at YYYY-MM-DD

A query log is a list of statements, each with how often it ran and, when the store says, who ran
it: pg_stat_statements with the role, BigQuery's job history with the user, or a file a person
exported (JSON, JSON lines, or one statement per line). Each statement is read for the tables it
touches and classified by one deterministic rule: a write, or a read by key, is `transactional`
(an application serving a user); an aggregate, a grouping, a window, a DISTINCT, a scan with no
WHERE or a range over many rows is `analytical` (a report or a model). One `Usage` per principal
and table, its kind the calls-weighted majority (a tie is transactional: the reader you must tell
before a change), its evidence `query_log`, `use_of` the table and `used_by` the component, team or
role the person maps the principal to (`--reader` or `usage.readers` in project.config.json; a
principal nobody mapped is a gap, said with how to map it, never a reader invented).

The statement text is hashed into the usage document (`build/documents/usage-<store>-<source>.md`,
kept in `archive/`) and never kept, so a log can be read without copying what the queries said:
the document names each statement shape by its hash, its kind and its calls. Counts change every
read, so they are the document's and not the fact's: a `Usage` carries only its kind and evidence,
and the same log read twice is one set of facts. A kind that flipped is a supersession the merge
refuses; the command says so before the gates see it. The catalog says what tables exist; a
statement on a table the graph lacks is a gap, and the store's own tables (pg_*, sqlite_*,
INFORMATION_SCHEMA) are not the estate's.
"""
import hashlib
import json
import os
import re

from .data import DataError, _graph_ids, _slug, store_slug, table_id
from .lineage import statement_tables

USAGE, DOCUMENT = "Usage", "Document"
DOC_KIND = "usage"
TRANSACTIONAL, ANALYTICAL = "transactional", "analytical"
UNATTRIBUTED = "unattributed"
SYSTEM = re.compile(r"^(pg_|sqlite_|information_schema$|__tables__$|duckdb_)", re.I)
_SYSTEM_SCHEMA = re.compile(r"\b(?:information_schema|pg_catalog|sys)\s*\.", re.I)

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_STRING = re.compile(r"'(?:[^']|'')*'")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?\b")
_PARAM = re.compile(r"(?<![\w])(?:\$\d+|:\w+|%s|%\(\w+\)s)")
_ANALYTICAL = re.compile(r"\b(?:COUNT|SUM|AVG|MIN|MAX|STDDEV\w*|VAR\w*|PERCENTILE\w*|APPROX_\w+|ARRAY_AGG|STRING_AGG|LISTAGG|GROUP_CONCAT)\s*\(|"
                         r"\bGROUP\s+BY\b|\bHAVING\b|\bOVER\s*\(|\bDISTINCT\b|\bUNION\b|\bINTERSECT\b|\bEXCEPT\b", re.I)
_WRITE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|MERGE|REPLACE|UPSERT)\b", re.I)
_SELECT = re.compile(r"^\s*(?:WITH\b|SELECT\b)", re.I)
_EQUALITY = re.compile(r"\bWHERE\b.*?(?:(?<![<>!])=\s*\?|\?\s*=(?![=<>])|\bIN\s*\(\s*\?)", re.I | re.S)   # a key, not a range


class UsageError(DataError):
    """A refusal, in words the person can act on."""


# ---- shapes ----

def shape(sql):
    """The statement with comments gone, literals and parameters as `?`, whitespace as one space,
    lowercased: two statements of one shape are one shape."""
    text = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql or ""))
    text = _STRING.sub("?", text)
    text = _PARAM.sub("?", text)
    text = _NUMBER.sub("?", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def shape_hash(sql):
    return hashlib.sha256(shape(sql).encode("utf-8")).hexdigest()[:12]


def tables_of(sql):
    """{"reads": [...], "writes": [...]}: the tables a statement touches, by their own names."""
    return statement_tables(_BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql or "")))


def is_system(sql, touched):
    """The store's own tables (pg_*, sqlite_*, INFORMATION_SCHEMA, pg_catalog) are not the estate's."""
    return bool(_SYSTEM_SCHEMA.search(sql or "")) or (bool(touched) and all(SYSTEM.match(t) for t in touched))


def classify(sql):
    """`transactional`, `analytical`, or None when the statement uses no table of the estate's."""
    tables = tables_of(sql)
    touched = tables["reads"] + tables["writes"]
    if not touched or is_system(sql, touched):
        return None
    if _WRITE.match(sql):
        return TRANSACTIONAL
    if not _SELECT.match(sql):
        return None
    normalized = shape(sql)
    if _ANALYTICAL.search(normalized):
        return ANALYTICAL
    if not re.search(r"\bwhere\b", normalized):
        return ANALYTICAL
    if _EQUALITY.search(normalized):
        return TRANSACTIONAL
    return ANALYTICAL


# ---- the log ----

def read_log_file(path):
    """A log a person exported: a JSON list or JSON lines of {sql|query, calls?, by|user|principal?},
    or one statement per line. -> [{"by", "sql", "calls"}]."""
    if not os.path.isfile(path):
        raise UsageError("no such log: %s" % path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.strip()
    entries = []
    if stripped.startswith("["):
        try:
            raw = json.loads(stripped)
        except ValueError as exc:
            raise UsageError("%s is not JSON: %s" % (path, exc))
        if not isinstance(raw, list):
            raise UsageError("%s: a JSON log is a list of statements" % path)
    elif stripped.startswith("{"):
        raw = []
        for n, line in enumerate(stripped.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError as exc:
                if n == 1:
                    raise UsageError("%s: a JSON log is a list of statements, or one JSON object per line (%s)" % (path, exc))
                raise UsageError("%s line %d is not JSON: %s" % (path, n, exc))
            raw.append(item)
        if len(raw) == 1 and not any(k in raw[0] for k in ("sql", "query")):
            raise UsageError("%s: a JSON log is a list of statements, or one JSON object per line" % path)
    else:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("--"):
                entries.append({"by": None, "sql": line, "calls": 1})
        return entries
    for item in raw:
        if not isinstance(item, dict):
            raise UsageError("%s: every statement is an object with `sql`" % path)
        sql = item.get("sql") or item.get("query")
        if not sql:
            continue
        entries.append(_entry(item.get("by") or item.get("user") or item.get("principal") or item.get("user_email"), sql, item.get("calls")))
    return entries


def _entry(by, sql, calls):
    try:
        n = int(calls) if calls not in (None, "") else 1
    except (TypeError, ValueError):
        n = 1
    return {"by": (str(by).strip() or None) if by is not None else None, "sql": str(sql), "calls": max(n, 1)}


def entries_from_connector(log):
    """What an overlay connector's query_log returns -> the same shape as `read_log_file`."""
    return [_entry(e.get("by"), e.get("sql") or e.get("query") or "", e.get("calls")) for e in log if (e.get("sql") or e.get("query"))]


def uses(entries):
    """-> ([{"reader", "table", "kind", "calls", "statements": [{"hash", "kind", "calls"}]}, ...],
    {"no_table": n, "system": n}). One use per principal and table; a statement that touches two
    tables is a use of each."""
    found, order, left_out = {}, [], {"no_table": 0, "system": 0}
    for e in entries:
        tables = tables_of(e["sql"])
        touched = tables["reads"] + tables["writes"]
        if not touched:
            left_out["no_table"] += 1
            continue
        if is_system(e["sql"], touched):
            left_out["system"] += 1
            continue
        kind = classify(e["sql"])
        if kind is None:
            left_out["no_table"] += 1
            continue
        h = shape_hash(e["sql"])
        seen = set()
        for t in touched:
            if SYSTEM.match(t) or t.lower() in seen:
                continue
            seen.add(t.lower())
            key = (e["by"], t.lower())
            if key not in found:
                found[key] = {"reader": e["by"], "table": t, "kind": None, "calls": 0, "statements": [], "_by_kind": {TRANSACTIONAL: 0, ANALYTICAL: 0}}
                order.append(key)
            use = found[key]
            use["calls"] += e["calls"]
            use["_by_kind"][kind] += e["calls"]
            for s in use["statements"]:
                if s["hash"] == h:
                    s["calls"] += e["calls"]
                    break
            else:
                use["statements"].append({"hash": h, "kind": kind, "calls": e["calls"]})
    out = []
    for key in order:
        use = found[key]
        by_kind = use.pop("_by_kind")
        use["kind"] = TRANSACTIONAL if by_kind[TRANSACTIONAL] >= by_kind[ANALYTICAL] else ANALYTICAL
        use["statements"].sort(key=lambda s: (-s["calls"], s["hash"]))
        out.append(use)
    return out, left_out


# ---- the document and the proposal ----

def _principal(use):
    return use["reader"] or UNATTRIBUTED


def use_line(use):
    return "%s uses %s (%s)" % (_principal(use), use["table"], use["kind"])


def usage_id(use):
    return "usage.%s-%s" % (_slug(_principal(use)), _slug(use["table"]))


def document(found, left_out, readers, store, source, at):
    source_said = "the %s query log" % source if source != "log" else "the log"
    title = "Usage of %s from %s" % (store, source_said)
    lines = ["# %s" % title, "", "Read from %s on %s by `oto data usage`: %d use(s) of %d table(s) by %d principal(s). The statement text is "
             "hashed and never kept: a line names a statement shape by its hash, its kind and its calls. One section per principal "
             "and table, its kind the calls-weighted majority. Each fact in the graph quotes its line here."
             % (source_said, at, len(found), len({u["table"].lower() for u in found}), len({_principal(u) for u in found})), ""]
    for use in found:
        lines += ["## %s" % use_line(use), ""]
        for s in use["statements"]:
            lines.append("- %s %s, %d call(s)" % (s["hash"], s["kind"], s["calls"]))
        lines.append("")
    principals = []
    for use in found:
        if _principal(use) not in principals:
            principals.append(_principal(use))
    lines += ["## Readers", ""]
    for p in principals:
        lines.append("- %s: %s" % (p, readers.get(p) or ("the log names no reader" if p == UNATTRIBUTED else "not mapped")))
    lines.append("")
    if left_out["no_table"] or left_out["system"]:
        lines += ["## Left out", ""]
        if left_out["no_table"]:
            lines.append("- %d statement(s) that use no table" % left_out["no_table"])
        if left_out["system"]:
            lines.append("- %d statement(s) on the store's own tables" % left_out["system"])
        lines.append("")
    return title, "\n".join(lines).rstrip() + "\n"


def propose(found, left_out, readers, store_id, doc, at, graph_ids, source):
    """({"source_doc", "as_of", "nodes", "edges"}, gaps). A use is proposed when its table is in
    the graph; a mapped reader must be too, and an unmapped principal is a gap."""
    store = store_slug(store_id)
    title, _text = document(found, left_out, readers, store, source, at)
    nodes = [{"id": "document.%s" % doc, "type": DOCUMENT, "label": title,
              "summary": "Who uses the tables of %s and how, as the %s said; the date is the fact's own." % (store, "query log" if source != "log" else "log"),
              "attributes": {"kind": DOC_KIND}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": title}]}]
    edges, gaps, unmapped = [], [], []
    for use in found:
        tid = table_id(store, use["table"])
        if tid not in graph_ids:
            gaps.append("%s uses %s, a table the graph lacks (%s)" % (_principal(use), use["table"], tid))
            continue
        uid = usage_id(use)
        principal = _principal(use)
        summary = "%s's use of %s is %s, as the query log shows." % (principal, use["table"], use["kind"])
        nodes.append({"id": uid, "type": USAGE, "label": "%s uses %s" % (principal, use["table"]), "summary": summary,
                      "attributes": {"kind": use["kind"], "evidence": "query_log"}, "valid_from": at,
                      "evidence": [{"doc": doc, "where": principal, "quote": use_line(use)}]})
        edges.append({"from": uid, "rel": "use_of", "to": tid})
        if readers.get(principal):
            edges.append({"from": uid, "rel": "used_by", "to": readers[principal]})
        elif principal not in unmapped:
            unmapped.append(principal)
    for p in unmapped:
        if p == UNATTRIBUTED:
            gaps.append("the log names no reader: its uses are unattributed until a person says who (--reader %s=<component|team|role id>)" % UNATTRIBUTED)
        else:
            gaps.append("%s is not mapped to a component, team or role (--reader %s=<node id>, or usage.readers in project.config.json)" % (p, p))
    return {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": edges}, gaps


def changed_kinds(project, proposal):
    """The uses whose kind differs from the live graph's: supersessions the merge will refuse."""
    from .curate import session as _session
    live = {n.get("id"): n for n in _session.live(project).get("nodes") or []}
    out = []
    for n in proposal["nodes"]:
        if n["type"] != USAGE or n["id"] not in live:
            continue
        was = (live[n["id"]].get("attributes") or {}).get("kind")
        if was and was != n["attributes"]["kind"]:
            out.append((n["id"], was, n["attributes"]["kind"]))
    return out


def parse_readers(pairs):
    """--reader principal=node.id, repeated -> {principal: node id}."""
    out = {}
    for pair in pairs or []:
        principal, sep, node = str(pair).partition("=")
        if not sep or not principal.strip() or not node.strip():
            raise UsageError("--reader takes principal=node.id, the principal as the log names it and the component, team or role it is: not %r" % pair)
        out[principal.strip()] = node.strip()
    return out


def usage(project, connector_name=None, path=None, log=None, store_id=None, at=None, readers=None, settings=None):
    """Read the log, write the document and the proposal. Returns {"doc", "document", "archive",
    "proposal", "store", "source", "uses", "gaps", "changed", "left_out"}."""
    if bool(log) == bool(connector_name):
        raise UsageError("one source at a time: --log <file> (a log a person exported) or --connector postgres|bigquery (the store's own log)")
    if not at or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(at)):
        raise UsageError("--at YYYY-MM-DD is required: the date the log was read is never defaulted")
    if not store_id or not str(store_id).startswith("datastore."):
        raise UsageError("--store datastore.<id> names the DataStore the tables are part of")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if USAGE not in classes:
        raise UsageError("the vocabulary declares no Usage: the data ontology does (oto init --ontology data, or compose it)")
    configured = ((project.config().get("usage") or {}).get("readers") or {}) if hasattr(project, "config") else {}
    reader_map = dict(configured)
    reader_map.update(readers or {})
    if log:
        entries, source = read_log_file(log), "log"
    else:
        from . import connectors as _connectors
        connector = _connectors.get(connector_name)
        if connector is None or "overlay" not in (connector.MANIFEST.get("modes") or []):
            raise UsageError("no overlay connector %r" % connector_name)
        if settings is None:
            settings = {"path": path} if path is not None else connector.settings(project)
        session = connector.connect(settings)
        try:
            raw = connector.query_log(session)
        finally:
            connector.close(session)
        if not raw:
            raise UsageError("the %s overlay has no query log to read (SQLite keeps none; Postgres needs pg_stat_statements): "
                             "export one and pass --log <file>" % connector_name)
        entries, source = entries_from_connector(raw), connector_name
    graph_ids = _graph_ids(project)
    if store_id not in graph_ids:
        raise UsageError("the graph holds no %s. The data layer describes a store the estate declares: record the DataStore first, "
                         "then introspect it, then read its log" % store_id)
    missing = sorted(v for v in reader_map.values() if v not in graph_ids)
    if missing:
        raise UsageError("the reader map names what the graph lacks: %s. A reader is a component, team or role the estate declares" % ", ".join(missing))
    found, left_out = uses(entries)
    store = store_slug(store_id)
    doc = "usage-%s-%s" % (store, source)
    title, text = document(found, left_out, reader_map, store, source, at)
    proposal, gaps = propose(found, left_out, reader_map, store_id, doc, at, graph_ids, source)
    changed = changed_kinds(project, proposal)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, doc + ".json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "store": store_id, "source": source,
            "uses": sum(1 for n in proposal["nodes"] if n["type"] == USAGE), "gaps": gaps, "changed": changed, "left_out": left_out}
