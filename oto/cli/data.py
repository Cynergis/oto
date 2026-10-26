# -*- coding: utf-8 -*-
"""`oto data`: the data semantic layer. introspect reads a store's catalog through an overlay
connector into a schema document and a proposal in the data vocabulary (roadmap C1)."""
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
    print("oto: unknown data command %r" % args.data_command, file=sys.stderr)
    return 1


def register(sub):
    data = sub.add_parser("data", help="the data semantic layer: a store's schema, lineage, usage and meaning as facts")
    data.add_argument("data_command", choices=["introspect"],
                      help="introspect reads a store's catalog through an overlay connector into a schema document and a proposal")
    data.add_argument("--connector", default="sqlite", help="the overlay connector: sqlite (default), postgres or bigquery")
    data.add_argument("--path", default=None, help="for sqlite: the file to read (default: this project's own built store); postgres and bigquery read their connection from project.config.json or the environment")
    data.add_argument("--store", default=None, help="the DataStore node the tables are part of, datastore.<id> (default: datastore.<store name>); proposed when the graph lacks it")
    data.add_argument("--at", default=None, help="the date the catalog was read, YYYY-MM-DD; never defaulted")
    project_arguments(data)
    data.set_defaults(func=cmd_data)
