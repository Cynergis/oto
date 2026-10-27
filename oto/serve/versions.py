# -*- coding: utf-8 -*-
"""The vocabulary's versions and what changed between two of them (roadmap D6). Two configs compare
through model/vocabulary.diff with the impact on the graph; the result renders as text (the shape
`oto ontology check` prints), as markdown (what the checks workflow posts on a pull request) or as
JSON. A config is read at a git ref with `git show`, so `oto ontology diff --from <ref>` and
/api/ontology/diff?from=&to= compare the working tree, or two refs, without checking anything out.

The versions model rides in the graph payload under `ontology.versions`: the current version, the
version last accepted (ontology.lock.json) and what changed since, and whether the project is in a
git repository so a ref can be compared live. The workbench's Versions page reads it, and asks the
diff route for a ref when served live.
"""
import json
import os
import subprocess

from .. import gitx
from ..model import vocabulary as _vocab
from ..project import ProjectError

CONFIG_NAME = "ontology.config.json"


def _summary(config):
    return {"version": int(config.get("ontology_version") or 0), "classes": len(config.get("classes") or {}),
            "relations": len(config.get("properties") or {}),
            "attributes": sum(len(v or {}) for v in (config.get("attributes") or {}).values())}


def compare(old, new, nodes=(), edges=(), labels=None):
    """Every change from `old` to `new` (config dicts), most severe first, with how many nodes or
    edges each breaking one touches."""
    before, after = _vocab.Vocabulary.from_config(old or {}), _vocab.Vocabulary.from_config(new or {})
    changes = _vocab.impact(_vocab.diff(before, after), list(nodes or []), list(edges or []), after)
    rows = [{"kind": c.kind, "severity": c.severity, "subject": c.subject, "detail": c.detail, "affected": c.affected} for c in changes]
    counts = {"changes": len(rows)}
    for severity in (_vocab.Change.BREAKING, _vocab.Change.ADDITIVE, _vocab.Change.COSMETIC):
        counts[severity] = sum(1 for r in rows if r["severity"] == severity)
    return {"from": _summary(old or {}), "to": _summary(new or {}), "labels": list(labels) if labels else None,
            "changes": rows, "counts": counts, "bump_needed": bool(counts["breaking"]) and after.version <= before.version}


def _labels(result):
    labels = result.get("labels") or ["the former vocabulary", "the current one"]
    return labels[0], labels[1]


def render(result, fmt="text"):
    """The comparison as text, markdown or JSON."""
    if fmt == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)
    a, b = _labels(result)
    n, breaking = result["counts"]["changes"], result["counts"]["breaking"]
    if fmt == "markdown":
        if not n:
            return "### Ontology: no change from %s to %s\n" % (a, b)
        L = ["### Ontology: %d change%s from %s to %s" % (n, "" if n == 1 else "s", a, b), "",
             "| Severity | Change | Subject | Detail |", "|---|---|---|---|"]
        for c in result["changes"]:
            touches = (" (touches %d)" % c["affected"]) if c["affected"] else ""
            L.append("| %s | %s | `%s` | %s%s |" % (c["severity"], c["kind"], c["subject"], c["detail"].replace("|", "\\|"), touches))
        if result["bump_needed"]:
            L += ["", "**%d breaking change%s with no version bump**: raise `ontology_version` in %s, then `oto ontology accept`."
                  % (breaking, "" if breaking == 1 else "s", CONFIG_NAME)]
        elif breaking:
            L += ["", "%d breaking change%s, acknowledged by the bump to version %d." % (breaking, "" if breaking == 1 else "s", result["to"]["version"])]
        return "\n".join(L) + "\n"
    if not n:
        return "ontology: no change from %s to %s (version %d, %d classes, %d relations)" % (
            a, b, result["to"]["version"], result["to"]["classes"], result["to"]["relations"])
    L = ["ontology: %d change(s) from %s to %s:" % (n, a, b)]
    for c in result["changes"]:
        touches = (" — touches %d" % c["affected"]) if c["affected"] else ""
        L.append("  [%-9s] %-28s %-24s %s%s" % (c["severity"], c["kind"], c["subject"], c["detail"], touches))
    if result["bump_needed"]:
        L.append("\n%d breaking change(s) with no version bump. Raise `ontology_version` in %s, then run `oto ontology accept`."
                 % (breaking, CONFIG_NAME))
    elif breaking:
        L.append("\n%d breaking change(s), acknowledged by the bump to version %d." % (breaking, result["to"]["version"]))
    return "\n".join(L)


def read_at(ref, name, cwd):
    """The JSON file `name` (relative to `cwd`, inside a git repository) as it was at `ref`."""
    text = gitx.run(["show", "%s:./%s" % (ref, name)], cwd=cwd)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ProjectError("%s at %s is not JSON: %s" % (name, ref, exc))


def in_git(directory):
    """True when `directory` sits inside a git work tree."""
    if not directory or not os.path.isdir(directory):
        return False
    try:
        out = subprocess.run(["git", "-C", directory, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and out.stdout.strip() == "true"


def diff_refs(from_ref, to_ref=None, cwd=None, name=CONFIG_NAME, nodes=(), edges=()):
    """The config at `from_ref` against the one at `to_ref`, or the working file when `to_ref` is None."""
    old = read_at(from_ref, name, cwd)
    if to_ref:
        new = read_at(to_ref, name, cwd)
    else:
        with open(os.path.join(cwd or ".", name), encoding="utf-8") as f:
            new = json.load(f)
    return compare(old, new, nodes, edges, labels=(from_ref, to_ref or "the working tree"))


def model(current, project_root, nodes=(), edges=()):
    """The versions as the payload carries them: current, accepted, what changed since, and whether a
    ref can be compared live."""
    out = {"current": int((current or {}).get("ontology_version") or 0), "accepted": None, "since_accepted": None, "git": False}
    if not project_root:
        return out
    out["git"] = in_git(project_root)
    path = os.path.join(project_root, _vocab.LOCK_NAME)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                locked = json.load(f)
        except (OSError, ValueError):
            return out
        out["accepted"] = int(locked.get("ontology_version") or 0)
        out["since_accepted"] = compare(locked, current, nodes, edges, labels=("version %d as accepted" % out["accepted"], "the working tree"))
    return out
