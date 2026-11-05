# -*- coding: utf-8 -*-
"""An optional stage, beside Neo4j. Load the built store into a BigQuery dataset, and read it back into memory.

Runs only when the project config names the target:

    "targets": ["sqlite", "bigquery"],
    "bigquery": {"project": "<a Google Cloud project>", "dataset": "<a dataset of its own for this graph>"}

`OTO_BIGQUERY_PROJECT` and `OTO_BIGQUERY_DATASET` override both names, and credentials come from Application
Default Credentials. The client lives in the `bigquery` extra, so the base install stays dependency-free.
A dataset holds one graph: BigQuery grants access per dataset, so a dataset is an access boundary.

What a load writes. Each table of the built store (targets/sqlite.py) becomes `<table>__b<n>`, in one load job, with
`oto_row` keeping its order, since a listing promises none. A load job is free. One row appended to `oto_builds` then
says that build is finished: that single job is the commit, so a load that stops midway leaves the last build the
one a reader sees. A view under each plain name lets people query the graph (`SELECT * FROM kg.nodes`). The two
newest builds are kept, so a reader part way through its copy can finish it, and older tables are dropped.

What a server reads. It lists the newest finished build's tables into an in-memory SQLite, built from the schema that
build recorded, so it answers exactly as the build does: same rows, same order, same full-text search
(docs/adr/0015-bigquery-holds-the-graph.md). Listing a table runs no query job: it bills nothing and needs only
`roles/bigquery.dataViewer` on the dataset.
"""
import datetime
import hashlib
import json
import os
import re
import sqlite3
import types

from ..project import ProjectError
from . import sqlite as _sqlite

PROJECT_ENV, DATASET_ENV = "OTO_BIGQUERY_PROJECT", "OTO_BIGQUERY_DATASET"
INSTALL = "pip install \"oto-kg[bigquery] @ git+<the engine repository>\""
BUILDS = "oto_builds"
ROW = "oto_row"
KEEP = 2                 # builds kept: the one served, and the one a reader may still be copying
ATTEMPTS = 3             # how many times a reader starts its copy again when a newer load retires what it reads
#: the store's full-text tables: SQLite keeps each one's index in tables of its own, named after it, which aren't data
FTS = ("node_fts", "docs_fts")
#: a full-text table holding what another table holds is filled from that one, rather than loaded twice
MIRRORS = {"docs_fts": ("docs", "path, title, body")}
TYPES = {"INTEGER": "INT64", "REAL": "FLOAT64"}
BUILDS_SCHEMA = (("seq", "INT64"), ("build_seq", "STRING"), ("schema_version", "INT64"), ("at", "STRING"), ("engine", "STRING"),
                 ("hash", "STRING"), ("tables", "STRING"), ("schema_sql", "STRING"))
BUILT_TABLE = re.compile(r"^(.+)__b(\d+)$")


def available():
    try:
        from google.cloud import bigquery  # noqa: F401
        return True
    except ImportError:
        return False


def connection(section=None):
    """The project and dataset: the environment, then the project config's `bigquery` section."""
    section = section or {}
    return {"project": os.environ.get(PROJECT_ENV) or section.get("project"), "dataset": os.environ.get(DATASET_ENV) or section.get("dataset")}


def configured(project):
    cfg = project.config()
    targets = cfg.get("targets") or ["sqlite"]
    forced = "bigquery" in (getattr(project, "options", {}) or {}).get("targets", set())
    conf = connection(cfg.get("bigquery"))
    return ("bigquery" in targets or forced) and bool(conf["project"] and conf["dataset"])


def open_client(settings):
    """A client for these settings: the one handed in, or a real one on Application Default Credentials."""
    client = settings.get("client")
    if client is not None:
        return client
    if not available():
        raise ProjectError("BigQuery needs its client: %s" % INSTALL)
    from google.cloud import bigquery
    return bigquery.Client(project=settings["project"])


def _missing(exc):
    """Whether this is BigQuery saying a table or dataset isn't there."""
    return getattr(exc, "code", None) == 404 or type(exc).__name__ == "NotFound"


def _full(project, dataset, table):
    return "%s.%s.%s" % (project, dataset, table)


# ---- the rows ----

def _value(value, kind):
    if value is None:
        return None
    return str(value) if kind == "STRING" else value


def materialize(plan):
    """The plan as the store a build makes, in memory: the one place that decides what a row holds."""
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.executescript(_sqlite.SCHEMA_SQL)
    _sqlite.write(con, plan)
    con.commit()
    return con


def tables_of(con):
    """{table: {"columns": [[name, BigQuery type]], "rows": [[value]]}}, each table in its own order."""
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    index_tables = tuple(name + "_" for name in FTS)
    out = {}
    for name in names:
        if name in MIRRORS or name.startswith(index_tables):
            continue
        columns = [[c[1], TYPES.get((c[2] or "").upper(), "STRING")] for c in con.execute('PRAGMA table_info("%s")' % name)]
        kinds = [c[1] for c in columns]
        rows = [[_value(v, k) for v, k in zip(r, kinds)] for r in con.execute('SELECT * FROM "%s" ORDER BY rowid' % name)]
        out[name] = {"columns": columns, "rows": rows}
    return out


def fingerprint(tables):
    """What a build holds, as one hash: the same rows in the same order give the same hash."""
    return hashlib.sha256(json.dumps(tables, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ---- BigQuery's objects, real when the client is installed ----

def _fields(columns):
    try:
        from google.cloud import bigquery
        return [bigquery.SchemaField(name, kind) for name, kind in columns]
    except ImportError:
        return [types.SimpleNamespace(name=name, field_type=kind) for name, kind in columns]


def _load_config(columns, append=False):
    disposition = "WRITE_APPEND" if append else "WRITE_TRUNCATE"
    try:
        from google.cloud import bigquery
        return bigquery.LoadJobConfig(schema=_fields(columns), write_disposition=disposition, source_format="NEWLINE_DELIMITED_JSON")
    except ImportError:
        return types.SimpleNamespace(schema=_fields(columns), write_disposition=disposition, source_format="NEWLINE_DELIMITED_JSON")


def _table(project, dataset, name, columns):
    try:
        from google.cloud import bigquery
        return bigquery.Table(_full(project, dataset, name), schema=_fields(columns))
    except ImportError:
        return types.SimpleNamespace(project=project, dataset_id=dataset, table_id=name, schema=_fields(columns))


def _dataset(project, dataset, location):
    try:
        from google.cloud import bigquery
        made = bigquery.Dataset("%s.%s" % (project, dataset))
        made.location = location
        return made
    except ImportError:
        return types.SimpleNamespace(project=project, dataset_id=dataset, location=location)


# ---- a load ----

def builds(client, project, dataset):
    """Every finished load, oldest first. None of them yet is an empty list."""
    try:
        rows = [dict(r.items()) for r in client.list_rows(_full(project, dataset, BUILDS))]
    except Exception as exc:                                       # noqa: BLE001 - the client's own hierarchy
        if _missing(exc):
            return []
        raise
    return sorted(rows, key=lambda r: int(r["seq"]))


def latest(client, project, dataset):
    """The newest finished load's record, or None."""
    found = builds(client, project, dataset)
    return found[-1] if found else None


def prepare(client, project, dataset):
    """The table that records finished loads. It says plainly when the dataset itself isn't there."""
    try:
        client.create_table(_table(project, dataset, BUILDS, BUILDS_SCHEMA), exists_ok=True)
    except Exception as exc:                                       # noqa: BLE001
        if _missing(exc):
            raise ProjectError("BigQuery has no dataset %s.%s: make it first, in the region you want the graph in: "
                               "bq mk --dataset --location=<region> %s:%s" % (project, dataset, project, dataset))
        raise


def _load_table(client, project, dataset, name, table):
    full = _full(project, dataset, name)
    columns = table["columns"] + [[ROW, "INT64"]]
    if not table["rows"]:                                          # over whatever a stopped load left
        client.delete_table(full, not_found_ok=True)
        client.create_table(_table(project, dataset, name, columns))
        return
    names = [c[0] for c in table["columns"]]
    rows = [dict(zip(names, row), **{ROW: i}) for i, row in enumerate(table["rows"])]
    client.load_table_from_json(rows, full, job_config=_load_config(columns)).result()


def _point_views(client, project, dataset, seq, names):
    for name in names:
        client.query("CREATE OR REPLACE VIEW `%s` AS SELECT * EXCEPT(%s) FROM `%s`"
                     % (_full(project, dataset, name), ROW, _full(project, dataset, "%s__b%d" % (name, seq)))).result()


def _retire(client, project, dataset, kept):
    for item in client.list_tables("%s.%s" % (project, dataset)):
        found = BUILT_TABLE.match(item.table_id)
        if found and int(found.group(2)) not in kept:
            client.delete_table(_full(project, dataset, item.table_id), not_found_ok=True)


def load(client, project, dataset, plan):
    """The plan into the dataset, finished by one row in `oto_builds`. Returns {seq, unchanged, hash, tables: {name: rows}}.
    The same build again loads nothing, and still puts the views right, so a rerun mends a load that stopped after its commit."""
    from .. import __version__
    con = materialize(plan)
    try:
        tables = tables_of(con)
    finally:
        con.close()
    digest = fingerprint(tables)
    prepare(client, project, dataset)
    found = builds(client, project, dataset)
    last = found[-1] if found else None
    unchanged = bool(last) and last["hash"] == digest
    seq = int(last["seq"]) if unchanged else (int(last["seq"]) + 1 if last else 1)
    counts = {name: len(table["rows"]) for name, table in tables.items()}
    if not unchanged:
        for name, table in tables.items():
            _load_table(client, project, dataset, "%s__b%d" % (name, seq), table)
        meta = dict(r for r in tables["meta"]["rows"]) if "meta" in tables else {}
        record = {"seq": seq, "build_seq": meta.get("build_seq"), "schema_version": _sqlite.SCHEMA_VERSION,
                  "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "engine": __version__,
                  "hash": digest, "tables": json.dumps(counts, sort_keys=True), "schema_sql": _sqlite.SCHEMA_SQL}
        client.load_table_from_json([record], _full(project, dataset, BUILDS), job_config=_load_config(BUILDS_SCHEMA, append=True)).result()
        found = found + [record]
    _point_views(client, project, dataset, seq, sorted(tables))
    _retire(client, project, dataset, {int(r["seq"]) for r in found[-KEEP:]})
    return {"seq": seq, "unchanged": unchanged, "hash": digest, "tables": counts}


# ---- a reader's copy ----

class _Moved(Exception):
    """What a reader was copying is gone or partial: a newer load has moved on."""


def _copy_table(client, project, dataset, con, name, seq, expected):
    full = _full(project, dataset, "%s__b%d" % (name, seq))
    try:
        rows = [dict(r.items()) for r in client.list_rows(full)]
    except Exception as exc:                                       # noqa: BLE001 - the client's own hierarchy
        if _missing(exc):
            raise _Moved("%s is gone" % full)
        raise
    if len(rows) != expected:
        raise _Moved("%s holds %d rows, and its build says %d" % (full, len(rows), expected))
    if not rows:
        return
    rows.sort(key=lambda r: r[ROW])
    columns = [c for c in rows[0] if c != ROW]
    statement = 'INSERT INTO "%s" (%s) VALUES (%s)' % (name, ", ".join('"%s"' % c for c in columns), ", ".join("?" for _c in columns))
    con.executemany(statement, ([r[c] for c in columns] for r in rows))


def _copy(client, project, dataset, record):
    con = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        con.executescript(record["schema_sql"])
        seq = int(record["seq"])
        for name, expected in sorted(json.loads(record["tables"]).items()):
            _copy_table(client, project, dataset, con, name, seq, int(expected))
        for mirror, (source, columns) in MIRRORS.items():
            con.execute('INSERT INTO "%s" (%s) SELECT %s FROM "%s" ORDER BY rowid' % (mirror, columns, columns, source))
        con.commit()
    except Exception:
        con.close()
        raise
    return con


def read(client, project, dataset):
    """The newest finished load, copied into memory: (connection, its record), or (None, None) with nothing loaded yet."""
    problem = None
    for _attempt in range(ATTEMPTS):
        record = latest(client, project, dataset)
        if record is None:
            return None, None
        try:
            return _copy(client, project, dataset, record), record
        except _Moved as exc:
            problem = exc
    raise ProjectError("BigQuery %s.%s kept changing while it was being read: %s. Try again; if it keeps happening, its tables were changed by hand: "
                       "run `oto build --target bigquery`" % (project, dataset, problem))


def differences(client, project, dataset, plan):
    """What differs between the newest finished load and this plan, row by row; [] when nothing does."""
    try:
        con, _record = read(client, project, dataset)
    except ProjectError as exc:
        return [str(exc)]
    if con is None:
        return ["BigQuery %s.%s holds no load" % (project, dataset)]
    wanted = materialize(plan)
    try:
        got, want = tables_of(con), tables_of(wanted)
    finally:
        con.close()
        wanted.close()
    out = []
    for name in sorted(set(want) | set(got)):
        if name not in got or name not in want:
            out.append("table %s: %s" % (name, "missing" if name not in got else "not in the build"))
        elif len(got[name]["rows"]) != len(want[name]["rows"]):
            out.append("table %s: planned %d rows, found %d" % (name, len(want[name]["rows"]), len(got[name]["rows"])))
        elif got[name] != want[name]:
            at = next((i for i, (a, b) in enumerate(zip(got[name]["rows"], want[name]["rows"])) if a != b), None)
            out.append("table %s: differs at row %s" % (name, at))
    return out


def run(project):
    """The build stage: through the connector (connectors/bigquery.py), like every store."""
    from ..connectors import get as _connector
    _connector("bigquery").stage(project)
