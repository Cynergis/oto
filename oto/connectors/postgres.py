# -*- coding: utf-8 -*-
"""The Postgres overlay: a Postgres schema read in place, never copied (roadmap K8, C1).

The catalog comes from information_schema (tables and views, columns with type and nullability, the
primary and foreign keys with the column a foreign key references); the query log from
pg_stat_statements when the extension is installed, with the role that ran each statement, else nothing; a native read runs one SELECT
inside `START TRANSACTION READ ONLY` and rolls back, so the store itself refuses a write the words
let through. The driver is pg8000 (BSD-3-Clause, pure Python), installed by the `postgres` extra;
the connection is a DSN (`postgresql://user@host:5432/db`) with the password from `PGPASSWORD` or
the variable the deploy config names, never from a file. A connection object may be handed in
(`settings["connection"]`), which is how the tests replay a recorded catalog without a server.
"""
import os
import urllib.parse

from . import Connector, select_only
from ..project import ProjectError

MANIFEST = {
    "name": "postgres", "version": "0.1.0", "modes": ["overlay"], "query_language": "sql",
    "capabilities": {"named_graphs": False, "schema_constraints": True, "transactions": True, "vector_index": False,
                     "full_text": True},
    "auth": ["basic", "env"], "conformance": "kit@1",
}
DSN_ENV, PASSWORD_ENV = "OTO_POSTGRES_DSN", "PGPASSWORD"
LOG_LIMIT = 500

TABLES_SQL = "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name"
COLUMNS_SQL = ("SELECT table_name, column_name, data_type, is_nullable, ordinal_position FROM information_schema.columns "
               "WHERE table_schema = %s ORDER BY table_name, ordinal_position")
KEYS_SQL = ("SELECT tc.table_name, kcu.column_name, tc.constraint_type, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name AND kcu.constraint_schema = tc.constraint_schema "
            "LEFT JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
            "AND ccu.constraint_schema = tc.constraint_schema AND tc.constraint_type = 'FOREIGN KEY' "
            "WHERE tc.table_schema = %s AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY') ORDER BY 1, 2")
EXTENSION_SQL = "SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'"
LOG_SQL = ("SELECT r.rolname, s.query, s.calls, s.total_exec_time FROM pg_stat_statements s LEFT JOIN pg_roles r ON r.oid = s.userid "
           "ORDER BY s.total_exec_time DESC LIMIT %s")


def connector():
    return PostgresConnector()


def available():
    try:
        import pg8000  # noqa: F401
        return True
    except ImportError:
        return False


def parse_dsn(dsn):
    """postgresql://user:password@host:port/database?sslmode=require -> its parts. The password
    belongs in the environment; parsing it here is for the DSN a person typed at a prompt."""
    parts = urllib.parse.urlsplit(dsn)
    query = dict(urllib.parse.parse_qsl(parts.query))
    return {"user": parts.username, "password": parts.password, "host": parts.hostname or "localhost", "port": parts.port or 5432,
            "database": (parts.path or "").lstrip("/") or None, "ssl": query.get("sslmode") in ("require", "verify-ca", "verify-full")}


class PostgresConnector(Connector):
    name = "postgres"
    MANIFEST = MANIFEST
    parse_dsn = staticmethod(parse_dsn)

    # ---- sessions ----
    def settings(self, project):
        cfg = project.config().get("postgres") or {}
        dsn = os.environ.get(DSN_ENV) or cfg.get("dsn")
        if not dsn:
            raise ProjectError("postgres overlay: set %s (postgresql://user@host:5432/db, the password in %s) or `postgres.dsn` in project.config.json"
                               % (DSN_ENV, PASSWORD_ENV))
        schema = cfg.get("schema") or "public"
        return {"dsn": dsn, "schema": schema, "name": cfg.get("name") or parse_dsn(dsn)["database"] or schema}

    def from_deploy(self, project, overlay):
        """Settings from the deploy config's `overlay` section: the endpoint is the DSN, the secret
        names the variable holding the password."""
        connection = overlay.get("connection") or {}
        dsn = connection.get("endpoint") or os.environ.get(DSN_ENV)
        if not dsn:
            raise ProjectError("the deploy config's overlay names no endpoint: a Postgres DSN")
        password = os.environ.get(connection["secret"]) if connection.get("secret") else None
        schema = overlay.get("schema") or "public"
        return {"dsn": dsn, "schema": schema, "name": parse_dsn(dsn)["database"] or schema, "password": password}

    def connect(self, settings):
        if settings.get("connection") is not None:
            return {"con": settings["connection"], "schema": settings.get("schema") or "public", "name": settings.get("name") or "postgres"}
        if not available():
            raise ProjectError("the postgres overlay needs its driver: pip install \"oto-kg[postgres]\"")
        import pg8000.dbapi
        parts = parse_dsn(settings["dsn"])
        password = settings.get("password") or parts["password"] or os.environ.get(PASSWORD_ENV)
        con = pg8000.dbapi.connect(user=parts["user"] or "postgres", password=password, host=parts["host"], port=parts["port"],
                                   database=parts["database"], ssl_context=True if parts["ssl"] else None)
        return {"con": con, "schema": settings.get("schema") or "public", "name": settings.get("name") or parts["database"] or "postgres"}

    def close(self, session):
        try:
            session["con"].close()
        except Exception:                                   # noqa: BLE001 - closing is best effort
            pass

    # ---- overlay ----
    def _rows(self, session, sql, params=()):
        cur = session["con"].cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def introspect(self, session):
        schema = session["schema"]
        tables = self._rows(session, TABLES_SQL, (schema,))
        columns = self._rows(session, COLUMNS_SQL, (schema,))
        keys = self._rows(session, KEYS_SQL, (schema,))
        primary, foreign = set(), {}
        for table, column, kind, ref_table, ref_column in keys:
            if kind == "PRIMARY KEY":
                primary.add((table, column))
            elif ref_table and ref_column:
                foreign[(table, column)] = "%s.%s" % (ref_table, ref_column)
        by_table = {}
        for table, column, data_type, nullable, _position in columns:
            pk = (table, column) in primary
            key = "primary" if pk else ("foreign" if (table, column) in foreign else None)
            by_table.setdefault(table, []).append({"name": column, "type": (data_type or "").strip() or "unknown",
                                                   "nullable": (nullable == "YES") and not pk, "key": key, "references": foreign.get((table, column))})
        out = []
        for name, kind in sorted(tables, key=lambda r: r[0]):
            out.append({"name": name, "kind": "view" if "VIEW" in (kind or "").upper() else "table", "columns": by_table.get(name, [])})
        return {"store": session["name"], "tables": out}

    def query_log(self, session, since=None):
        if not self._rows(session, EXTENSION_SQL):
            return []
        return [{"by": by, "sql": sql, "calls": calls, "total_ms": total} for by, sql, calls, total in self._rows(session, LOG_SQL, (LOG_LIMIT,))]

    def native_read(self, session, sql, limit=100):
        text = select_only(sql)
        con = session["con"]
        cur = con.cursor()
        try:
            try:
                cur.execute("START TRANSACTION READ ONLY")
                cur.execute(text)
                rows = cur.fetchmany(limit + 1)
                columns = [d[0] for d in cur.description or []]
            except Exception as exc:                        # noqa: BLE001 - the store's refusal, in words
                con.rollback()
                raise ValueError("read-only query refused by the store: %s" % exc)
            con.rollback()
        finally:
            cur.close()
        return {"columns": columns, "rows": [list(r) for r in rows[:limit]], "truncated": len(rows) > limit}
