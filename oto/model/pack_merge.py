# -*- coding: utf-8 -*-
"""A pack's vocabulary as code (docs/plans/people-and-graphs.md, phase 2): files that merge, and a merge that knows terms.

Two authors adding unrelated terms conflicted in every file they touched, because new terms land at the same spot.
`format_` writes the pack's own files in a canonical form (sorted keys, and the sample's nodes and edges in a stable
order), which makes conflicts rarer, but two inserts at one spot still conflict in git whatever the format. So
`rebase` merges term by term: two new terms never clash, and only the same term changed two ways stops it. A git merge
driver wouldn't do, because GitHub's merge button doesn't run one.

`changes` says what moved between two versions of the vocabulary, for a reviewer, and which of it would break a graph
already on the pack, since a release is a plain number and has no way to say so itself.
"""
import json
import os

from .. import route as _route

CONFIG = "ontology.config.json"
RATIONALE = "ontology.rationale.json"
QUESTIONS = "questions.json"
SAMPLE = "sample.graph.json"
RULES = "rules.json"
#: the pack's own files, each with a canonical form and a term-level merge
TERM_FILES = (CONFIG, RATIONALE, QUESTIONS, SAMPLE, RULES)
MANIFEST = "manifest.json"
TRIAL_PREFIX = "trial/"
_GONE = object()


# ---- canonical files ----

def _edge_key(edge):
    return (str(edge.get("from")), str(edge.get("rel")), str(edge.get("to")))


def canonical(filename, payload):
    """A payload in its canonical order. Dict keys sort when written; the lists whose order means nothing sort here."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if filename == SAMPLE:
        if isinstance(out.get("nodes"), list):
            out["nodes"] = sorted(out["nodes"], key=lambda n: str(n.get("id")) if isinstance(n, dict) else "")
        if isinstance(out.get("edges"), list):
            out["edges"] = sorted(out["edges"], key=lambda e: _edge_key(e) if isinstance(e, dict) else ("", "", ""))
    if filename == RULES and isinstance(out.get("rules"), list):
        out["rules"] = sorted(out["rules"], key=lambda r: str(r.get("id")) if isinstance(r, dict) else "")
    return out


def canonical_text(filename, payload):
    return json.dumps(canonical(filename, payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _own_dir(directory):
    from . import packs as _packs
    return os.path.join(_packs.embedded_root(directory), _packs.embedded_name(directory))


def not_canonical(directory):
    """The pack's own files not in canonical form, by name. A file that isn't JSON is the check's to say, not this."""
    out = []
    own = _own_dir(directory)
    for filename in TERM_FILES:
        path = os.path.join(own, filename)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            if canonical_text(filename, json.loads(text)) != text:
                out.append(filename)
        except ValueError:
            continue
    return out


def format_(directory):
    """Write the pack's own files in canonical form. Returns the files it changed."""
    changed = not_canonical(directory)
    own = _own_dir(directory)
    for filename in changed:
        path = os.path.join(own, filename)
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(canonical_text(filename, payload))
    return changed


# ---- a term-level merge ----

def _keyed(filename, payload):
    """A payload with its lists of terms as maps, so a three-way merge sees terms rather than positions."""
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if filename == SAMPLE:
        if isinstance(out.get("nodes"), list):
            out["nodes"] = {str(n.get("id")): n for n in out["nodes"] if isinstance(n, dict)}
        if isinstance(out.get("edges"), list):
            out["edges"] = {"|".join(_edge_key(e)): e for e in out["edges"] if isinstance(e, dict)}
    if filename == RULES and isinstance(out.get("rules"), list):
        out["rules"] = {str(r.get("id")): r for r in out["rules"] if isinstance(r, dict)}
    return out


def _unkeyed(filename, payload):
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    if filename == SAMPLE:
        for key in ("nodes", "edges"):
            if isinstance(out.get(key), dict):
                out[key] = list(out[key].values())
    if filename == RULES and isinstance(out.get("rules"), dict):
        out["rules"] = list(out["rules"].values())
    return out


def merge3(base, ours, theirs, where=""):
    """The three-way merge of two JSON values: (merged, clashes). What only one side changed is taken, and the same
    change on both sides is one change; a value both changed two ways is a clash, named by its path."""
    if ours == theirs:
        return ours, []
    if ours == base:
        return theirs, []
    if theirs == base:
        return ours, []
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base_map = base if isinstance(base, dict) else {}
        merged, clashes = {}, []
        for key in sorted(set(ours) | set(theirs) | set(base_map)):
            value, found = merge3(base_map.get(key, _GONE), ours.get(key, _GONE), theirs.get(key, _GONE),
                                  "%s.%s" % (where, key) if where else str(key))
            clashes += found
            if value is not _GONE:
                merged[key] = value
        return merged, clashes
    return ours, [where or "(the whole file)"]


def _json_at(root, ref, path):
    text = _route.read_at(root, ref, path)
    if text is None:
        return _GONE
    try:
        return json.loads(text)
    except ValueError:
        return _GONE


def rebase(directory, onto, head="HEAD"):
    """Re-apply what a branch changed in the pack onto a moved main, term by term, in the working tree: the terms only one
    side touched are taken, and the same term changed two ways is a conflict and nothing is written. Another file both sides
    changed is one too, but for the trial's, which is never published: main's stands. Returns {ok, conflicts, onto, base,
    head, written, steps}: `steps` are the git commands that put the change on `onto` as one commit, run by the person, since
    a pack author's commit is theirs; nothing here touches git."""
    root = os.path.abspath(directory)
    onto_sha, head_sha = _route._resolve(root, onto), _route._resolve(root, head)
    base_sha = _route._merge_base(root, onto_sha, head_sha)
    out = {"ok": False, "conflicts": [], "onto": onto_sha, "base": base_sha, "head": head_sha, "written": [], "steps": []}
    if onto_sha == base_sha:
        out["ok"] = True
        out["conflicts"].append("nothing to do: %s is the base of this change already" % onto[:12])
        return out
    if _route._resolve(root, "HEAD") != head_sha:
        out["conflicts"].append("the steps act on the branch checked out here, and that is not %s: check it out first" % head[:12])
        return out
    dirty = _route._git(root, "status", "--porcelain", "--untracked-files=no")[1]
    if dirty.strip():
        out["conflicts"].append("uncommitted changes here, which the steps would throw away: commit them or set them aside first (%s)"
                                % ", ".join(line[3:] for line in dirty.splitlines()[:5]))
        return out

    own = os.path.relpath(_own_dir(root), root).replace(os.sep, "/")
    handled = {}
    for filename in TERM_FILES:
        handled["%s/%s" % (own, filename)] = filename
    for manifest in (MANIFEST, "%s/%s" % (own, MANIFEST)):
        handled[manifest] = MANIFEST
    head_changed = _route._changed(root, base_sha, head_sha)
    onto_changed = _route._changed(root, base_sha, onto_sha)
    merged = {}
    for path, filename in handled.items():
        if path not in head_changed or path not in onto_changed:
            continue
        base = _keyed(filename, _json_at(root, base_sha, path))
        value, clashes = merge3(base, _keyed(filename, _json_at(root, head_sha, path)), _keyed(filename, _json_at(root, onto_sha, path)))
        out["conflicts"] += ["%s: %s changed here and on %s, two ways" % (path, clash, onto[:12]) for clash in clashes]
        merged[path] = (filename, value)
    others = head_changed - set(handled)
    kept_from_onto = []
    for path in sorted(others & onto_changed):
        if _route._blob(root, onto_sha, path) == _route._blob(root, head_sha, path):
            continue
        if path.startswith(TRIAL_PREFIX):
            kept_from_onto.append(path)
        else:
            out["conflicts"].append("%s changed here and on %s: this file isn't terms, so a person settles it" % (path, onto[:12]))
    if out["conflicts"]:
        return out

    for path, (filename, value) in merged.items():
        target = os.path.join(root, *path.split("/"))
        if value is _GONE:
            if os.path.exists(target):
                os.remove(target)
            continue
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(canonical_text(filename, _unkeyed(filename, value)) if filename != MANIFEST else json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        out["written"].append(path)
    # what only this branch changed comes along as it is; what only main changed stays main's, because the steps start from main
    stage = sorted((head_changed - set(kept_from_onto)) | set(merged))
    stage = [p for p in stage if os.path.exists(os.path.join(root, *p.split("/"))) or _route._blob(root, onto_sha, p)]
    out["steps"] = _route.git_steps(onto_sha, stage, "This change to the vocabulary, on the new main")
    out["ok"] = True
    return out


# ---- what moved, and what it would break ----

def _own_payloads_from_dir(own):
    out = {}
    for filename in (CONFIG, QUESTIONS):
        path = os.path.join(own, filename)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[filename] = json.load(f)
    return out


def snapshot_here(directory):
    return _own_payloads_from_dir(_own_dir(directory))


def snapshot_at(directory, ref):
    root = os.path.abspath(directory)
    own = os.path.relpath(_own_dir(root), root).replace(os.sep, "/")
    out = {}
    for filename in (CONFIG, QUESTIONS):
        value = _json_at(root, ref, "%s/%s" % (own, filename))
        if value is not _GONE:
            out[filename] = value
    return out


def resolve_release(directory, against):
    """What `--against` names: a pack's directory, a git ref, or a release number, whose tag is v<number>. Returns a snapshot of
    the vocabulary there. Raises ValueError when it names nothing."""
    from . import packs as _packs
    if os.path.isdir(against) and _packs.dir_for(os.path.abspath(against)):
        return _own_payloads_from_dir(_own_dir(os.path.abspath(against)))
    root = os.path.abspath(directory)
    for ref in (against, "v%s" % against):
        code, out, _err = _route._git(root, "rev-parse", "--verify", "--quiet", "%s^{commit}" % ref)
        if code == 0 and out.strip():
            return snapshot_at(root, out.strip())
    raise ValueError("%s names no release here: a release number with a tag v<number>, a git ref, or a pack's directory" % against)


def _section(payload, key):
    value = (payload or {}).get(key)
    return value if isinstance(value, dict) else {}


def changes(before, after):
    """What moved between two snapshots: {added, changed, removed, breaking}, each a list of words a reviewer reads."""
    out = {"added": [], "changed": [], "removed": [], "breaking": []}
    old_config, new_config = before.get(CONFIG) or {}, after.get(CONFIG) or {}

    def compare(kind, old, new):
        for name in sorted(set(new) - set(old)):
            out["added"].append("%s %s" % (kind, name))
        for name in sorted(set(old) - set(new)):
            out["removed"].append("%s %s" % (kind, name))
        for name in sorted(set(old) & set(new)):
            if old[name] != new[name]:
                out["changed"].append("%s %s" % (kind, name))

    compare("class", _section(old_config, "classes"), _section(new_config, "classes"))
    compare("relation", _section(old_config, "properties"), _section(new_config, "properties"))
    old_attributes, new_attributes = _section(old_config, "attributes"), _section(new_config, "attributes")
    flat_old = {"%s.%s" % (c, a): v for c, attrs in old_attributes.items() if isinstance(attrs, dict) for a, v in attrs.items()}
    flat_new = {"%s.%s" % (c, a): v for c, attrs in new_attributes.items() if isinstance(attrs, dict) for a, v in attrs.items()}
    compare("attribute", flat_old, flat_new)
    compare("question", _section(before.get(QUESTIONS), "questions"), _section(after.get(QUESTIONS), "questions"))

    for name in sorted(set(_section(old_config, "classes")) - set(_section(new_config, "classes"))):
        out["breaking"].append("class %s is gone: a graph holding one no longer builds" % name)
    old_properties, new_properties = _section(old_config, "properties"), _section(new_config, "properties")
    for name in sorted(old_properties):
        if name not in new_properties:
            out["breaking"].append("relation %s is gone: a graph using it no longer builds" % name)
            continue
        for key in ("domain", "range"):
            if isinstance(old_properties[name], dict) and isinstance(new_properties[name], dict) and old_properties[name].get(key) != new_properties[name].get(key):
                out["breaking"].append("relation %s changed its %s, from %s to %s: an edge a graph holds may no longer fit"
                                       % (name, key, old_properties[name].get(key), new_properties[name].get(key)))
    for name in sorted(flat_old):
        if name not in flat_new:
            out["breaking"].append("attribute %s is gone: a graph holding it no longer builds" % name)
            continue
        old, new = flat_old[name], flat_new[name]
        if isinstance(old, dict) and isinstance(new, dict):
            if old.get("type") != new.get("type"):
                out["breaking"].append("attribute %s changed its type, from %s to %s" % (name, old.get("type"), new.get("type")))
            if new.get("required") and not old.get("required"):
                out["breaking"].append("attribute %s is now required: a fact without it no longer passes" % name)
    if new_config.get("strict_domains") and not old_config.get("strict_domains"):
        out["breaking"].append("strict_domains is now on: an edge outside its relation's domain no longer passes")
    return out


def render_changes(found):
    """The term-level diff, for a pull request."""
    if not any(found.values()):
        return "**pack diff**: No term changed."
    lines = ["**pack diff**: what this changes, term by term."]
    for key, label in (("added", "Added"), ("changed", "Changed"), ("removed", "Removed")):
        if found[key]:
            lines += ["", "**%s**" % label] + ["- %s" % item for item in found[key]]
    if found["breaking"]:
        lines += ["", "**Breaking**: what would stop a graph already on this pack."] + ["- %s" % item for item in found["breaking"]]
    return "\n".join(lines)
