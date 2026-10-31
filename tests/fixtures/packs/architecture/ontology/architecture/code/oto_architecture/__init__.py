# -*- coding: utf-8 -*-
"""The architecture pack's code (ADR-0011): the architecture graph's commands (roadmap Epic H): a framework's model in and out (H1), the code map
and compile on merge (H2).

    oto arch import --framework <name> --file model.json --at YYYY-MM-DD [--name <slug>] [--environment environment.<id>]
    oto arch export --framework <name> [--out model.json]
    oto arch map --repo <path> --repository repo.<id> --at YYYY-MM-DD [--name <slug>]
    oto arch compile --at YYYY-MM-DD --by <who> [--note "..."]
    oto arch impact --decision <id|ADR-nnn> | --orphans | --untraced | --files <paths...> [--format text|markdown]

`map` scans a code repository by a declared convention (`oto.codemap.json` at its root, else every
directory under `src/` is a module of the component named after it) into a code-map document and a
proposal: a `CodeModule` per module with its path and language, `located_in` the repository the
estate declares, `implemented_by` from the component the convention names when the graph holds it
(a module whose component the graph lacks is proposed untraced, never a component invented: AR9
lists it), and the last `Commit` that `touches` each module when the repository is a git checkout.
Mapped again after a merge, the modules are the same facts and the new commit is one more node.

`compile` runs what project.config.json declares under `arch` ({"models": [{"framework", "path"}], "environment":
environment.<id>, "codemap": {"repo": path, "repository": repo.<id>}}): the imports and the map,
through the gates and applied with the merge in the note, then built. A merge the gates refuse
leaves no candidate behind and names the findings. The `oto architecture` workflow runs it on
every merge to main, so the graph matches main and nobody edits it by hand.

`import` and `export` read and write a framework's model through the adapter the framework's pack
provides (`provides.adapters`, oto/extensions.py; `--framework <name>`). The adapter writes a
document in the corpus and a proposal in the architecture vocabulary that goes through the gates like
any other change, and walks the live graph back into the framework's form; this module knows no
framework. A node from a framework carries `external_id`, `external_type` and `external_payload`;
the model's document carries `framework` and the model's header.
"""
import collections
import contextlib
import fnmatch
import glob as _glob
import io
import json
import os
import re
import subprocess

from oto.naming import slug as _slug
from oto.project import ProjectError

PREFIX = {"System": "system", "Component": "component", "DataStore": "datastore", "Environment": "environment", "Role": "role"}
RELATIONSHIP, CONTROL, FLOW, STEP, INTERFACE, DECISION, DOCUMENT = "Relationship", "Control", "Flow", "FlowStep", "Interface", "Decision", "Document"
MODULE, COMMIT = "CodeModule", "Commit"
CONVENTION_NAME = "oto.codemap.json"
DEFAULT_CONVENTION = {"modules": [{"path": "src/*", "component": "component.{name}"}]}
DEFAULT_IGNORE = (".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", "target", ".tox", ".mypy_cache", ".pytest_cache")
LANGUAGES = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".java": "java",
             ".go": "go", ".rs": "rust", ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".sql": "sql", ".sh": "shell", ".scala": "scala", ".php": "php",
             ".swift": "swift", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".tf": "terraform", ".dart": "dart", ".ex": "elixir", ".exs": "elixir"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ArchError(ProjectError):
    """A refusal, in words the person can act on."""


# ---- the code map ----

def convention_for(repo_path):
    """`oto.codemap.json` at the repository root, else the default: every directory under src/ is a
    module of the component named after it."""
    path = os.path.join(repo_path, CONVENTION_NAME)
    if not os.path.isfile(path):
        return DEFAULT_CONVENTION
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError as exc:
            raise ArchError("%s is not JSON: %s" % (path, exc))


def _ignored(relative, ignore):
    parts = relative.replace(os.sep, "/").split("/")
    for pattern in ignore:
        if any(fnmatch.fnmatch(part, pattern) for part in parts) or fnmatch.fnmatch(relative.replace(os.sep, "/"), pattern):
            return True
    return False


def _language(directory, ignore):
    counts = collections.Counter()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not _ignored(d, ignore)]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in LANGUAGES:
                counts[LANGUAGES[ext]] += 1
    return counts.most_common(1)[0][0] if counts else None


def _last_commit(repo_path, relative):
    try:
        out = subprocess.run(["git", "-C", repo_path, "log", "-1", "--format=%H%x1f%ad%x1f%an%x1f%s", "--date=short", "--", relative],
                             check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not out:
        return None
    sha, date, author, subject = (out.split("\x1f") + ["", "", "", ""])[:4]
    return {"sha": sha, "committed_on": date, "author": author, "message": subject}


def scan(repo_path, convention):
    """{"modules": [{"path", "component", "language", "commit"}], "git": bool}: the repository read by
    the convention, modules in path order, each once (the first spec that names a path wins)."""
    if not isinstance(convention, dict) or not isinstance(convention.get("modules"), list):
        raise ArchError("a code-map convention is {\"modules\": [{\"path\": \"src/*\", \"component\": \"component.{name}\"}, ...], \"ignore\": [...]}")
    ignore = list(DEFAULT_IGNORE) + [str(x) for x in convention.get("ignore") or []]
    is_git = os.path.isdir(os.path.join(repo_path, ".git"))
    found, seen = [], set()
    for spec in convention["modules"]:
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str) or not spec["path"].strip():
            raise ArchError("every module spec names a `path` (a directory or a glob, relative to the repository) and a `component` (an id with {name}, or null)")
        excepted = {str(x).strip("/") for x in spec.get("except") or []}
        matches = sorted(d for d in _glob.glob(os.path.join(repo_path, spec["path"].strip("/"))) if os.path.isdir(d))
        for directory in matches:
            relative = os.path.relpath(directory, repo_path).replace(os.sep, "/")
            if relative in seen or relative in excepted or _ignored(relative, ignore):
                continue
            seen.add(relative)
            component = spec.get("component")
            if isinstance(component, str):
                component = component.replace("{name}", _slug(relative.rsplit("/", 1)[-1])) or None
            found.append({"path": relative, "component": component, "language": _language(directory, ignore),
                          "commit": _last_commit(repo_path, relative) if is_git else None})
    found.sort(key=lambda m: m["path"])
    return {"modules": found, "git": is_git}


def _repository_slug(repository_id):
    return _slug(repository_id.split(".", 1)[1] if "." in repository_id else repository_id)


def module_id(repository_id, path):
    return "codemodule.%s-%s" % (_repository_slug(repository_id), _slug(path))


def module_line(module):
    return "%s (%s)" % (module["path"], module.get("language") or "unknown")


def commit_line(commit):
    """The full sha, so the gate finds the value the fact carries in the document it cites."""
    return "%s %s %s" % (commit["sha"], commit["committed_on"], commit["author"])


def codemap_document(found, repository_id, repo_path, at, source):
    repo = _repository_slug(repository_id)
    title = "Code map of %s" % repo
    lines = ["# %s" % title, "", "Read from %s on %s by `oto arch map` (%s). One line per module, with its language and the component the convention "
             "names, and one per last commit that touched it; each fact in the graph quotes its line here." % (repo_path, at, source), "", "## Modules", ""]
    for m in found["modules"]:
        lines.append("- %s: %s" % (module_line(m), m["component"] or "no component"))
        if m.get("commit"):
            lines.append("  - %s: %s" % (commit_line(m["commit"]), m["commit"]["message"]))
    return title, "\n".join(lines).rstrip() + "\n"


def propose_codemap(found, repository_id, doc, at, graph_ids, repo_path, source):
    """(proposal, gaps): modules, their commits and the edges to the estate's repository and components."""
    repo = _repository_slug(repository_id)
    title, _text = codemap_document(found, repository_id, repo_path, at, source)
    nodes = [{"id": "document.%s" % doc, "type": DOCUMENT, "label": title, "summary": "The code map of %s as `oto arch map` read it; the date is the fact's own." % repo,
              "attributes": {"kind": "architecture"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": title}]}]
    edges, gaps, commits = [], [], {}
    for m in found["modules"]:
        mid = module_id(repository_id, m["path"])
        attributes = {"path": m["path"]}
        if m.get("language"):
            attributes["language"] = m["language"]
        nodes.append({"id": mid, "type": MODULE, "label": m["path"], "summary": "The %s module of %s." % (m["path"], repo), "attributes": attributes,
                      "valid_from": at, "evidence": [{"doc": doc, "where": "modules", "quote": module_line(m)}]})
        edges.append({"from": mid, "rel": "located_in", "to": repository_id})
        if m["component"]:
            if m["component"] in graph_ids:
                edges.append({"from": m["component"], "rel": "implemented_by", "to": mid})
            else:
                gaps.append("%s: the convention names %s, which the graph lacks; the module is proposed untraced (AR9 lists it)" % (m["path"], m["component"]))
        if m.get("commit"):
            c = m["commit"]
            cid = "commit.%s" % c["sha"][:12]
            if cid not in commits:
                commits[cid] = True
                nodes.append({"id": cid, "type": COMMIT, "label": "%s %s" % (c["sha"][:7], c["message"]), "summary": c["message"],
                              "attributes": {"sha": c["sha"], "committed_on": c["committed_on"], "author": c["author"], "message": c["message"]},
                              "valid_from": c["committed_on"] or at, "evidence": [{"doc": doc, "where": "modules", "quote": commit_line(c)}]})
            edges.append({"from": cid, "rel": "touches", "to": mid})
    if not found["git"]:
        gaps.append("%s is not a git checkout: no commits recorded" % repo_path)
    return {"source_doc": doc, "as_of": at, "nodes": nodes, "edges": edges}, gaps


def map_repo(project, repo_path, repository_id, at, name=None):
    """Scan, write the document and the proposal. Returns {"doc", "document", "archive", "proposal",
    "modules", "commits", "gaps", "convention"}."""
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date the code was read is never defaulted")
    if not repository_id:
        raise ArchError("--repository repo.<id> names the Repository the estate declares (SA14), where these modules live")
    with open(project.ontology_config_path, encoding="utf-8") as f:
        classes = json.load(f).get("classes") or {}
    if MODULE not in classes or COMMIT not in classes:
        raise ArchError("the vocabulary declares no CodeModule and Commit: the architecture ontology does (oto init --ontology architecture, or compose it)")
    if not os.path.isdir(repo_path):
        raise ArchError("no such repository: %s" % repo_path)
    from oto.naming import graph_ids as _graph_ids
    graph_ids = _graph_ids(project)
    if repository_id not in graph_ids:
        raise ArchError("the graph holds no %s. The estate declares the repository (a Repository node, SA14) before the code map describes it" % repository_id)
    convention = convention_for(repo_path)
    source = CONVENTION_NAME if os.path.isfile(os.path.join(repo_path, CONVENTION_NAME)) else "the default convention, src/*"
    found = scan(repo_path, convention)
    doc = "codemap-%s" % (_slug(name) if name else _repository_slug(repository_id))
    title, text = codemap_document(found, repository_id, repo_path, at, source)
    proposal, gaps = propose_codemap(found, repository_id, doc, at, graph_ids, repo_path, source)
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
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out, "modules": len(found["modules"]),
            "commits": sum(1 for n in proposal["nodes"] if n["type"] == COMMIT), "gaps": gaps, "convention": source}


# ---- compile on merge ----

def compile_project(project, at, by, note=None):
    """What project.config.json declares under `arch`, imported and mapped, through the gates, applied
    and built. Returns {"proposals": [...], "gaps": [...], "applied": True, "built": True}. Refused
    at the gate, it aborts the candidate and raises with the findings."""
    from oto.curate import session as _session
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date of the merge is never defaulted")
    if not (by or "").strip():
        raise ArchError("--by names who compiles: the workflow, or a person")
    arch_cfg = project.config().get("arch") or {}
    models = [(m.get("framework"), m.get("path")) for m in arch_cfg.get("models") or [] if isinstance(m, dict)]
    for key, paths in arch_cfg.items():                             # a framework's name as a key: {"<framework>": ["model.json"]}
        if key not in ("models", "environment", "codemap") and isinstance(paths, list):
            models += [(key, p) for p in paths]
    codemap = arch_cfg.get("codemap") or {}
    if not models and not codemap:
        raise ArchError("project.config.json declares no `arch`: {\"models\": [{\"framework\": \"<name>\", \"path\": \"<model>\"}], \"environment\": \"environment.<id>\", "
                        "\"codemap\": {\"repo\": \"<path>\", \"repository\": \"repo.<id>\"}}. Nothing to compile")
    if _session.exists(project):
        raise ArchError("a candidate is open: apply or abort it before compiling (oto curate apply / abort)")
    proposals, gaps = [], []
    from oto import extensions as _extensions
    for framework, relative in models:
        read = _extensions.adapter(framework)["read"]
        done = read(project, os.path.join(project.data, relative), at, environment=arch_cfg.get("environment"))
        proposals.append(done["proposal"])
        gaps += done["gaps"]
    if codemap:
        if not codemap.get("repository"):
            raise ArchError("arch.codemap names no `repository`: the Repository the estate declares")
        done = map_repo(project, os.path.join(project.data, codemap.get("repo") or "."), codemap["repository"], at)
        proposals.append(done["proposal"])
        gaps += done["gaps"]
    apply_proposals(project, proposals, by, note or "compiled by oto arch compile")
    return {"proposals": proposals, "gaps": gaps, "applied": True, "built": True}


def apply_proposals(project, proposals, by, note):
    """Open a candidate, add each proposal, check, apply with `by` and `note`, build: the engine's
    `oto.curate.apply`, the gates' own way of landing facts a command generated, refused at the gate
    with the findings and the graph unchanged."""
    from oto.curate.apply import GateError, apply_proposals as _through_the_gates
    try:
        _through_the_gates(project, proposals, by, note)
    except GateError as exc:
        raise ArchError(str(exc))


# ---- impact (H4) ----

def _graph_index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    out, inc = {}, {}
    for e in graph.get("edges") or []:
        out.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
        inc.setdefault((e.get("to"), e.get("rel")), []).append(e.get("from"))
    return nodes, out, inc


def decision_id(term):
    """decision.adr-007 as given, or ADR-007 the way a decision record names itself."""
    from oto import adr as _adr
    term = (term or "").strip()
    return _adr.node_id(term) if _adr.ID.match(term) else term


def impact(graph, decision):
    """{"id", "label", "status", "superseded_by", "governs": [{"id", "label", "type", "connections", "modules", "proposals"}],
    "reached": [labels], "modules": [paths], "proposals": [labels]} for a decision."""
    nodes, out, inc = _graph_index(graph)
    did = decision_id(decision)
    d = nodes.get(did)
    if d is None:
        raise ArchError("the graph holds no %s" % did)
    if d.get("type") != "Decision":
        raise ArchError("%s is a %s, not a Decision" % (did, d.get("type")))
    report = {"id": did, "label": d.get("label") or did, "status": "superseded" if d.get("status") == "superseded" else (d.get("attributes") or {}).get("status") or d.get("status"),
              "superseded_by": d.get("superseded_by"), "superseded_by_label": nodes.get(d.get("superseded_by"), {}).get("label") if d.get("superseded_by") else None,
              "governs": [], "reached": [], "modules": [], "proposals": []}
    for gid in out.get((did, "governs"), []) + [x for x in out.get((did, "about"), []) if x not in out.get((did, "governs"), [])]:
        g = nodes.get(gid)
        if g is None:
            continue
        item = {"id": gid, "label": g.get("label") or gid, "type": g.get("type"), "connections": [], "modules": [], "proposals": []}
        for rid in inc.get((gid, "connects_from"), []) + inc.get((gid, "connects_to"), []):
            r = nodes.get(rid)
            if r is None:
                continue
            others = [x for x in out.get((rid, "connects_to"), []) + out.get((rid, "connects_from"), []) if x != gid]
            for other in others or [None]:
                item["connections"].append({"id": rid, "label": r.get("label") or rid, "kind": (r.get("attributes") or {}).get("kind"),
                                            "protocol": (r.get("attributes") or {}).get("protocol"),
                                            "other": nodes.get(other, {}).get("label") if other else None, "other_id": other})
                if other and nodes.get(other, {}).get("label") not in report["reached"] and other != gid:
                    report["reached"].append(nodes.get(other, {}).get("label") or other)
        for mid in out.get((gid, "implemented_by"), []):
            m = nodes.get(mid)
            if m and m.get("type") == "CodeModule":
                path = (m.get("attributes") or {}).get("path") or m.get("label")
                item["modules"].append(path)
                if path not in report["modules"]:
                    report["modules"].append(path)
        for pid in inc.get((gid, "proposes_change_to"), []):
            p = nodes.get(pid)
            if p and ((p.get("attributes") or {}).get("status") or "proposed") == "proposed":
                item["proposals"].append(p.get("label") or pid)
                if (p.get("label") or pid) not in report["proposals"]:
                    report["proposals"].append(p.get("label") or pid)
        report["governs"].append(item)
    return report


def render_impact(report, fmt="text"):
    md = fmt == "markdown"
    head = "## Impact of %s" % report["label"] if md else "Impact of %s" % report["label"]
    L = [head, ""]
    status = "Status: %s" % report["status"]
    if report.get("superseded_by"):
        status += ", superseded by %s" % (report.get("superseded_by_label") or report["superseded_by"])
    L.append(status + ".")
    L.append("")
    if not report["governs"]:
        L.append("Governs nothing the graph holds.")
    else:
        L.append("Governs %d node(s):" % len(report["governs"]))
        for g in report["governs"]:
            bits = ["%d connection(s)" % len(g["connections"])]
            if g["modules"]:
                bits.append("module(s) %s" % ", ".join(g["modules"]))
            if g["proposals"]:
                bits.append("open proposal(s) %s" % ", ".join(g["proposals"]))
            L.append("- %s (%s): %s" % (g["label"], g["id"], ", ".join(bits)))
    if report["reached"]:
        L.append("")
        L.append("Reached through their connections: %s." % ", ".join(report["reached"]))
    if report["modules"]:
        L.append("")
        L.append("Modules to check: %s." % ", ".join(report["modules"]))
    if report["proposals"]:
        L.append("")
        L.append("Open change proposals: %s." % ", ".join(report["proposals"]))
    return "\n".join(L).rstrip() + "\n"


ORPHAN_TYPES = ("System", "Component", "DataStore", "Interface")


def orphans(graph):
    """Systems, components, stores and interfaces no relationship reaches: not an end of any
    Relationship, and for an interface, exposed or consumed by nothing and on no connection."""
    nodes, out, inc = _graph_index(graph)
    found = []
    for n in nodes.values():
        if n.get("type") not in ORPHAN_TYPES or n.get("status") == "superseded":
            continue
        nid = n["id"]
        if n["type"] == "Interface":
            reached = inc.get((nid, "exposes"), []) or inc.get((nid, "consumes"), []) or inc.get((nid, "via"), [])
            why = "exposed by nothing, consumed by nothing, on no connection"
        else:
            reached = inc.get((nid, "connects_from"), []) or inc.get((nid, "connects_to"), [])
            why = "an end of no relationship"
        if not reached:
            found.append({"id": nid, "label": n.get("label") or nid, "type": n["type"], "why": why})
    return sorted(found, key=lambda x: (x["type"], x["label"]))


def untraced(graph):
    """{"modules": [{"id", "path"}], "components": [{"id", "label"}]}: modules nothing implements, components with no module."""
    nodes, out, inc = _graph_index(graph)
    modules = [{"id": n["id"], "path": (n.get("attributes") or {}).get("path") or n.get("label")} for n in nodes.values()
               if n.get("type") == "CodeModule" and n.get("status") != "superseded" and not inc.get((n["id"], "implemented_by"))]
    components = [{"id": n["id"], "label": n.get("label") or n["id"]} for n in nodes.values()
                  if n.get("type") == "Component" and n.get("status") != "superseded"
                  and not any(nodes.get(m, {}).get("type") == "CodeModule" for m in out.get((n["id"], "implemented_by"), []))]
    return {"modules": sorted(modules, key=lambda m: m["path"]), "components": sorted(components, key=lambda c: c["label"])}


def render_orphans(found, fmt="text"):
    L = ["## Orphans" if fmt == "markdown" else "Orphans: nodes no relationship reaches", ""]
    if not found:
        L.append("none: every system, component, store and interface is an end of a relationship.")
    for o in found:
        L.append("- %s (%s, %s): %s" % (o["label"], o["id"], o["type"], o["why"]))
    return "\n".join(L).rstrip() + "\n"


def render_untraced(found, fmt="text"):
    L = ["## Untraced code" if fmt == "markdown" else "Untraced code", ""]
    L.append("Modules nothing implements (%d):" % len(found["modules"]))
    L += ["- %s (%s)" % (m["path"], m["id"]) for m in found["modules"]] or ["- none"]
    L.append("")
    L.append("Components with no module (%d):" % len(found["components"]))
    L += ["- %s (%s)" % (c["label"], c["id"]) for c in found["components"]] or ["- none"]
    return "\n".join(L).rstrip() + "\n"


def impact_of_files(project, paths, fmt="markdown"):
    """The impact of every decision record among `paths`, rendered; "" when none is one. A record
    whose decision the graph does not hold yet is named, so the reviewer knows."""
    from oto import adr as _adr
    from oto.curate import session as _session
    graph = None
    out = []
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if not _adr.is_adr(text):
            continue
        record = _adr.parse(text)
        adr_id = str(record["front"].get("id") or "").strip()
        did = _adr.node_id(adr_id) if adr_id else None
        if graph is None:
            graph = _session.live(project)
        try:
            out.append(render_impact(impact(graph, did), fmt))
        except ArchError:
            head = "## %s" if fmt == "markdown" else "%s"
            out.append((head % ("Impact of %s" % (adr_id or os.path.basename(path)))) + "\n\nThe decision is not in the graph yet (%s): its impact is what this pull request adds. "
                       "Once applied, `oto arch impact --decision %s` reads it.\n" % (did or "no id", adr_id or "<id>"))
    return "\n".join(out)


def _a(n):
    return (n or {}).get("attributes") or {}


def _index(graph):
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if n.get("id")}
    out, inc = {}, {}
    for e in graph.get("edges") or []:
        out.setdefault((e.get("from"), e.get("rel")), []).append(e.get("to"))
        inc.setdefault((e.get("to"), e.get("rel")), []).append(e.get("from"))
    return nodes, out, inc


# ---- measurements (H6): a report or a stated value becomes evidence of a requirement ----

def measure_from(path):
    """(format, value) read from a JUnit XML report, a coverage.py XML report or a k6 summary JSON."""
    import xml.etree.ElementTree as ET
    if not os.path.isfile(path):
        raise ArchError("no such report: %s" % path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("<"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ArchError("%s is not XML: %s" % (path, exc))
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if suites:
            def num(el, key):
                try:
                    return int(el.get(key) or 0)
                except ValueError:
                    return 0
            tests = sum(num(s, "tests") for s in suites)
            failures = sum(num(s, "failures") for s in suites)
            errors = sum(num(s, "errors") for s in suites)
            skipped = sum(num(s, "skipped") for s in suites)
            passed = max(tests - failures - errors - skipped, 0)
            detail = ", ".join(x for x in ("%d failed" % failures if failures else "", "%d error(s)" % errors if errors else "", "%d skipped" % skipped if skipped else "") if x)
            return "junit", "%d of %d tests passed%s" % (passed, tests, " (%s)" % detail if detail else "")
        if root.tag == "coverage" and root.get("line-rate") is not None:
            try:
                rate = float(root.get("line-rate"))
            except ValueError:
                raise ArchError("%s: line-rate is not a number" % path)
            covered, valid = root.get("lines-covered"), root.get("lines-valid")
            detail = " (%s of %s)" % (covered, valid) if covered and valid else ""
            return "coverage", "%d %% of lines covered%s" % (round(rate * 100), detail)
        raise ArchError("%s is XML, but neither a JUnit report (testsuite) nor a coverage.py report (coverage line-rate); the formats read are junit, coverage and k6" % path)
    try:
        data = json.loads(text)
    except ValueError:
        raise ArchError("%s is neither XML nor JSON; the formats read are junit (XML), coverage (XML) and k6 (JSON summary)" % path)
    metrics = (data or {}).get("metrics") if isinstance(data, dict) else None
    duration = (metrics or {}).get("http_req_duration") if isinstance(metrics, dict) else None
    values = (duration or {}).get("values") if isinstance(duration, dict) else None
    if isinstance(values, dict) and values.get("p(95)") is not None:
        count = ((metrics.get("http_reqs") or {}).get("values") or {}).get("count")
        return "k6", "p95 %d ms%s" % (round(float(values["p(95)"])), " over %d requests" % int(count) if count else "")
    raise ArchError("%s is JSON, but not a k6 summary (metrics.http_req_duration.values.p(95)); the formats read are junit, coverage and k6" % path)


def measure(project, nfr_id, at, value=None, path=None, source=None):
    """A measurement as Evidence of the requirement, cited to a document. Returns {"doc", "document", "archive", "proposal", "value", "format"}."""
    from oto.curate import session as _session
    if not at or not ISO_DATE.match(str(at)):
        raise ArchError("--at YYYY-MM-DD is required: the date of the measurement is never defaulted")
    if not (value or "").strip() and not path:
        raise ArchError("a measurement comes from a report (--from <junit.xml|coverage.xml|k6-summary.json>) or is stated (--value \"...\")")
    graph = _session.live(project)
    nodes, out, inc = _index(graph)
    nfr = nodes.get(nfr_id)
    if nfr is None:
        raise ArchError("the graph holds no %s" % nfr_id)
    if nfr.get("type") != "NFR":
        raise ArchError("%s is a %s, not an NFR (a Requirement with a metric and a budget): only a requirement with a budget is measured" % (nfr_id, nfr.get("type")))
    fmt = "stated"
    if path:
        fmt, value = measure_from(path)
    value = value.strip()
    slug = _slug(nfr_id.split(".", 1)[1] if "." in nfr_id else nfr_id)
    doc = "measure-%s-%s" % (slug, at)
    a = _a(nfr)
    lines = ["# Measurement of %s" % (nfr.get("label") or nfr_id), "",
             "Recorded by `oto arch measure` on %s, %s. The measured value next to the budget, so what the requirement asks and what was observed are one line."
             % (at, "from a %s report, %s" % (fmt, os.path.basename(path)) if path else "a value stated at the prompt"), "", "## Measured", "",
             "- %s: %s, budget %s (%s)" % (nfr.get("label") or nfr_id, value, a.get("budget") or "none set", a.get("metric") or "no metric")]
    text = "\n".join(lines) + "\n"
    corpus = os.path.join(project.layout.corpus, doc + ".md")
    archive = os.path.join(project.layout.archive, doc + ".md")
    for target in (corpus, archive):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    evidence_id = "evidence.%s" % doc
    attributes = {"kind": "measurement", "value": value, "observed_on": at}
    if source or path:
        attributes["source_url"] = source or os.path.basename(path)
    proposal = {"source_doc": doc, "as_of": at, "nodes": [
        {"id": "document.%s" % doc, "type": "Document", "label": "Measurement of %s" % (nfr.get("label") or nfr_id), "summary": "A measurement of %s as recorded; the date is the fact's own." % nfr_id,
         "attributes": {"kind": "run"}, "valid_from": at, "evidence": [{"doc": doc, "where": "title", "quote": "Measurement of %s" % (nfr.get("label") or nfr_id)}]},
        {"id": evidence_id, "type": "Evidence", "label": "%s measured on %s" % (nfr.get("label") or nfr_id, at), "summary": "%s: %s on %s." % (a.get("metric") or nfr_id, value, at),
         "attributes": attributes, "valid_from": at, "evidence": [{"doc": doc, "where": "measured", "quote": value}]}],
        "edges": [{"from": evidence_id, "rel": "measurement_of", "to": nfr_id}]}
    for comp in inc.get((nfr_id, "satisfies"), []):
        if nodes.get(comp, {}).get("type") in ("Component", "System", "Interface"):
            proposal["edges"].append({"from": evidence_id, "rel": "evidence_of", "to": comp})
    out_dir = os.path.join(project.data, "proposals")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, doc + ".json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return {"doc": doc, "document": corpus, "archive": archive, "proposal": out_path, "value": value, "format": fmt}
