# -*- coding: utf-8 -*-
"""`oto status`: where a project is in its life, and the next step."""
import json
import os

from ._common import project_arguments, resolve as _resolve


def _count_files(directory, suffix=None):
    if not os.path.isdir(directory):
        return 0
    return sum(1 for n in os.listdir(directory)
               if os.path.isfile(os.path.join(directory, n)) and not n.startswith(".")
               and (suffix is None or n.endswith(suffix)))


def _newest(paths):
    stamps = [os.path.getmtime(p) for p in paths if p and os.path.exists(p)]
    return max(stamps) if stamps else 0


def gather(project):
    """Every fact `oto status` prints, as a dict. Deterministic apart from file timestamps."""
    from ..curate import assertions as _assertions, reattest as _reattest, session as _session
    from ..intake import pipeline as _pipeline
    from ..model import rationale as _rationale

    layout = project.layout
    root = os.path.dirname(project.src)
    identity = project.identity()

    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    with open(project.graph_path, encoding="utf-8") as f:
        graph = json.load(f)
    classes = vocabulary.get("classes") or {}
    properties = vocabulary.get("properties") or {}

    rationale = None
    if os.path.exists(_rationale.path_for(project)):
        coverage = _rationale.report(vocabulary, _rationale.load(project))
        rationale = {"classes_with_rationale": coverage["classes_with_rationale"],
                     "classes_validated": len(coverage["classes_validated"]),
                     "problems": len(coverage["problems"])}

    corpus_files = [os.path.join(layout.corpus, n) for n in os.listdir(layout.corpus)] \
        if os.path.isdir(layout.corpus) else []
    inputs_changed = _newest([project.graph_path, project.ontology_config_path] + corpus_files)
    database = layout.database
    built = os.path.exists(database)

    status = {
        "name": identity["name"], "slug": identity["slug"], "root": root,
        "inbox": _count_files(layout.inbox),
        "processing": _count_files(layout.processing),
        "errors": sum(len([n for n in files if not n.endswith(_pipeline.ERROR_SUFFIX)])
                      for _d, _s, files in os.walk(layout.errors)) if os.path.isdir(layout.errors) else 0,
        "open_runs": [m["run_id"] for m in _pipeline.open_runs(project)],
        "corpus": _count_files(layout.corpus, ".md"),
        "notes": _count_files(layout.notes, ".md"),
        "classes": len(classes), "properties": len(properties),
        "attributes": sum(len(v or {}) for v in (vocabulary.get("attributes") or {}).values()),
        "vocabulary_accepted": os.path.exists(os.path.join(project.data, "ontology.lock.json")),
        "rationale": rationale,
        "nodes": len(graph.get("nodes") or []), "edges": len(graph.get("edges") or []),
        "candidate": _session.exists(project),
        "assertions": len(_assertions.read(project)),
        "reattest": len(_reattest.pending(project, graph)),
        "rules": len(__import__("oto.reason.rules", fromlist=["load"]).load(project)),
        "gold_set": os.path.exists(os.path.join(project.data, "gold", "questions.jsonl")),
        "built": built,
        "stale": built and os.path.getmtime(database) < inputs_changed,
    }
    status.update(_serving(project))
    status["ontology"] = _ontology(project)
    status["next"] = _next(status)
    return status


def _ontology(project):
    """What the project started from, and whether a newer version is known, from the local
    registry cache or the engine's shipped copy; never the network."""
    from ..model import registry as _registry
    record, legacy = _registry.project_record(project)
    if not record:
        return None
    out = {"name": record["name"], "release": record.get("release"), "origin": record.get("origin"),
           "registry": record.get("registry"), "available": None, "legacy_key": legacy,
           "pack": (record.get("pack") or {}).get("name"), "pack_release": (record.get("pack") or {}).get("release")}
    try:
        out["available"] = _registry.newer_release(record)
    except Exception:                                                 # noqa: BLE001 - advisory only
        out["available"] = None
    return out


def _serving(project):
    """Which store `oto serve` reads here, and for Neo4j whether it can be reached and holds a load.

    The check is one round trip with a short timeout, so `oto status` still answers when the
    database is down; that is exactly when the line matters.
    """
    cfg = project.config()
    backend = ((cfg.get("serve") or {}).get("backend") or "sqlite").lower()
    out = {"backend": backend, "neo4j": None}
    if backend != "neo4j":
        return out
    from ..targets import neo4j as _target
    conf = _target.connection(cfg.get("neo4j"))
    state = {"uri": conf["uri"], "database": conf["database"], "reachable": False, "loaded": False,
             "build_seq": None, "problem": None}
    out["neo4j"] = state
    if not _target.available():
        state["problem"] = "driver not installed (the neo4j extra)"
        return out
    if not conf["uri"]:
        state["problem"] = "no uri: set neo4j.uri or NEO4J_URI"
        return out
    auth = _target.credentials()
    if not auth:
        state["problem"] = "no credentials: set NEO4J_PASSWORD or NEO4J_AUTH"
        return out
    from ..serve.store import Neo4jStore
    try:
        store = Neo4jStore(conf["uri"], auth, conf["database"], project.identity()["slug"])
    except Exception as exc:                                          # noqa: BLE001
        state["problem"] = str(exc)
        return out
    try:
        store.ping()
        state["reachable"] = True
        state["build_seq"] = store.meta("build_seq")
        state["loaded"] = state["build_seq"] is not None
    except Exception as exc:                                          # noqa: BLE001
        state["problem"] = "unreachable: %s" % exc
    finally:
        store.close()
    return out


def _next(s):
    """One suggestion, in lifecycle order. The first unmet step is the next one."""
    if s["corpus"] == 0 and s["inbox"] > 0:
        return "oto ingest: %d file(s) wait in inbox/" % s["inbox"]
    if s["corpus"] == 0 and s["nodes"] == 0:
        return "put source documents in inbox/, then oto ingest"
    if s["classes"] == 0 or s["properties"] == 0:
        return "declare the vocabulary in ontology.config.json (the ontology-interview skill)"
    if s["nodes"] == 0:
        return "author the graph: oto curate start, then proposals via oto curate add (the build-knowledge-base skill)"
    if s["candidate"]:
        return "a candidate is open: oto curate check, then oto curate apply or abort"
    if not s["built"]:
        return "oto build"
    if s["stale"]:
        return "oto build: the inputs changed after the last build"
    neo = s.get("neo4j")
    if neo and not neo["reachable"]:
        return "the server reads Neo4j and cannot: %s (oto serve --backend sqlite serves the local build meanwhile)" % neo["problem"]
    if neo and not neo["loaded"]:
        return "oto build --target neo4j: the server reads Neo4j and it holds no load of this project"
    if s["open_runs"]:
        return "oto ingest complete: %d file(s) are in the graph but still in processing/ (run %s)" % (
            s["processing"], s["open_runs"][-1])
    if not s["vocabulary_accepted"]:
        return "oto ontology accept, so future vocabulary changes can be diffed"
    if not s["gold_set"]:
        return "serve it (oto serve), and start a gold set (oto bench start) to measure answers"
    return "up to date: oto serve, or oto query"


def _store_status(root):
    """A published query store checkout: how fresh it is and how to update it."""
    from .. import publish as _publish
    manifest = _publish.read_manifest(root)
    with open(os.path.join(root, _publish.CONFIG_NAME), encoding="utf-8") as f:
        cfg = json.load(f)
    print("%s (slug %s): a published query store, not a knowledge project" % (cfg.get("name"), cfg.get("slug")))
    print("  store       build_seq %s, published %s%s" % (manifest.get("build_seq", "?"), manifest.get("published_at", "?"),
                                                           (" from " + manifest["source"]) if manifest.get("source") else ""))
    print("  serve       sqlite, this checkout: oto serve --project %s" % root)
    print()
    print("next: oto sync --repo %s to update it" % (manifest.get("repo") or "<the query repository>"))
    return 0


def cmd_status(args):
    from .. import publish as _publish

    # A store checkout carries an identity config too, so it must be recognised before the
    # project constructor accepts it and grows a build/ directory inside it.
    root = os.path.abspath(args.project)
    if _publish.is_store(root):
        return _store_status(root)
    project = _resolve(args)
    s = gather(project)
    if args.json:
        print(json.dumps(s, indent=2, sort_keys=True))
        return 0
    print("%s (slug %s)" % (s["name"], s["slug"]))
    print("  sources     inbox %d, processing %d, errors %d, corpus %d document(s), notes %d"
          % (s["inbox"], s["processing"], s["errors"], s["corpus"], s["notes"]))
    if s["errors"]:
        print("              %d file(s) in errors/ need a person: read the .error.json beside each" % s["errors"])
    accepted = "accepted" if s["vocabulary_accepted"] else "not yet accepted"
    print("  vocabulary  %d class(es), %d relation(s), %d typed attribute(s), %d rule(s), %s"
          % (s["classes"], s["properties"], s["attributes"], s["rules"], accepted))
    if s.get("ontology"):
        t = s["ontology"]
        where = (" from %s" % t["registry"]) if t.get("registry") else (" (%s)" % t["origin"] if t.get("origin") else "")
        newer = ("; @%s available: oto ontology diff" % t["available"]) if t.get("available") else ""
        via = (" via pack %s @%s" % (t["pack"], t["pack_release"])) if t.get("pack") else ""
        print("  ontology    %s @%s%s%s%s" % (t["name"], t["release"], where, via, newer))
        if t.get("legacy_key"):
            print("              recorded under the old key `template` in project.config.json; rename it to "
                  "`ontology` and `version` inside it to `release`")
    if s["classes"] == 0 or s["properties"] == 0:
        print("              none declared yet. Four ways to get one, usually combined:")
        print("                1. from an ontology:       oto ontology import --from <name>[,<name>]   (oto ontology list)")
        print("                2. from the documents:     oto ingest, oto survey, then the ontology-interview skill")
        print("                3. from a file you own:    oto ontology import --file <vocabulary>.ttl|.csv|.json")
        print("                4. by interview:           the ontology-interview skill, questions before nouns")
        print("              whichever: oto ontology rationale --strict, then oto ontology accept")
    if s["rationale"]:
        r = s["rationale"]
        print("  rationale   %d of %d class(es) have a recorded reason, %d confirmed by a named person%s"
              % (r["classes_with_rationale"], s["classes"], r["classes_validated"],
                 (", %d problem(s)" % r["problems"]) if r["problems"] else ""))
    else:
        print("  rationale   none recorded")
    candidate = ", candidate OPEN" if s["candidate"] else ""
    if s["reattest"]:
        print("  re-attest   %d fact(s) cite a document that arrived as a new version and have not been "
              "checked against it (oto curate check lists them)" % s["reattest"])
    print("  graph       %d node(s), %d edge(s), %d assertion(s)%s" % (s["nodes"], s["edges"], s["assertions"], candidate))
    build = "not built" if not s["built"] else ("STALE, inputs changed since" if s["stale"] else "up to date")
    print("  build       %s" % build)
    if s["backend"] == "neo4j":
        neo = s["neo4j"]
        if neo["reachable"] and neo["loaded"]:
            state = "serving Neo4j %s (%s), build_seq %s" % (neo["uri"], neo["database"], neo["build_seq"])
        elif neo["reachable"]:
            state = "Neo4j %s reachable, NO load of this project yet" % neo["uri"]
        else:
            state = "Neo4j NOT serving: %s" % neo["problem"]
        print("  serve       %s" % state)
    else:
        print("  serve       sqlite, the local build (set serve.backend to neo4j for a shared live server)")
    print("  bench       %s" % ("gold set present" if s["gold_set"] else "no gold set"))
    print()
    print("next: %s" % s["next"])
    return 0


def register(sub):
    status = sub.add_parser("status", help="where the project is in its life, and the next step")
    project_arguments(status)
    status.add_argument("--json", action="store_true", help="machine-readable")
    status.set_defaults(func=cmd_status)
