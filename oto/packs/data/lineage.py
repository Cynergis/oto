# -*- coding: utf-8 -*-
"""Lineage (roadmap C3): what loads a table and where its rows come from, read from what the ETL
already says, never guessed.

    oto data lineage --dbt target/manifest.json --store datastore.<id> --at YYYY-MM-DD
    oto data lineage --sql <dir|file> [--tool <name>] --store datastore.<id> --at YYYY-MM-DD

Two readers, both deterministic. The dbt reader takes the manifest dbt writes: a model, seed or
snapshot is a `LoadJob` (tool `dbt`, schedule from `meta.schedule` when the project says one) that
loads the table it materializes and is sourced from the models and sources it depends on; an
ephemeral model is a CTE, so a job that depends on one is sourced from whatever the ephemeral model
reads; a source is a `Feed` whose kind the `loader` suggests; a seed is a table loaded from a file.
The SQL reader takes a file or a directory of `.sql` files, one job per file: INSERT, MERGE,
CREATE ... AS and COPY or LOAD DATA say what the job writes, FROM and JOIN in those statements say
what it reads, a COPY or LOAD path is a `Feed` of kind `file`, a table the file both writes and
reads is its own staging and neither, and `-- schedule:` and `-- tool:` comments name the rest.
Comments, string literals and CTE names are not tables.

Either reader becomes a lineage document in the corpus (`build/documents/lineage-<store>-<reader>.md`,
kept in `archive/`), one section per job, and a proposal in the data vocabulary: `LoadJob` and
`Feed` nodes quoting their lines, `loaded_by` and `sourced_from` edges to tables the graph already
holds. The catalog says what tables exist (`oto data introspect`); lineage says how they are
loaded. A job that loads or reads a table the graph lacks is a gap, reported and never a table
invented here. The proposal goes through the gates like any other change.
"""
import json
import os
import re

from . import DataError, _graph_ids, _slug, store_slug, table_id

JOB, FEED, DOCUMENT = "LoadJob", "Feed", "Document"
DOC_KIND = "lineage"
DEFAULT_TOOL = "sql"
DBT_JOBS = ("model", "seed", "snapshot")
FEED_KINDS = (("file", ("file", "s3", "gcs", "blob", "sftp", "ftp", "csv", "drop", "bucket")),
              ("api", ("api", "http", "rest")),
              ("stream", ("kafka", "kinesis", "pubsub", "pub/sub", "stream", "event")))


class LineageError(DataError):
    """A refusal, in words the person can act on."""


# ---- the dbt reader ----

def _feed_kind(loader):
    text = (loader or "").lower()
    for kind, words in FEED_KINDS:
        if any(w in text for w in words):
            return kind
    return "database"


def read_dbt(manifest):
    """A dbt manifest -> {"reader", "tool", "about", "jobs", "feeds"}. Jobs are the models, seeds and
    snapshots; an ephemeral model collapses to what it reads; a test is nothing here."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("nodes"), dict) or not isinstance(manifest.get("metadata"), dict):
        raise LineageError("not a dbt manifest: expected `metadata`, `nodes` and `sources` as dbt writes target/manifest.json")
    meta = manifest["metadata"]
    about = "dbt %s, project %s, generated %s" % (meta.get("dbt_version") or "?", meta.get("project_name") or "?", meta.get("generated_at") or "?")
    nodes, sources = manifest["nodes"], manifest.get("sources") or {}
    feeds, feed_order = {}, []

    def feed(name, fid, kind, label, summary):
        if name not in feeds:
            feeds[name] = {"name": name, "id": fid, "kind": kind, "label": label, "summary": summary}
            feed_order.append(name)
        return {"feed": name}

    def table_name(node):
        return node.get("alias") or node.get("name")

    def materialized(node):
        return ((node.get("config") or {}).get("materialized") or node.get("resource_type") or "").lower()

    def resolve(uid, seen):
        """What a dependency contributes as a source: a feed, a table, or (ephemeral) its own sources."""
        if uid in seen:
            return []
        seen = seen | {uid}
        if uid in sources:
            s = sources[uid]
            name = "%s.%s" % (s.get("source_name") or "?", s.get("identifier") or s.get("name") or "?")
            summary = (s.get("description") or "").strip() or "The dbt source %s in %s.%s." % (name, s.get("database") or "?", s.get("schema") or "?")
            return [feed(name, "feed.%s-%s" % (_slug(s.get("source_name")), _slug(s.get("identifier") or s.get("name"))),
                         _feed_kind(s.get("loader")), name, summary)]
        node = nodes.get(uid)
        if not node or node.get("resource_type") not in DBT_JOBS:
            return []
        if materialized(node) == "ephemeral":
            out = []
            for dep in (node.get("depends_on") or {}).get("nodes") or []:
                out.extend(resolve(dep, seen))
            return out
        return [{"table": table_name(node)}]

    jobs = []
    for uid, node in nodes.items():
        if node.get("resource_type") not in DBT_JOBS or materialized(node) == "ephemeral":
            continue
        name = node.get("name") or table_name(node)
        schedule = (node.get("meta") or {}).get("schedule") or ((node.get("config") or {}).get("meta") or {}).get("schedule")
        if node.get("resource_type") == "seed":
            path = node.get("original_file_path") or ("seeds/%s.csv" % name)
            summary = "The dbt seed file %s." % path
            if (node.get("description") or "").strip():
                summary += " " + node["description"].strip()
            srcs = [feed("seed %s" % name, "feed.dbt-seed-%s" % _slug(name), "file", "seed %s" % name, summary)]
        else:
            srcs, seen = [], set()
            for dep in (node.get("depends_on") or {}).get("nodes") or []:
                for s in resolve(dep, frozenset()):
                    key = json.dumps(s, sort_keys=True)
                    if key not in seen:
                        seen.add(key)
                        srcs.append(s)
        jobs.append({"name": name, "tool": "dbt", "schedule": (schedule or "").strip() or None, "loads": [table_name(node)],
                     "sources": srcs, "where": node.get("original_file_path") or name})
    return {"reader": "dbt", "tool": "dbt", "about": about, "jobs": jobs, "feeds": [feeds[n] for n in feed_order]}


# ---- the SQL reader ----

NAME = r"[\w$.\"`\[\]]+"
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HEADER = re.compile(r"--\s*(schedule|tool)\s*:\s*([^\n]+)", re.I)
_LITERAL = re.compile(r"'(?:[^']|'')*'")
_FROM_IN_FUNCTION = re.compile(r"\b(?:EXTRACT|SUBSTRING|TRIM|POSITION|OVERLAY)\s*\([^()]*\bFROM\b[^()]*\)", re.I)
_COPY = re.compile(r"\bCOPY\s+(?:INTO\s+)?(" + NAME + r")\b.*?\bFROM\s+(?:'([^']+)'|(@\S+))", re.I | re.S)
_LOAD = re.compile(r"\bLOAD\s+DATA\b.*?\bINFILE\s+'([^']+)'.*?\bINTO\s+TABLE\s+(" + NAME + r")", re.I | re.S)
_WRITES = (re.compile(r"\bINSERT\s+(?:OVERWRITE\s+)?(?:INTO\s+)?(?:TABLE\s+)?(" + NAME + r")", re.I),
           re.compile(r"\bMERGE\s+INTO\s+(" + NAME + r")", re.I),
           re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+|TRANSIENT\s+)?(?:TABLE|(?:MATERIALIZED\s+)?VIEW)\s+"
                      r"(?:IF\s+NOT\s+EXISTS\s+)?(" + NAME + r")(?:\s*\([^)]*\))?\s+AS\b", re.I | re.S))
_UPDATE = re.compile(r"\bUPDATE\s+(?:ONLY\s+)?(" + NAME + r")", re.I)
_DELETE = re.compile(r"\bDELETE\s+FROM\s+(?:ONLY\s+)?(" + NAME + r")", re.I)
_READS = re.compile(r"\b(?:FROM|JOIN)\s+(" + NAME + r")(?![\w$.\"`\[\]]|\s*\()", re.I)   # a whole name, not a function call
_CTE = re.compile(r"\b(" + NAME + r")\s+(?:\([^)]*\)\s*)?AS\s*\(", re.I)
_SKIP = re.compile(r"^\s*(?:DELETE|UPDATE|TRUNCATE|DROP|ALTER|GRANT|REVOKE|SET|BEGIN|COMMIT|ROLLBACK|START|END|USE|CALL|EXEC|EXECUTE|DECLARE"
                   r"|COPY|LOAD)\b", re.I)                # COPY and LOAD DATA were harvested with their paths above
_KEYWORDS = {"select", "where", "values", "dual", "lateral", "unnest", "only", "with"}


def _plain(name):
    """`"public"."t"` / `proj.ds.t` -> t, the table's own name within its store."""
    cleaned = re.sub(r"[\"`\[\]]", "", name).strip().rstrip(",;")
    return cleaned.rsplit(".", 1)[-1] if cleaned else cleaned


def _feed_of_path(path):
    """The directory of a COPY or LOAD path names the feed: one feed for every file dropped there."""
    path = path.strip()
    head, sep, tail = path.rpartition("/")
    if sep and head and not head.endswith(":/"):
        return head
    return path


def statement_tables(sql):
    """One statement, comments already gone -> {"reads": [...], "writes": [...]}: the tables it
    reads (FROM, JOIN, UPDATE ... FROM, DELETE ... USING) and writes (INSERT, MERGE, UPDATE, DELETE,
    CREATE ... AS), by their own names, in order, each once; CTE names and function calls are not
    tables."""
    blank = _FROM_IN_FUNCTION.sub(lambda m: " " * len(m.group(0)), _LITERAL.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql or ""))
    writes = []
    for pattern in _WRITES + (_UPDATE, _DELETE):
        for m in pattern.finditer(blank):
            t = _plain(m.group(1))
            if t and t.lower() not in {x.lower() for x in writes}:
                writes.append(t)
    ctes = {_plain(m.group(1)).lower() for m in _CTE.finditer(blank)}
    deleted = {_plain(m.group(1)).lower() for m in _DELETE.finditer(blank)}     # DELETE FROM t writes t, it does not read it
    reads = []
    for m in _READS.finditer(blank):
        t = _plain(m.group(1))
        if not t or t.lower() in _KEYWORDS or t.lower() in ctes or t.lower() in deleted or t.lower() in {x.lower() for x in reads}:
            continue
        reads.append(t)
    return {"reads": reads, "writes": writes}


def scan_sql(text, filename):
    """One SQL file -> one job: {"name", "tool", "tool_declared", "schedule", "loads", "sources", "feeds", "where"}.
    `tool` is the `-- tool:` comment or the default; `tool_declared` says which."""
    headers = {k.lower(): v.strip() for k, v in _HEADER.findall(text)}
    name = re.sub(r"\.sql$", "", filename.replace(os.sep, "/"), flags=re.I)
    code = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", text))
    feeds, feed_order, events = {}, [], []          # events: ("load", table, pos) | ("read", table, pos) | ("feed", name, pos)
    for m in _COPY.finditer(code):
        path = _feed_of_path(m.group(2) or m.group(3))
        events.append(("load", _plain(m.group(1)), m.start()))
        events.append(("feed", path, m.start() + 1))
        feeds.setdefault(path, {"name": path, "id": "feed.%s" % _slug(path), "kind": "file", "label": path,
                                "summary": "Files at %s, copied in by the job." % path})
        if path not in feed_order:
            feed_order.append(path)
    for m in _LOAD.finditer(code):
        path = _feed_of_path(m.group(1))
        events.append(("load", _plain(m.group(2)), m.start()))
        events.append(("feed", path, m.start() + 1))
        feeds.setdefault(path, {"name": path, "id": "feed.%s" % _slug(path), "kind": "file", "label": path,
                                "summary": "Files at %s, loaded by the job." % path})
        if path not in feed_order:
            feed_order.append(path)
    blank = _FROM_IN_FUNCTION.sub(lambda m: " " * len(m.group(0)), _LITERAL.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", code))
    offset = 0
    for statement in blank.split(";"):
        base = offset
        offset += len(statement) + 1
        if _SKIP.match(statement):
            continue
        targets = []
        for pattern in _WRITES:
            for m in pattern.finditer(statement):
                targets.append((_plain(m.group(1)), base + m.start()))
        if not targets:
            continue
        ctes = {_plain(m.group(1)).lower() for m in _CTE.finditer(statement)}
        for t, pos in targets:
            events.append(("load", t, pos))
        for m in _READS.finditer(statement):
            t = _plain(m.group(1))
            if not t or t.lower() in _KEYWORDS or t.lower() in ctes or t.lower() in {x.lower() for x, _p in targets}:
                continue
            events.append(("read", t, base + m.start()))
    events.sort(key=lambda e: e[2])
    loads, reads, sources = [], [], []
    for kind, what, _pos in events:
        if kind == "load" and what.lower() not in {x.lower() for x in loads}:
            loads.append(what)
        elif kind == "read" and what.lower() not in {x.lower() for x in reads}:
            reads.append(what)
    staging = {x.lower() for x in loads} & {x.lower() for x in reads}
    loads = [x for x in loads if x.lower() not in staging]
    seen = set()
    for kind, what, _pos in events:
        if kind == "feed" and ("feed", what) not in seen:
            seen.add(("feed", what))
            sources.append({"feed": what})
        elif kind == "read" and what.lower() not in staging and ("table", what.lower()) not in seen:
            seen.add(("table", what.lower()))
            sources.append({"table": what})
    return {"name": name, "tool": headers.get("tool") or DEFAULT_TOOL, "tool_declared": bool(headers.get("tool")),
            "schedule": headers.get("schedule") or None, "loads": loads, "sources": sources, "feeds": [feeds[n] for n in feed_order],
            "where": filename}


def read_sql(path, tool=None):
    """A .sql file or a directory of them -> the same shape as `read_dbt`, one job per file."""
    if os.path.isdir(path):
        files = []
        for root, _dirs, names in os.walk(path):
            for n in sorted(names):
                if n.lower().endswith(".sql"):
                    files.append(os.path.join(root, n))
        files.sort()
        if not files:
            raise LineageError("no .sql file(s) under %s" % path)
        base = path
    elif os.path.isfile(path):
        files, base = [path], os.path.dirname(path)
    else:
        raise LineageError("no such file or directory: %s" % path)
    jobs, feeds, feed_order = [], {}, []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            job = scan_sql(fh.read(), os.path.relpath(f, base))
        if tool and not job.pop("tool_declared"):      # the flag names the runner; a `-- tool:` comment in the file wins
            job["tool"] = tool
        for feed in job.pop("feeds"):
            if feed["name"] not in feeds:
                feeds[feed["name"]] = feed
                feed_order.append(feed["name"])
        jobs.append(job)
    about = "%d SQL file(s) under %s" % (len(files), path) if os.path.isdir(path) else "the SQL file %s" % path
    return {"reader": "sql", "tool": tool or DEFAULT_TOOL, "about": about, "jobs": jobs, "feeds": [feeds[n] for n in feed_order]}


# ---- the document and the proposal ----

def job_line(job):
    return "%s (%s)" % (job["name"], job["tool"])


def feed_line(feed):
    return "%s (%s)" % (feed["name"], feed["kind"])


def document(read, store, at):
    reader = "dbt" if read["reader"] == "dbt" else "SQL"
    title = "Lineage of %s from %s" % (store, reader)
    lines = ["# %s" % title, "", "Read from %s on %s by `oto data lineage`. One section per job: what it loads, where it is "
             "sourced from, when and with what. The Feeds section names each source behind the jobs. Each fact in the graph "
             "quotes its line here." % (read["about"], at), ""]
    for job in read["jobs"]:
        lines += ["## %s" % job_line(job), ""]
        for t in job["loads"]:
            lines.append("- loads %s" % t)
        for s in job["sources"]:
            lines.append("- sourced from %s" % ("feed %s" % s["feed"] if "feed" in s else "table %s" % s["table"]))
        if job.get("schedule"):
            lines.append("- schedule %s" % job["schedule"])
        lines.append("")
    if read["feeds"]:
        lines += ["## Feeds", ""]
        for feed in read["feeds"]:
            lines.append("- %s: %s" % (feed_line(feed), feed["summary"]))
        lines.append("")
    return title, "\n".join(lines).rstrip() + "\n"


def job_id(read, job):
    return "loadjob.%s%s" % ("dbt-" if read["reader"] == "dbt" else "", _slug(job["name"]))


def propose(read, store_id, doc, at, graph_ids):
    """The proposal and the gaps: ({"source_doc", "as_of", "nodes", "edges"}, [gap, ...]). A job is
    proposed when at least one table it loads is in the graph; a table it loads or reads that the
    graph lacks is a gap."""
    store = store_slug(store_id)
    title, _text = document(read, store, at)
    nodes = [{"id": "document.%s" % doc, "type": DOCUMENT, "label": title,
              "summary": "The lineage of %s as the %s reader read it; the date is the fact's own." % (store, read["reader"]),
              "attributes": {"kind": DOC_KIND}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": title}]}]
    edges, gaps, feeds_used = [], [], []
    by_name = {f["name"]: f for f in read["feeds"]}
    for job in read["jobs"]:
        loads = [(t, table_id(store, t)) for t in job["loads"]]
        known = [(t, tid) for t, tid in loads if tid in graph_ids]
        for t, tid in loads:
            if tid not in graph_ids:
                gaps.append("%s loads a table the graph lacks: %s (%s)" % (job["name"], t, tid))
        if not known:
            if not loads:
                gaps.append("%s loads nothing the scanner recognises" % job["name"])
            continue
        jid = job_id(read, job)
        attributes = {"tool": job["tool"]}
        if job.get("schedule"):
            attributes["schedule"] = job["schedule"]
        said = ["feed %s" % s["feed"] if "feed" in s else "table %s" % s["table"] for s in job["sources"]]
        summary = "Loads %s%s, with %s." % (", ".join(t for t, _tid in known), (" from " + ", ".join(said)) if said else "", job["tool"])
        nodes.append({"id": jid, "type": JOB, "label": job["name"], "summary": summary, "attributes": attributes, "valid_from": at,
                      "evidence": [{"doc": doc, "where": job["name"], "quote": job_line(job)}]})
        for _t, tid in known:
            edges.append({"from": tid, "rel": "loaded_by", "to": jid})
        for s in job["sources"]:
            if "feed" in s:
                feed = by_name[s["feed"]]
                if feed["name"] not in feeds_used:
                    feeds_used.append(feed["name"])
                edges.append({"from": jid, "rel": "sourced_from", "to": feed["id"]})
            else:
                tid = table_id(store, s["table"])
                if tid in graph_ids:
                    edges.append({"from": jid, "rel": "sourced_from", "to": tid})
                else:
                    gaps.append("%s is sourced from a table the graph lacks: %s (%s)" % (job["name"], s["table"], tid))
    for name in feeds_used:
        feed = by_name[name]
        nodes.append({"id": feed["id"], "type": FEED, "label": feed["label"], "summary": feed["summary"], "attributes": {"kind": feed["kind"]},
                      "valid_from": at, "evidence": [{"doc": doc, "where": "feeds", "quote": feed_line(feed)}]})
    return {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": edges}, gaps


def lineage(project, dbt=None, sql=None, store_id=None, at=None, tool=None):
    """Read, write the document and the proposal. Returns {"doc", "document", "archive", "proposal",
    "store", "reader", "about", "jobs", "feeds", "gaps"}."""
    if bool(dbt) == bool(sql):
        raise LineageError("one reader at a time: --dbt <manifest.json> (what dbt wrote) or --sql <dir|file> (the ETL's SQL)")
    if not at or not re.match(r"^\d{4}-\d{2}-\d{2}$", str(at)):
        raise LineageError("--at YYYY-MM-DD is required: the date the lineage was read is never defaulted")
    if not store_id or not str(store_id).startswith("datastore."):
        raise LineageError("--store datastore.<id> names the DataStore the loaded tables are part of")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if JOB not in classes or FEED not in classes:
        raise LineageError("the vocabulary declares no LoadJob and Feed: the data ontology does (oto init --ontology data, or compose it)")
    if dbt:
        if not os.path.isfile(dbt):
            raise LineageError("no such manifest: %s" % dbt)
        with open(dbt, encoding="utf-8") as f:
            try:
                manifest = json.load(f)
            except ValueError as exc:
                raise LineageError("%s is not JSON: %s" % (dbt, exc))
        read = read_dbt(manifest)
    else:
        read = read_sql(sql, tool=tool)
    graph_ids = _graph_ids(project)
    if store_id not in graph_ids:
        raise LineageError("the graph holds no %s. The data layer describes a store the estate declares: record the DataStore "
                           "(and the environment it runs in) first, then introspect it, then read its lineage" % store_id)
    store = store_slug(store_id)
    doc = "lineage-%s-%s" % (store, read["reader"])
    title, text = document(read, store, at)
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    proposal, gaps = propose(read, store_id, doc, at, graph_ids)
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
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "store": store_id, "reader": read["reader"],
            "about": read["about"], "jobs": sum(1 for n in proposal["nodes"] if n["type"] == JOB),
            "feeds": sum(1 for n in proposal["nodes"] if n["type"] == FEED), "gaps": gaps}
