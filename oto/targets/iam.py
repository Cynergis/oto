# -*- coding: utf-8 -*-
"""Stage, optional. The generated system's IAM: the platform's bindings derived from the active rules
of the access policy through the roles each principal holds, with the generated controls as a
proposal, versioned, hashed and signed like the policy bundle (roadmap E7, ADR-0005).

Runs when the vocabulary declares `PolicyRule` and writes `build/iam/`: `bindings.json`, `gcp.json`,
`controls.proposal.json`, `iam-bindings.md`, `manifest.json` (see oto/iam.py). Signed with the key
`policy.sign_with` names, as the policy bundle is; the provider is `policy.provider` (gcp). The
controls are not applied here: a build never writes the graph. `oto policy iam --apply` takes them
through the gates.
"""
import json
import os
import shutil

from .. import audit as _audit, iam as _iam, policy as _policy
from ..project import ProjectError


def run(project):
    layout = project.layout
    out = layout.iam
    with open(project.ontology_config_path, encoding="utf-8") as f:
        vocabulary = json.load(f)
    classes = vocabulary.get("classes") or {}
    if _policy.CLASS not in classes:
        print("iam: the vocabulary declares no %s; no bindings to derive" % _policy.CLASS)
        if os.path.isdir(out):
            shutil.rmtree(out)
        return
    graph = _iam.built_graph(project)                     # with the derived attributes: pii on a table whose column is personal data
    version = {"build_seq": int(project.build_seq()), "graph": _audit.graph_version(project), "ontology": vocabulary.get("ontology_version")}
    key_env = _policy.settings(project)["sign_with"]
    provider = _iam.settings(project)["provider"]
    if os.path.isdir(out):
        shutil.rmtree(out)
    try:
        manifest = _iam.bundle(graph, out, version=version, key_env=key_env, classes=classes, provider=provider)
    except (_iam.IamError, _policy.PolicyError) as exc:
        raise ProjectError(str(exc))
    print("iam: %d binding(s) on %d resource(s) for %d member(s) into %s (%s), %d control(s) proposed, %s" % (
        manifest["bindings"], manifest["resources"], manifest["members"], os.path.relpath(out, os.path.dirname(project.src)), manifest["provider"],
        manifest["controls"], ("signed with %s" % key_env) if key_env else "unsigned"))
    if _iam.CONTROL not in classes:
        print("  no Control in the vocabulary: no controls proposed (compose the architecture pack)")
    for problem in manifest["problems"]:
        print("  not bound: %s" % problem)
