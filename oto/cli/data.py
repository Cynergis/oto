# -*- coding: utf-8 -*-
"""`oto data`: the data semantic layer. introspect reads a store's catalog through an overlay
connector into a schema document and a proposal in the data vocabulary (roadmap C1); lineage reads
a dbt manifest or the ETL's SQL into a lineage document and a proposal of jobs and feeds (C3)."""
import os
import sys

from ._common import project_arguments, resolve as _resolve


def cmd_data(args):
    from .. import data as _data
    project = _resolve(args)
    if args.data_command == "introspect":
        try:
            done = _data.introspect(project, connector_name=args.connector, path=args.path, store_id=args.store, at=args.at)
        except _data.DataError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %d table(s), %d column(s) read through the %s overlay" % (done["store"], done["tables"], done["columns"], args.connector))
        print("  schema document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal        %s" % rel(done["proposal"]))
        print("  meaning is not the catalog's to say: every table and column is a draft until a person confirms it")
        print("  next: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\""
              % rel(done["proposal"]))
        return 0
    if args.data_command == "lineage":
        from .. import lineage as _lineage
        try:
            done = _lineage.lineage(project, dbt=args.dbt, sql=args.sql, store_id=args.store, at=args.at, tool=args.tool)
        except _data.DataError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        rel = lambda p: os.path.relpath(p, project.data)  # noqa: E731
        print("%s: %d job(s), %d feed(s) read from %s" % (done["store"], done["jobs"], done["feeds"], done["about"]))
        print("  lineage document %s (kept in %s)" % (rel(done["document"]), rel(done["archive"])))
        print("  proposal         %s" % rel(done["proposal"]))
        if done["gaps"]:
            print("  gaps, not proposed (the catalog says what tables exist: introspect the store first, or declare the feed):")
            for gap in done["gaps"]:
                print("    %s" % gap)
        print("  next: oto curate start (if no candidate is open), oto curate add --from %s, oto curate check, oto curate apply --by <you> --note \"...\""
              % rel(done["proposal"]))
        return 0
    print("oto: unknown data command %r" % args.data_command, file=sys.stderr)
    return 1


def register(sub):
    data = sub.add_parser("data", help="the data semantic layer: a store's schema, lineage, usage and meaning as facts")
    data.add_argument("data_command", choices=["introspect", "lineage"],
                      help="introspect reads a store's catalog through an overlay connector into a schema document and a proposal; "
                           "lineage reads a dbt manifest (--dbt) or SQL files (--sql) into a lineage document and a proposal of jobs and feeds")
    data.add_argument("--connector", default="sqlite", help="the overlay connector: sqlite (default), postgres or bigquery")
    data.add_argument("--path", default=None, help="for sqlite: the file to read (default: this project's own built store); postgres and bigquery read their connection from project.config.json or the environment")
    data.add_argument("--store", default=None, help="the DataStore node the tables are part of, datastore.<id> (default for introspect: datastore.<store name>); the graph must hold it")
    data.add_argument("--at", default=None, help="the date the catalog or lineage was read, YYYY-MM-DD; never defaulted")
    data.add_argument("--dbt", default=None, help="for lineage: the dbt manifest (target/manifest.json)")
    data.add_argument("--sql", default=None, help="for lineage: a .sql file or a directory of them, one job per file")
    data.add_argument("--tool", default=None, help="for lineage --sql: what runs the files when no `-- tool:` comment says (default: sql)")
    project_arguments(data)
    data.set_defaults(func=cmd_data)
