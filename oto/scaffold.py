# -*- coding: utf-8 -*-
"""Create a new OTO project.

A project holds **data only**. The engine is an installed package, so nothing is copied here. That is
the difference from the tool this replaced, which copied its own scripts into every project and made
a fix something you had to re-copy everywhere.

Layout:

    <root>/
      project.config.json     identity: slug, name, namespace, database name
      ontology.config.json    YOUR domain vocabulary (classes + properties)
      graph.json              the curated graph — the source of truth
      lexicon.json            optional jargon and synonym map
      notes/                  AUTHORED narrative markdown
      inbox/                  drop raw documents here
      processing/             claimed by an ingest run; extracted, not yet in the graph
      errors/                 files a run could not extract, with the reason beside each
      archive/                the graph holds them; `oto ingest complete` moves them here
      runs/                   one manifest per ingest run
      build/                  GENERATED. `oto clean` deletes it whole.
        documents/            the corpus, extracted to Markdown
        entities/             one page per graph node
        ontology/             ontology.md, Turtle, JSON-LD
        cards/                retrieval cards
        graph/                graph JSON, CSV, N-Triples, search index
        <slug>.db
"""
import json
import os
import shutil

from . import __version__

# `notes/` is authored. Everything under `build/` is generated, so `oto clean` can delete it whole.
DIRS = ["inbox", "processing", "errors", "archive", "runs", "notes", "actions",
        "build/documents/assets", "build/entities", "build/ontology", "build/cards", "build/graph"]

# The temporal and provenance vocabulary is shared by every domain, so it is pre-filled.
TEMPORAL = {
    "asOf": {"type": "date", "definition": "When this fact was recorded or observed (transaction time)."},
    "validFrom": {"type": "date", "definition": "When the fact became true in the world (valid time)."},
    "validTo": {"type": "date", "definition": "When the fact stopped being true. Absent means it still holds."},
    "status": {"type": "string", "definition": "current | superseded | proposed | intended."},
    "supersedes": {"type": "ref", "definition": "The fact this one replaces."},
    "supersededBy": {"type": "ref", "definition": "The newer fact that retired this one."},
    "sourceDoc": {"type": "string", "definition": "Slug of the document that introduced or changed this fact."},
}

PROJECT_README = """# {name}

An OTO knowledge project. It holds **data only**. The engine is the installed `oto` package.

## Directories

| Path | What it holds |
|---|---|
| `project.config.json` | Identity. Every generated name derives from `slug`. |
| `ontology.config.json` | **Your domain vocabulary.** Declare classes and properties here. |
| `graph.json` | The curated graph. This is the source of truth. |
| `lexicon.json` | Optional. Maps jargon, acronyms and synonyms to entities, so a question in the reader's words resolves: `{{"entries": [{{"term": "PM", "aka": ["preventive maintenance"], "targets": ["procedure.pm"], "status": "current", "note": ""}}]}}`. |
| `ontology.lock.json` | The vocabulary as last accepted, so a change can be diffed. Commit it. |
| `assertions.jsonl` | Append-only record of things people said. Facts derived from one cite it. |
| `notes/` | **Authored** narrative markdown. Indexed alongside the generated pages. |
| `inbox/` | Drop raw documents here. |
| `processing/` | Claimed by an ingest run and extracted, but the graph does not hold their facts yet. Empty means nothing is owed. |
| `errors/<run>/` | Files a run could not extract, each with a `.error.json` saying why. Fix, then drop back in `inbox/`. |
| `archive/` | The graph holds them. Only `oto ingest complete` moves files here, after curate and build. |
| `runs/` | One manifest per ingest run: every file, its content hash, its outcome. |
| `build/` | Generated, and nothing else. `oto clean` deletes it whole and `oto build` recreates it. |

## First build

1. Drop source documents in `inbox/`.
2. Declare your domain vocabulary in `ontology.config.json`. Start small: the classes and
   relationships your questions actually need.
3. Author `graph.json`. Every node needs `as_of`, `valid_from`, `source_doc` and `status`.
4. Run `oto build`.

The build **fails** if the graph uses a class or relation you did not declare. That gate is
deliberate: it stops your model from drifting as the graph grows.

## Rules that keep answers correct

- **Never overwrite a contradicted fact.** Mark the old one `superseded` and add the new one. Queries
  return current facts by default, so answers stay right and stay auditable.
- **Cite every fact.** A node or edge without a source cannot be checked.
- **Keep this repository private** if the corpus is confidential. The built database grants full read
  access to whoever holds it.
"""

PROJECT_GITIGNORE = """# build/ is entirely generated. Track it only if you deliberately publish it.
build/
*.db.new
__pycache__/
"""


def slug_from(name):
    """A machine identifier from a human title: lowercase, words joined by hyphens."""
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    if not slug:
        raise ValueError("cannot derive a slug from %r; pass --slug" % name)
    return slug


def _write(path, payload, force, label):
    if os.path.exists(path) and not force:
        print("  kept (exists): %s" % label)
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if isinstance(payload, str):
            f.write(payload)
        else:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
    print("  wrote: %s" % label)
    return True


def _today():
    import datetime
    return datetime.date.today().isoformat()


def _ontology_record(name, ontologies, bases, pack=None):
    """What a project remembers about the ontology it started from, so a later `oto ontology
    diff` can say what the upstream ontology changed since. From a pack, the ontology's origin is
    what the pack recorded when it embedded it, and the pack itself is remembered."""
    if pack is not None:
        onto = pack["manifest"].get("ontology") or {}
        source = onto.get("source")
        where = ontologies.FETCHED if onto.get("registry") else \
            (ontologies.BUILTIN if source == "built-in" else (ontologies.USER if source == "user" else ontologies.PATH))
        return {"name": onto.get("name") or name, "release": onto.get("release"), "origin": where,
                "source": source or pack["directory"], "registry": onto.get("registry"), "ref": onto.get("ref"),
                "commit": onto.get("commit"), "installed_at": _today(), "extends": list(bases),
                "pack": {"name": pack["manifest"]["name"], "release": pack["manifest"]["release"],
                         "registry": pack["manifest"].get("registry"), "source": pack["manifest"].get("source")}}
    manifest = ontologies.manifest_for(name)
    where = ontologies.origin(name)
    if where == ontologies.FETCHED:
        source = manifest.get("source")
    elif where in (ontologies.BUILTIN, ontologies.USER):
        source = where
    else:
        source = ontologies.dir_for(name)
    return {"name": manifest["name"], "release": manifest["release"], "origin": where, "source": source,
            "registry": manifest.get("registry"), "ref": manifest.get("ref"), "commit": manifest.get("commit"),
            "installed_at": _today(), "extends": list(bases)}


def init(root, slug=None, name=None, namespace=None, prefix=None, force=False, ontology=None,
         repo=False, engine=None, pack=None, empty=False):
    """Create or top up a project. Never overwrites authored data unless force is set.

    One of `slug` and `name` is enough: the other derives from it. With an ontology, the vocabulary
    and a small sample graph are installed so `oto build` works immediately. A team that sees the
    whole loop on day one understands what it is building; a team facing an empty config often does
    not. `empty` installs the vocabulary and leaves the graph empty: a real product's graph holds
    what its people said, not the pack's example, and its lexicon seed (which names the example)
    is left out too.
    """
    if not slug and not name:
        raise ValueError("a project needs a name: pass --name (the slug derives from it) or --slug")
    slug = (slug or slug_from(name)).strip().lower()
    name = name or slug.replace("-", " ").title()
    root = os.path.abspath(root)

    for d in DIRS:
        os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
    print("oto init: %s (slug=%s) -> %s" % (name, slug, root))
    print("  created %d directories" % len(DIRS))

    ontology_config = None
    sample_graph = None
    ontology_notes = None
    ontology_rationale = None
    ontology_rules = []
    ontology_questions = {}
    ontology_briefs = {}
    ontology_lexicon = None
    ontology_interview = None
    ontology_guide = None
    ontology_actions = []
    ontology_gold = []
    ontology_record = None
    roots, pack_info, pack_views = None, None, {}
    if pack:
        from .model import packs as _packs
        if ontology:
            raise ValueError("pass --ontology or --pack, not both: a pack embeds its ontology")
        pack_dir = _packs.dir_for(pack)
        if pack_dir is None:
            raise ValueError("unknown pack %r: a name from `oto pack list`, or a directory" % pack)
        problems = _packs.check(pack_dir)
        if problems:
            raise ValueError("pack %r is not usable: %s" % (pack, "; ".join(problems[:5])))
        pack_info = {"manifest": _packs.read(pack_dir), "directory": pack_dir}
        ontology = _packs.embedded_name(pack_dir)
        roots = [_packs.embedded_root(pack_dir)]
        pack_views = _packs.views(pack_dir)
        print("  pack: %s @%d (%s)" % (pack_info["manifest"]["name"], pack_info["manifest"]["release"], pack_dir))
    if ontology:
        from .model import ontologies as _ontologies
        from .model import registry as _registry
        names, wanted = [], {}
        for given in (t.strip() for t in ontology.split(",") if t.strip()):
            one, release = _registry.split_release(given)
            names.append(one)
            wanted[one] = release
        for one in names:
            if _ontologies.dir_for(one, roots) is None:
                _record, entry = _registry.find(one)
                if entry is not None:
                    raise ValueError("ontology %r is not on this machine; the registry %r lists it at release %s: "
                                     "oto ontology add %s" % (one, _record["name"], entry.get("release"), one))
                raise ValueError("unknown ontology %r. Available: %s"
                                 % (one, ", ".join(_ontologies.available()) or "none"))
            if wanted[one] is not None and _ontologies.manifest_for(one, roots)["release"] != wanted[one]:
                raise ValueError("ontology %r is at release %s on this machine, not %d: oto ontology add %s@%d"
                                 % (one, _ontologies.manifest_for(one, roots)["release"], wanted[one], one, wanted[one]))
            problems = _ontologies.self_check(one, roots)
            if problems:
                raise ValueError("ontology %r is not usable: %s" % (one, "; ".join(problems)))
        if len(names) == 1:
            result = _ontologies.composed(names[0], roots=roots)
            ontology_config, sample_graph, ontology_notes = result["config"], result["sample"], result["readme"]
            ontology_rationale = result["rationale"]
            ontology_rules = result["rules"]
            ontology_questions = result["questions"]
            ontology_briefs = result["briefs"]
            ontology_lexicon, ontology_interview, ontology_gold = result["lexicon"], result["interview"], result["gold"]
            ontology_guide = result.get("guide")
            ontology_actions = list(result.get("actions") or [])
            manifest = result["manifest"]
            print("  ontology: %s @%d%s" % (names[0], manifest["release"],
                                            (" (extends %s)" % ", ".join(result["report"]["parts"][:-1]))
                                            if len(result["report"]["parts"]) > 1 else ""))
            ontology_record = _ontology_record(names[0], _ontologies, result["report"]["parts"][:-1], pack=pack_info)
        else:
            ontology_config, sample_graph, ontology_notes, ontology_rationale, report = _ontologies.merge(names)
            ontology_rules = list(ontology_config.pop("_rules", None) or [])   # carried by the merge, not config
            ontology_questions = dict(ontology_config.pop("_questions", None) or {})
            ontology_briefs = dict(ontology_config.pop("_briefs", None) or {})
            ontology_lexicon = ontology_config.pop("_lexicon", None)
            ontology_interview = ontology_config.pop("_interview", None)
            ontology_guide = ontology_config.pop("_guide", None)
            ontology_actions = list(ontology_config.pop("_actions", None) or [])
            ontology_gold = list(ontology_config.pop("_gold", None) or [])
            print("  merged %d ontologies: %d classes, %d relations. Prune before accepting."
                  % (len(names), report["classes"], report["properties"]))
            for kind, first, second in report["class_clashes"]:
                print("    class %-24s described differently in %s and %s; kept %s" % (kind, first, second, first))
            for relation, first, second in report["relation_clashes"]:
                print("    relation %-21s domain or range differ in %s and %s; widened to both" % (relation, first, second))
            ontology_record = {"name": ontology, "release": None, "source": "merge",
                               "commit": None, "installed_at": _today(),
                               "parts": [_ontology_record(one, _ontologies, _ontologies.parts(one)[:-1]) for one in names]}
        ontology_config = dict(ontology_config, name=name)

    config = {
        "_about": "Project identity. Every generated name derives from `slug`, so several knowledge "
                  "bases coexist on one machine without collisions. Vocabulary lives in "
                  "ontology.config.json.",
        "slug": slug,
        "name": name,
        "namespace": namespace or "https://%s.example/kg/" % slug,
        "prefix": prefix or slug,
        "db_name": "%s.db" % slug,
        "server_name": "%s-kg" % slug,
        "oto_version": __version__,
    }
    if ontology_record:
        config["ontology"] = ontology_record
    _write(os.path.join(root, "project.config.json"), config, force, "project.config.json")

    _write(os.path.join(root, "ontology.config.json"), ontology_config or {
        "_about": "Your domain vocabulary. This file is the ONLY source of it: the build fails if the "
                  "graph uses a class or relation declared nowhere here. A class is {definition}; a "
                  "relation is {domain, range, inverse, definition}. Use A|B for a union. Raise "
                  "`ontology_version` when a change breaks existing data, then run "
                  "`oto ontology accept`. Set `strict_domains` to true once every edge respects its "
                  "declared domain and range.",
        "name": name,
        "ontology_version": 1,
        "strict_domains": False,
        "classes": {},
        "properties": {},
        "temporal": TEMPORAL,
    }, force, "ontology.config.json")

    if ontology and ontology_rules:
        import types

        from .reason import rules as _rules
        holder = types.SimpleNamespace(data=root)          # the rules module addresses a project
        if not os.path.exists(_rules.path_for(holder)) or force:
            _rules.save(holder, ontology_rules)
            print("  wrote: %s" % _rules.NAME)
        else:
            print("  kept (exists): %s" % _rules.NAME)
    if ontology and ontology_questions:
        import types
        from .reason import questions as _questions
        holder = types.SimpleNamespace(data=root)
        if not os.path.exists(_questions.path_for(holder)) or force:
            _questions.save(holder, ontology_questions)
            print("  wrote: %s" % _questions.NAME)
        else:
            print("  kept (exists): %s" % _questions.NAME)
    if ontology and ontology_briefs:
        import types
        from .reason import briefs as _briefs
        holder = types.SimpleNamespace(data=root)
        if not os.path.exists(_briefs.path_for(holder)) or force:
            _briefs.save(holder, ontology_briefs)
            print("  wrote: %s" % _briefs.NAME)
        else:
            print("  kept (exists): %s" % _briefs.NAME)

    for action in ontology_actions:
        target = os.path.join(root, "actions", action["id"] + ".json")
        _write(target, action, force, os.path.join("actions", action["id"] + ".json"))

    if ontology_rationale:
        from .model import rationale as _rationale
        _write(os.path.join(root, _rationale.RATIONALE_NAME), {
            "_about": ("Why each class and relation exists, and who confirmed it. `validated_by` is "
                       "empty until a person who knows the domain has actually confirmed the entry. "
                       "Run `oto ontology rationale` to see coverage."),
            "classes": ontology_rationale.get("classes") or {},
            "properties": ontology_rationale.get("properties") or {},
        }, force, _rationale.RATIONALE_NAME)

    if empty:
        ontology_lexicon = None
    if ontology_lexicon and (ontology_lexicon.get("entries") or []):
        _write(os.path.join(root, "lexicon.json"), {
            "_about": ("Jargon, acronyms and synonyms mapped to entities, so a question in the reader's "
                       "words resolves. Seeded by the ontology; the targets name its sample and will "
                       "need re-pointing at your own entities."),
            "entries": ontology_lexicon["entries"]}, force, "lexicon.json")
    if ontology_interview:
        _write(os.path.join(root, "INTERVIEW.md"),
               "%s\n\n---\n\nInstalled from the `%s` ontology by `oto init`: the questions the "
               "ontology-interview skill asks in this domain, in order. Edit them as the domain teaches you.\n"
               % (ontology_interview.rstrip(), ontology), force, "INTERVIEW.md")
    for view_name, source in sorted(pack_views.items()):
        target = os.path.join(root, "views", view_name)
        if os.path.exists(target) and not force:
            print("  kept (exists): %s" % os.path.join("views", view_name))
            continue
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store"))
        print("  wrote: %s" % os.path.join("views", view_name))
    if ontology_guide:
        _write(os.path.join(root, "GUIDE.md"),
               "%s\n\n---\n\nInstalled from the `%s` ontology by `oto init`: what this domain's graph is for and "
               "how to read it. The concierge skill quotes it to a newcomer. Edit it as the project teaches you.\n"
               % (ontology_guide.rstrip(), ontology), force, "GUIDE.md")
    if ontology_gold:
        os.makedirs(os.path.join(root, "gold"), exist_ok=True)
        _write(os.path.join(root, "gold", "patterns.jsonl"),
               "\n".join(json.dumps(entry, ensure_ascii=False) for entry in ontology_gold) + "\n",
               force, os.path.join("gold", "patterns.jsonl"))

    if ontology_notes:
        _write(os.path.join(root, "ONTOLOGY-NOTES.md"),
               "%s\n\n---\n\nInstalled from the `%s` ontology by `oto init`. Edit the vocabulary in\n"
               "`ontology.config.json`, then record your own reasoning here.\n"
               % (ontology_notes.rstrip(), ontology),
               force, "ONTOLOGY-NOTES.md")

    if empty:
        sample_graph, ontology_lexicon = None, None
        print("  graph: empty (--empty); the ontology's sample stays in the ontology")
    _write(os.path.join(root, "graph.json"), sample_graph or {
        "_about": "The curated knowledge graph. Hand-authored, or authored by an agent under review. "
                  "This is the source of truth; everything under build/ is compiled from it.",
        "nodes": [],
        "edges": [],
    }, force, "graph.json")

    _write(os.path.join(root, "README.md"), PROJECT_README.format(name=name), force, "README.md")
    if repo:
        from . import repo as _repo
        _repo.write(root, slug, name, engine=engine, force=force, writer=_write)
    else:
        _write(os.path.join(root, ".gitignore"), PROJECT_GITIGNORE, force, ".gitignore")

    print("\nProject ready. Next:")
    if repo:
        print("  this project is laid out to live in a GitHub repository:")
        print("    git init && git add -A && git commit -m 'oto init' && push it")
        print("    a push to inbox/ runs the ingest workflow; pull requests run the gates;")
        print("    a merge to main builds and publishes the store. Read CLAUDE.md.")
    if ontology:
        print("  1) it already builds:  oto build --project %s" % root)
        print("  2) then ask it something:  oto query --project %s entity \"<a label>\"" % root)
        print("  3) read ONTOLOGY-NOTES.md, edit ontology.config.json, replace graph.json")
    else:
        print("  1) put source documents in %s" % os.path.join(root, "inbox"))
        print("  2) declare your classes and properties in ontology.config.json")
        print("  3) author graph.json, then run: oto build --project %s" % root)
        print("  (or start from a vocabulary: oto init --ontology <name>)")
    return root
