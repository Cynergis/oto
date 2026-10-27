# -*- coding: utf-8 -*-
"""`oto policy`: the access policy compiled into a bundle (roadmap E2) and the snapshot an agent
runs under (E3). compile writes the bundle from the live graph; snapshot writes the signed
intersection of what an agent and a principal may do; verify checks a bundle or a snapshot against
its hash and signature; list reads every rule in words; denials turns a guard's refusals into audit
records."""
import json
import os
import sys

from ._common import project_arguments, resolve as _resolve


def _vocabulary(project):
    with open(project.ontology_config_path, encoding="utf-8") as f:
        return json.load(f)


def cmd_policy(args):
    from .. import audit as _audit, policy as _policy
    from ..curate import session as _session
    from ..targets import policy as _stage
    project = _resolve(args)
    vocabulary = _vocabulary(project)
    classes = vocabulary.get("classes") or {}
    if _policy.CLASS not in classes:
        print("oto: the vocabulary declares no %s: the policy pack is not part of this project (oto init --ontology policy, or oto ontology import --from policy)"
              % _policy.CLASS, file=sys.stderr)
        return 1
    if args.policy_command == "compile":
        out = args.out or project.layout.policy
        key_env = args.sign_with or _stage.settings(project)["sign_with"]
        try:
            seq = int(project.build_seq())
        except Exception:
            seq = 0
        version = {"build_seq": seq, "graph": _audit.graph_version(project), "ontology": vocabulary.get("ontology_version")}
        try:
            manifest = _policy.bundle(_session.live(project), out, version=version, at=args.at, key_env=key_env, classes=classes)
        except _policy.PolicyError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: %d rule(s) compiled (cedar + json), %s" % (out, manifest["rules"], ("signed with %s" % key_env) if key_env else "unsigned"))
        for problem in manifest["problems"]:
            print("  left out: %s" % problem)
        return 0
    if args.policy_command == "snapshot":
        if not args.agent or not args.principal:
            print("oto: snapshot takes --agent <agent id> and --principal <principal id>", file=sys.stderr)
            return 1
        out = args.out or _policy.SNAPSHOT_NAME
        key_env = args.sign_with or _stage.settings(project)["sign_with"]
        try:
            seq = int(project.build_seq())
        except Exception:
            seq = 0
        version = {"build_seq": seq, "graph": _audit.graph_version(project), "ontology": vocabulary.get("ontology_version")}
        ttl = args.ttl if args.ttl is not None else _policy.settings(project)["ttl_hours"]
        try:
            snap = _policy.write_snapshot(_session.live(project), args.agent, args.principal, out, at=args.at, version=version, key_env=key_env,
                                          classes=classes, ttl_hours=ttl)
        except _policy.PolicyError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%s: %s running for %s: %d permit(s), %d forbid(s), writes under %s, denied %s, expires %s, %s" % (
            out, snap["agent"]["id"], snap["principal"]["id"], len(snap["permits"]), len(snap["forbids"]),
            ", ".join(snap["scopes"]["write"]) or "nothing", ", ".join(snap["scopes"]["denied"]) or "nothing", snap["expires_at"],
            ("signed with %s" % key_env) if key_env else "unsigned"))
        return 0
    if args.policy_command == "denials":
        if not args.events:
            print("oto: denials takes --events <events.jsonl>, what a guard writes beside the snapshot", file=sys.stderr)
            return 1
        try:
            counts = _policy.denials(project, args.events)
        except _policy.PolicyError as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        print("%d denial(s) recorded as audit records, %d already there, %d other event(s) skipped, of %d" % (
            counts["recorded"], counts["already"], counts["skipped"], counts["events"] + counts["skipped"]))
        return 0
    if args.policy_command == "verify" and args.bundle and os.path.isfile(args.bundle):
        key_env = args.sign_with or _stage.settings(project)["sign_with"]
        problems = _policy.verify_snapshot(args.bundle, key_env=key_env)
        if problems:
            print("oto: %s does not hold:" % args.bundle, file=sys.stderr)
            for p in problems:
                print("  %s" % p, file=sys.stderr)
            return 1
        snap = _policy.read_snapshot(args.bundle)
        signature = snap.get("signature")
        print("%s holds: %s%s" % (args.bundle, _policy.describe_snapshot(snap),
                                  ("; the signature is not checked without the key (--sign-with %s)" % signature["key"]) if signature and not key_env else ""))
        return 0
    if args.policy_command == "verify":
        where = args.bundle or project.layout.policy
        key_env = args.sign_with or _stage.settings(project)["sign_with"]
        try:
            manifest = _policy.read_manifest(where)
        except (_policy.PolicyError, ValueError) as exc:
            print("oto: %s" % exc, file=sys.stderr)
            return 1
        problems = _policy.verify(where, key_env=key_env)
        if problems:
            print("oto: %s does not hold:" % where, file=sys.stderr)
            for p in problems:
                print("  %s" % p, file=sys.stderr)
            return 1
        note = ""
        if manifest.get("signature") and not key_env:
            note = "; the signature names the key in %s, not checked without it (--sign-with %s)" % (manifest["signature"]["key"], manifest["signature"]["key"])
        print("%s holds: %s%s" % (where, _policy.describe(manifest), note))
        return 0
    if args.policy_command == "list":
        graph = _session.live(project)
        nodes = [n for n in graph.get("nodes") or [] if (n.get("status") or "current") == "current"]
        by_id = {n["id"]: n for n in nodes}
        edges = {}
        for e in graph.get("edges") or []:
            if (e.get("status") or "current") == "current":
                edges.setdefault((e["from"], e["rel"]), []).append(e["to"])
        rules = [n for n in nodes if n.get("type") == _policy.CLASS]
        if not rules:
            print("no policy rules in the graph")
            return 0
        rules.sort(key=lambda n: (-int((n.get("attributes") or {}).get("priority") or 0), n["id"]))
        for n in rules:
            a = n.get("attributes") or {}
            who = ", ".join(by_id[t].get("label") or t for t in edges.get((n["id"], "for_role"), []) if t in by_id) or "(no role)"
            perms = [by_id[t] for t in edges.get((n["id"], "of_permission"), []) if t in by_id]
            what = ", ".join("%s %s%s" % ((p.get("attributes") or {}).get("action"), (p.get("attributes") or {}).get("resource_class"),
                                           (" where " + " and ".join((p.get("attributes") or {}).get("selector") or [])) if (p.get("attributes") or {}).get("selector") else "")
                             for p in perms) or "(no permission)"
            on = [by_id[t].get("label") or t for t in edges.get((n["id"], "singles_out"), []) if t in by_id]
            verb = "may not" if a.get("effect") == "forbid" else "may"
            print("  [%-7s] %-6s %4s  %s: %s %s %s%s" % (a.get("status") or _policy.DEFAULT_STATUS, a.get("effect"), a.get("priority") or 0,
                                                        n["id"], who, verb, what, (" on " + ", ".join(on)) if on else ""))
            if a.get("rationale"):
                print("           %s" % a["rationale"])
        return 0
    return 1


def register(sub):
    policy = sub.add_parser("policy", help="the access policy compiled into a bundle: compile, verify, list")
    policy.add_argument("policy_command", choices=["compile", "snapshot", "verify", "list", "denials"],
                        help="compile writes policies.cedar, policies.json and manifest.json from the active rules; snapshot writes the signed "
                             "intersection of what an agent and a principal may do (.factory/policy.json); verify checks a bundle directory or a "
                             "snapshot file against its hash and signature; list reads every rule in words; denials turns a guard's refusals into audit records")
    policy.add_argument("bundle", nargs="?", default=None, help="for verify: the bundle directory (default build/policy) or a snapshot file")
    policy.add_argument("--agent", default=None, help="for snapshot: the agent, agent.<id>")
    policy.add_argument("--principal", default=None, help="for snapshot: the principal it runs for, principal.<id>")
    policy.add_argument("--events", default=None, help="for denials: the events file a guard writes (.factory/events.jsonl)")
    policy.add_argument("--out", default=None, help="for compile: where to write the bundle (default build/policy); for snapshot: the file (default .factory/policy.json)")
    policy.add_argument("--at", default=None, help="for compile and snapshot: the date to record as generated (default: today)")
    policy.add_argument("--ttl", type=float, default=None, help="for snapshot: hours until it expires (default: project.config.json policy.ttl_hours, else 24)")
    policy.add_argument("--sign-with", dest="sign_with", default=None, metavar="ENV",
                        help="the environment variable holding the signing key (default: project.config.json policy.sign_with)")
    project_arguments(policy)
    policy.set_defaults(func=cmd_policy)
