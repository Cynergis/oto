# -*- coding: utf-8 -*-
"""The BigQuery overlay: a dataset read in place, never copied (roadmap K8, C1).

The catalog comes from the dataset's INFORMATION_SCHEMA (TABLES, COLUMNS, and the primary and
foreign key constraints BigQuery declares without enforcing); the query log from the region's
INFORMATION_SCHEMA.JOBS_BY_PROJECT, the jobs that referenced the dataset, with the user that ran each; a native read is dry-run
first, so a statement the words let through but BigQuery would execute as anything other than a
SELECT is refused before it runs, then run with a cap on the bytes billed. The client is
google-cloud-bigquery (Apache-2.0), installed by the `bigquery` extra, with Application Default
Credentials; a client object may be handed in (`settings["client"]`), which is how the tests replay a
recorded catalog without a project.
"""
import os
import types

from . import Connector, select_only
from ..project import ProjectError

MANIFEST = {
    "name": "bigquery", "version": "0.1.0", "modes": ["overlay"], "query_language": "sql",
    "capabilities": {"named_graphs": False, "schema_constraints": True, "transactions": False, "vector_index": True,
                     "full_text": True},
    "auth": ["adc", "service-account"], "conformance": "kit@1",
}
PROJECT_ENV, DATASET_ENV = "OTO_BIGQUERY_PROJECT", "OTO_BIGQUERY_DATASET"
DEFAULT_REGION = "us"
DEFAULT_MAX_BYTES = 1 << 30
LOG_LIMIT = 500
LOG_FIELDS = ("creation_time", "user_email", "query", "total_bytes_processed", "statement_type")


def connector():
    return BigQueryConnector()


def available():
    try:
        from google.cloud import bigquery  # noqa: F401
        return True
    except ImportError:
        return False


def _job_config(dry_run, max_bytes):
    try:
        from google.cloud import bigquery
        return bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=not dry_run, maximum_bytes_billed=max_bytes)
    except ImportError:
        return types.SimpleNamespace(dry_run=dry_run, maximum_bytes_billed=max_bytes)


class BigQueryConnector(Connector):
    name = "bigquery"
    MANIFEST = MANIFEST

    # ---- sessions ----
    def settings(self, project):
        cfg = project.config().get("bigquery") or {}
        project_id = os.environ.get(PROJECT_ENV) or cfg.get("project")
        dataset = os.environ.get(DATASET_ENV) or cfg.get("dataset")
        if not (project_id and dataset):
            raise ProjectError("bigquery overlay: set %s and %s, or `bigquery.project` and `bigquery.dataset` in project.config.json; "
                               "credentials come from Application Default Credentials" % (PROJECT_ENV, DATASET_ENV))
        return {"project": project_id, "dataset": dataset, "region": cfg.get("region") or DEFAULT_REGION,
                "max_bytes": int(cfg.get("max_bytes") or DEFAULT_MAX_BYTES)}

    def from_deploy(self, project, overlay):
        """Settings from the deploy config's `overlay` section: the endpoint is the GCP project, the
        dataset is `connection.database` or `overlay.schema`."""
        connection = overlay.get("connection") or {}
        project_id = connection.get("endpoint") or os.environ.get(PROJECT_ENV)
        dataset = connection.get("database") or overlay.get("schema") or os.environ.get(DATASET_ENV)
        if not (project_id and dataset):
            raise ProjectError("the deploy config's overlay names no BigQuery project (endpoint) and dataset (database or schema)")
        return {"project": project_id, "dataset": dataset, "region": overlay.get("region") or DEFAULT_REGION, "max_bytes": DEFAULT_MAX_BYTES}

    def connect(self, settings):
        client = settings.get("client")
        if client is None:
            if not available():
                raise ProjectError("the bigquery overlay needs its client: pip install \"oto-kg[bigquery]\"")
            from google.cloud import bigquery
            client = bigquery.Client(project=settings["project"])
        return {"client": client, "project": settings["project"], "dataset": settings["dataset"],
                "region": settings.get("region") or DEFAULT_REGION, "max_bytes": int(settings.get("max_bytes") or DEFAULT_MAX_BYTES)}

    def close(self, session):
        close = getattr(session.get("client"), "close", None)
        if callable(close):
            try:
                close()
            except Exception:                               # noqa: BLE001 - closing is best effort
                pass

    # ---- overlay ----
    def _prefix(self, session):
        return "`%s.%s.INFORMATION_SCHEMA." % (session["project"], session["dataset"])

    def _run(self, session, sql, dry_run=False):
        return session["client"].query(sql, job_config=_job_config(dry_run, session["max_bytes"]))

    def _rows(self, session, sql, max_results=None):
        result = self._run(session, sql).result(max_results=max_results)
        return [d.name for d in result.schema], [list(r.values()) for r in result]

    def introspect(self, session):
        p = self._prefix(session)
        _c, tables = self._rows(session, "SELECT table_name, table_type FROM %sTABLES` ORDER BY table_name" % p)
        _c, columns = self._rows(session, "SELECT table_name, column_name, data_type, is_nullable, ordinal_position FROM %sCOLUMNS` "
                                          "ORDER BY table_name, ordinal_position" % p)
        _c, keys = self._rows(session, "SELECT kcu.table_name, kcu.column_name, tc.constraint_type, ccu.table_name AS ref_table, "
                                       "ccu.column_name AS ref_column FROM %sTABLE_CONSTRAINTS` tc "
                                       "JOIN %sKEY_COLUMN_USAGE` kcu ON kcu.constraint_name = tc.constraint_name "
                                       "LEFT JOIN %sCONSTRAINT_COLUMN_USAGE` ccu ON ccu.constraint_name = tc.constraint_name "
                                       "AND tc.constraint_type = 'FOREIGN KEY' "
                                       "WHERE tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY') ORDER BY 1, 2" % (p, p, p))
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
        return {"store": session["dataset"], "tables": out}

    def query_log(self, session, since=None):
        sql = ("SELECT %s FROM `region-%s`.INFORMATION_SCHEMA.JOBS_BY_PROJECT "
               "WHERE job_type = 'QUERY' AND state = 'DONE' AND EXISTS (SELECT 1 FROM UNNEST(referenced_tables) t WHERE t.dataset_id = '%s') "
               "ORDER BY creation_time DESC LIMIT %d" % (", ".join(LOG_FIELDS), session["region"], session["dataset"].replace("'", ""), LOG_LIMIT))
        _c, rows = self._rows(session, sql)
        out = []
        for at, by, query, total_bytes, kind in rows:
            out.append({"at": at.isoformat() if hasattr(at, "isoformat") else str(at), "by": by, "sql": query, "bytes": total_bytes, "kind": kind})
        return out

    def native_read(self, session, sql, limit=100):
        text = select_only(sql)
        try:
            dry = self._run(session, text, dry_run=True)
            kind = getattr(dry, "statement_type", None)
        except Exception as exc:                            # noqa: BLE001 - the store's refusal, in words
            raise ValueError("read-only query refused by the store: %s" % exc)
        if kind != "SELECT":
            raise ValueError("read-only: the dry run says the statement is %s, not a SELECT; it was not run" % (kind or "unknown"))
        try:
            columns, rows = self._rows(session, text, max_results=limit + 1)
        except Exception as exc:                            # noqa: BLE001
            raise ValueError("read-only query refused by the store: %s" % exc)
        return {"columns": columns, "rows": rows[:limit], "truncated": len(rows) > limit}
