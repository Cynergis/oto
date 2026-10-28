# -*- coding: utf-8 -*-
"""Stage, optional. The policy bundle: the active rules of the access policy compiled into Cedar and
JSON, versioned, hashed and signed (roadmap E2, ADR-0004).

Runs when the vocabulary declares `PolicyRule` (the policy pack) and writes `build/policy/`:
`policies.cedar`, `policies.json`, `manifest.json` (see oto/policy.py). A project whose vocabulary
has no PolicyRule skips the stage with a note. The project may name the environment variable that
holds the signing key, `"policy": {"sign_with": "OTO_POLICY_KEY"}` in project.config.json; a build
without the key then fails, since a bundle that says it is signed and is not would be worse than none.
"""
import json
import os
import shutil

from ... import audit as _audit
from ...project import ProjectError
from .. import policy as _policy


def settings(project):
    return _policy.settings(project)


def run(project):
    layout = project.layout
    out = layout.policy
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    classes = vocabulary.get("classes") or {}
    if _policy.CLASS not in classes:
        print("policy: the vocabulary declares no %s; nothing to compile" % _policy.CLASS)
        if os.path.isdir(out):
            shutil.rmtree(out)
        return
    with open(os.path.join(layout.graph, "knowledge-graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    version = {"build_seq": int(project.build_seq()), "graph": _audit.graph_version(project), "ontology": vocabulary.get("ontology_version")}
    key_env = settings(project)["sign_with"]
    if os.path.isdir(out):
        shutil.rmtree(out)
    try:
        manifest = _policy.bundle(graph, out, version=version, key_env=key_env, classes=classes)
    except _policy.PolicyError as exc:
        raise ProjectError(str(exc))
    print("policy: %d rule(s) compiled into %s (cedar + json), %s" % (
        manifest["rules"], os.path.relpath(out, os.path.dirname(project.src)), ("signed with %s" % key_env) if key_env else "unsigned"))
    for problem in manifest["problems"]:
        print("  left out: %s" % problem)
