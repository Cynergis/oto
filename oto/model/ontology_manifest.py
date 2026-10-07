# -*- coding: utf-8 -*-
"""The ontology manifest: `manifest.json` beside the vocabulary.

The manifest gives an ontology its name, its namespace and its release number, and says what it
composes on top of (`extends`), what it carries, and which engine contract it was written for.
A directory without one can still be read (the defaults are its name, release 1, extends
nothing), and is reported as not usable: an ontology states its namespace.

    {
      "name": "insurance-claims",
      "release": 3,
      "domain": "insurance",
      "summary": "Auto and property claims: parties, policies, losses, adjusters, reserves.",
      "extends": ["oto-core", "insurance-party"],
      "namespace": "https://example.org/ont/insurance-claims#",
      "engine": ">=0.1",
      "carries": ["vocabulary", "rationale", "rules", "questions", "sample", "lexicon", "interview", "guide", "gold"],
      "maintainer": "Claims knowledge team <claims-kb@example.com>",
      "changelog": [{"release": 3, "at": "2026-10-02", "note": "Reserve became a class."}]
    }

`namespace` is the IRI the ontology's own terms live under in every RDF export, in every project
that uses it (model/namespaces.py). It is required: an ontology without one is not usable. Once
published it is an identifier others hold: do not change it.
`domain` is the category the ontology belongs to, one lowercase slug, for grouping a listing or a
catalog; optional. `product_type` says the ontology is what a product of that kind must specify
(`product-report` declares `report`): one lowercase slug, optional; a registry lists its product
types so a studio's first question, "which kind of product?", is read from the marketplace. `release` is an integer that rises on every published change; whether a change breaks a project
is computed by a diff, never declared here. The vocabulary's own `ontology_version` inside
`ontology.config.json` rises only on a breaking change and stays independent: two numbers, two
questions (which publication is this; does the schema still fit the data).
"""
import json
import os
import re

from .. import __version__
from . import namespaces as _namespaces

MANIFEST_NAME = "manifest.json"
NAME_OK = re.compile(r"^[a-z][a-z0-9-]*$")
DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: What an ontology may carry, and the file or directory that proves it.
CARRIES = {
    "vocabulary": "ontology.config.json",
    "rationale": "ontology.rationale.json",
    "rules": "rules.json",
    "questions": "questions.json",
    "briefs": "briefs.json",
    "sample": "sample.graph.json",
    "readme": "README.md",
    "lexicon": "lexicon.json",
    "interview": "interview.md",
    "guide": "guide.md",
    "actions": "actions",
    "gold": os.path.join("gold", "patterns.jsonl"),
}
FIELDS = ("name", "release", "domain", "product_type", "summary", "extends", "namespace", "engine", "carries", "maintainer", "changelog")
#: The domains the engine has seen: the category an ontology or a pack belongs to. A new one is
#: allowed and noted, never refused; add it here once it is deliberate. Never the same word as a
#: relation's domain and range, which live inside the vocabulary.
DOMAINS = ("insurance", "organization", "product", "professional-services", "reporting", "software")
#: Written by `oto ontology add`, never by an author: where a fetched ontology came from.
PROVENANCE = ("registry", "source", "ref", "path", "commit", "fetched_at")


def path_for(directory):
    return os.path.join(directory, MANIFEST_NAME)


def detect_carries(directory):
    """What the directory actually holds, in the order CARRIES lists them."""
    return [key for key, rel in CARRIES.items() if os.path.exists(os.path.join(directory, rel))]


def read(directory, fallback_summary=""):
    """The manifest with defaults filled in. Never raises on a missing file; a malformed one is
    reported by `problems`, which reads the file again."""
    manifest = {"name": os.path.basename(os.path.normpath(directory)), "release": 1, "summary": fallback_summary,
                "extends": [], "engine": None, "carries": detect_carries(directory), "maintainer": "",
                "changelog": [], "_declared": False}
    path = path_for(directory)
    if not os.path.exists(path):
        return manifest
    try:
        with open(path, encoding="utf-8") as f:
            declared = json.load(f)
    except (OSError, ValueError):
        return manifest
    if not isinstance(declared, dict):
        return manifest
    for key in FIELDS + PROVENANCE:
        if key in declared and declared[key] not in (None, ""):
            manifest[key] = declared[key]
    manifest["_declared"] = True
    return manifest


def write(directory, manifest):
    payload = {key: manifest[key] for key in FIELDS + PROVENANCE if manifest.get(key) not in (None, "", [])}
    payload["_about"] = ("The ontology's identity: its release rises on every published change, `extends` "
                         "names what it composes on top of, `carries` what the directory holds.")
    with open(path_for(directory), "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path_for(directory)


# ---- the engine contract ----

def _version_tuple(text):
    parts = []
    for piece in str(text).split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group(0)))
    return tuple(parts)


def satisfies(spec, version=__version__):
    """True when this engine meets a `>=x.y` spec. Returns None for a spec it cannot read."""
    m = re.match(r"^\s*>=\s*(\d+(?:\.\d+)*)\s*$", str(spec))
    if not m:
        return None
    want = _version_tuple(m.group(1))
    have = _version_tuple(version)
    have = have + (0,) * (len(want) - len(have))
    return have[:len(want)] >= want


# ---- the domain ----

def domain_problems(domain, where="manifest.json"):
    """A domain is optional; when given it is one lowercase slug."""
    if domain is None:
        return []
    if not isinstance(domain, str) or not NAME_OK.match(domain):
        return ["%s domain %r must be one lowercase slug (letters, digits, hyphens)" % (where, domain)]
    return []


def product_type_problems(product_type, where="manifest.json"):
    """A product type is optional; when given it is one lowercase slug."""
    if product_type is None:
        return []
    if not isinstance(product_type, str) or not NAME_OK.match(product_type):
        return ["%s product_type %r must be one lowercase slug (letters, digits, hyphens)" % (where, product_type)]
    return []


def domain_note(domain):
    """An advisory line when the domain is one the engine has not seen, or None."""
    if not domain or not isinstance(domain, str) or not NAME_OK.match(domain) or domain in DOMAINS:
        return None
    return ("domain %r is new to this engine (known: %s); fine if deliberate, and worth adding to the engine's list"
            % (domain, ", ".join(DOMAINS)))


# ---- what is wrong with a manifest ----

def problems(directory):
    """Problems with the manifest file itself and with what it claims about the directory."""
    out = []
    path = path_for(directory)
    if not os.path.exists(path):
        return ["no manifest.json: an ontology states its name and its namespace there"]
    try:
        with open(path, encoding="utf-8") as f:
            declared = json.load(f)
    except ValueError as exc:
        return ["manifest.json is not valid JSON: %s" % exc]
    except OSError as exc:
        return ["manifest.json cannot be read: %s" % exc]
    if not isinstance(declared, dict):
        return ["manifest.json must be a JSON object"]

    name = declared.get("name")
    if name is not None and (not isinstance(name, str) or not NAME_OK.match(name)):
        out.append("manifest.json name %r must be lowercase letters, digits and hyphens" % (name,))
    if name and name != os.path.basename(os.path.normpath(directory)):
        out.append("manifest.json names %r but the directory is %r" % (name, os.path.basename(os.path.normpath(directory))))
    release = declared.get("release", 1)
    if not isinstance(release, int) or isinstance(release, bool) or release < 1:
        out.append("manifest.json release must be a positive integer, not %r" % (release,))
    extends = declared.get("extends", [])
    if not isinstance(extends, list) or not all(isinstance(x, str) and x for x in extends):
        out.append("manifest.json extends must be a list of ontology names")
    elif name in extends:
        out.append("manifest.json: an ontology cannot extend itself")
    engine = declared.get("engine")
    if engine is not None:
        ok = satisfies(engine)
        if ok is None:
            out.append("manifest.json engine %r is not a spec this engine reads (use \">=x.y\")" % (engine,))
        elif not ok:
            out.append("manifest.json needs engine %s and this engine is %s: upgrade the engine, "
                       "or use an ontology written for it" % (engine, __version__))
    carries = declared.get("carries")
    if carries is not None:
        if not isinstance(carries, list) or not all(isinstance(x, str) for x in carries):
            out.append("manifest.json carries must be a list of names")
        else:
            unknown = sorted(set(carries) - set(CARRIES))
            if unknown:
                out.append("manifest.json carries unknown item(s): %s (known: %s)"
                           % (", ".join(unknown), ", ".join(CARRIES)))
            found = set(detect_carries(directory))
            for item in carries:
                if item in CARRIES and item not in found:
                    out.append("manifest.json says it carries %r but %s is not there" % (item, CARRIES[item]))
            for item in sorted(found - set(carries)):
                if item != "readme":
                    out.append("the directory holds %s but manifest.json does not list %r in carries" % (CARRIES[item], item))
    out += domain_problems(declared.get("domain"), "manifest.json")
    out += product_type_problems(declared.get("product_type"), "manifest.json")
    if declared.get("namespace") in (None, ""):
        out.append("manifest.json states no namespace: the IRI the ontology's terms live under, "
                   "for example https://example.org/ont/%s#" % (name or "name"))
    else:
        problem = _namespaces.iri_problem(declared["namespace"], "manifest.json namespace")
        if problem:
            out.append(problem)
    changelog = declared.get("changelog", [])
    if not isinstance(changelog, list):
        out.append("manifest.json changelog must be a list")
    else:
        for index, entry in enumerate(changelog, 1):
            if not isinstance(entry, dict) or not isinstance(entry.get("release"), int) \
                    or not isinstance(entry.get("note"), str) or not entry.get("note", "").strip():
                out.append("manifest.json changelog entry %d needs an integer release and a note" % index)
            elif entry.get("at") and not DATE_OK.match(str(entry["at"])):
                out.append("manifest.json changelog entry %d: `at` must be YYYY-MM-DD" % index)
            elif isinstance(release, int) and entry.get("release", 0) > release:
                out.append("manifest.json changelog entry %d is for release %d, newer than the ontology's %d"
                           % (index, entry["release"], release))
    return out
