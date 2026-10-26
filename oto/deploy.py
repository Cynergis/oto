# -*- coding: utf-8 -*-
"""Deploy: where a graph goes, and how a build moves there.

`oto.deploy.json` beside the project says it once: the repository the graph is compiled from, the
graph's name, the store it is published to (connector) and how to reach it (a method and the *name*
of the variable that holds the secret, never the secret), the query repository to publish to, and
the environments in the order a build moves through them, each with who may approve the step.

    {"repo": "cynergis/client-kg", "graph": "product-kg", "connector": "neo4j",
     "connection": {"endpoint": "bolt://graph.dev.client.internal", "auth": "basic", "secret": "NEO4J_PASSWORD"},
     "publish": {"to": "https://github.com/cynergis/client-kg-store", "require_pr": true, "site": false},
     "environments": [{"name": "dev", "approvers": []},
                      {"name": "test", "approvers": ["kg-owners"]},
                      {"name": "prod", "approvers": ["kg-owners", "data-governance"]}],
     "promotion": "same-commit"}

The config validates before anything publishes (`oto deploy check`). It is JSON, like every other
file of a project, because the engine reads it with the standard library alone.

An environment is a branch of the query repository: `dev` holds what was published to dev, `test`
what was promoted to test. A build is published to the first environment; every later one is
reached by **promotion**: the store the previous environment holds is copied forward, byte for
byte, after its hash and its commit are checked, and never rebuilt. Each step appends one line to
`PROMOTIONS.jsonl` on the branch (environment, commit, hash, who approved and how, when, from
where), so the record travels with the store and a reader can ask what is in prod, from which
commit, approved by whom. In CI the approver is GitHub's required reviewer on the environment; on a
machine it is the person named with `--by`; the record says which.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile

from .project import ProjectError

NAME = "oto.deploy.json"
RECORD = "PROMOTIONS.jsonl"
CONNECTORS = ("sqlite", "neo4j")
AUTH = ("basic", "oidc", "token", "workload-identity", "file", "env", "adc", "service-account")
KEYS = ("repo", "graph", "connector", "connection", "publish", "environments", "promotion", "overlay")
CONNECTION_KEYS = ("endpoint", "auth", "secret", "database", "note")
OVERLAY_KEYS = ("connector", "connection", "native_read", "schema", "region")
PROMOTION = "same-commit"
ENV_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
ENV_VAR = re.compile(r"^[A-Z][A-Z0-9_]*$")


# ---- the config ----

def path(project):
    return os.path.join(project.data, NAME)


def exists(project):
    return os.path.exists(path(project))


def load(project):
    """The config as written, or a ProjectError saying there is none or it does not read."""
    if not exists(project):
        raise ProjectError("no %s in the project: `oto deploy init --repo <owner/name> --to <query repository>` "
                           "writes one" % NAME)
    try:
        with open(path(project), encoding="utf-8") as f:
            return json.load(f)
    except ValueError as exc:
        raise ProjectError("%s is not valid JSON: %s" % (NAME, exc))


def problems(config):
    """What is wrong with a config, in words. [] when it validates."""
    from .validate import privacy as _privacy
    if not isinstance(config, dict):
        return ["the config must be a JSON object"]
    out = []
    unknown = sorted(set(config) - set(KEYS) - {"_about"})
    if unknown:
        out.append("unknown key(s) %s (it takes %s)" % (", ".join(unknown), ", ".join(KEYS)))
    for key in ("repo", "graph"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            out.append("`%s` is required: %s" % (key, "the repository the graph is compiled from, owner/name"
                                                 if key == "repo" else "the graph's name in the store"))
    connector = config.get("connector")
    if connector not in CONNECTORS:
        out.append("connector %r is not one of %s" % (connector, ", ".join(CONNECTORS)))
    connection = config.get("connection")
    if connector == "neo4j" and not isinstance(connection, dict):
        out.append("`connection` is required for neo4j: endpoint, auth and the secret's variable name")
    if connection is not None:
        out += _connection_problems(connection, "connection")
    overlay = config.get("overlay")
    if overlay is not None:
        out += _overlay_problems(overlay)
    publish = config.get("publish")
    if not isinstance(publish, dict) or not isinstance(publish.get("to"), str) or not publish["to"]:
        out.append("`publish.to` names the query repository the store is published to")
    elif any(k not in ("to", "require_pr", "site") for k in publish):
        out.append("unknown key(s) in `publish`: %s" % ", ".join(sorted(set(publish) - {"to", "require_pr", "site"})))
    envs = config.get("environments")
    if not isinstance(envs, list) or not envs:
        out.append("`environments` needs at least one environment, in the order a build moves through them")
    else:
        seen = set()
        for entry in envs:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                out.append("each environment is {\"name\": ..., \"approvers\": [...]}")
                continue
            if not ENV_NAME.match(entry["name"]):
                out.append("environment name %r must be a lowercase slug (dev, test, prod)" % entry["name"])
            if entry["name"] in seen:
                out.append("environment %r is declared twice" % entry["name"])
            seen.add(entry["name"])
            approvers = entry.get("approvers", [])
            if not (isinstance(approvers, list) and all(isinstance(a, str) and a for a in approvers)):
                out.append("`approvers` of %s must be a list of team or person names" % entry["name"])
    if config.get("promotion", PROMOTION) != PROMOTION:
        out.append("`promotion` must be %r: the same build moves through the environments, never a rebuild" % PROMOTION)
    for kind in sorted({f.kind for f in _privacy.blocking(_privacy.scan(json.dumps(config, ensure_ascii=False)))}):
        out.append("%s found in the config: a secret never goes in the file; name the environment variable that holds it" % kind)
    return out


def _connection_problems(connection, where):
    out = []
    if not isinstance(connection, dict):
        return ["`%s` must be an object" % where]
    unknown = sorted(set(connection) - set(CONNECTION_KEYS))
    if unknown:
        out.append("unknown key(s) in `%s`: %s" % (where, ", ".join(unknown)))
    endpoint = connection.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        out.append("`%s.endpoint` is required" % where)
    elif "://" in endpoint:
        import urllib.parse
        try:
            if urllib.parse.urlsplit(endpoint).password:
                out.append("a password in `%s.endpoint`: a secret never goes in the file; name the environment variable that holds it in `secret`" % where)
        except ValueError:
            out.append("`%s.endpoint` is not a URL that reads" % where)
    if connection.get("auth") not in AUTH:
        out.append("`%s.auth` %r is not one of %s" % (where, connection.get("auth"), ", ".join(AUTH)))
    secret = connection.get("secret")
    if secret is not None and not (isinstance(secret, str) and ENV_VAR.match(secret)):
        out.append("`%s.secret` must be the name of an environment variable (NEO4J_PASSWORD), never a value" % where)
    return out


def overlay_connectors():
    """The connectors whose manifest declares `overlay`."""
    from . import connectors as _connectors
    return [n for n in _connectors.available() if "overlay" in (_connectors.get(n).MANIFEST.get("modes") or [])]


def _overlay_problems(overlay):
    """The `overlay` section: an overlay connector, its connection, and whether a native read is allowed."""
    if not isinstance(overlay, dict):
        return ["`overlay` must be an object: connector, connection, native_read"]
    out = []
    unknown = sorted(set(overlay) - set(OVERLAY_KEYS))
    if unknown:
        out.append("unknown key(s) in `overlay`: %s (it takes %s)" % (", ".join(unknown), ", ".join(OVERLAY_KEYS)))
    name = overlay.get("connector")
    if name not in overlay_connectors():
        out.append("`overlay.connector` %r is not an overlay connector; one of %s" % (name, ", ".join(overlay_connectors())))
    if "native_read" in overlay and not isinstance(overlay["native_read"], bool):
        out.append("`overlay.native_read` must be true or false: whether the served kg_read may run a native read")
    if overlay.get("connection") is not None:
        out += _connection_problems(overlay["connection"], "overlay.connection")
    elif name in ("postgres", "bigquery"):
        out.append("`overlay.connection` is required for %s: the endpoint, and the secret's variable name when one is needed" % name)
    for key in ("schema", "region"):
        if key in overlay and not (isinstance(overlay[key], str) and overlay[key]):
            out.append("`overlay.%s` must be a non-empty string" % key)
    return out


def native_read_allowed(config):
    """Whether the served kg_read may run: the overlay section says so, in so many words."""
    overlay = (config or {}).get("overlay") or {}
    return isinstance(overlay, dict) and overlay.get("native_read") is True


def chain(config):
    """The environments in order."""
    return [e["name"] for e in (config or {}).get("environments") or [] if isinstance(e, dict) and e.get("name")]


def approvers(config, environment):
    for entry in (config or {}).get("environments") or []:
        if entry.get("name") == environment:
            return list(entry.get("approvers") or [])
    return []


def previous(config, environment):
    """The environment a build is promoted from into `environment`; None for the first."""
    names = chain(config)
    if environment not in names:
        return None
    index = names.index(environment)
    return names[index - 1] if index else None


def starter(repo, to, graph, connector="sqlite"):
    """A config to start from: three environments, the owners approving test and prod."""
    config = {"_about": "Where this graph goes (oto deploy check validates it). Secrets are named, never written: "
                        "`connection.secret` is an environment variable's name.",
              "repo": repo, "graph": graph, "connector": connector,
              "publish": {"to": to, "require_pr": True, "site": False},
              "environments": [{"name": "dev", "approvers": []},
                               {"name": "test", "approvers": ["kg-owners"]},
                               {"name": "prod", "approvers": ["kg-owners", "data-governance"]}],
              "promotion": PROMOTION}
    if connector == "neo4j":
        config["connection"] = {"endpoint": "bolt://localhost:7687", "auth": "basic", "secret": "NEO4J_PASSWORD"}
    return config


def write(project, config):
    with open(path(project), "w", encoding="utf-8", newline="\n") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


def loaded_and_valid(project):
    """The config, or a ProjectError naming what is wrong with it."""
    config = load(project)
    found = problems(config)
    if found:
        raise ProjectError("%s does not validate:\n  - %s" % (NAME, "\n  - ".join(found)))
    return config


# ---- the record and promotion ----

def _sha256(file_path):
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def read_record(directory):
    """The promotion record a checkout carries, oldest first."""
    target = os.path.join(directory, RECORD)
    if not os.path.exists(target):
        return []
    with open(target, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_record(directory, entry):
    with open(os.path.join(directory, RECORD), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def record_entry(environment, manifest, by=None, kind=None, source_environment=None):
    return {"environment": environment, "at": _now(), "source": manifest.get("source") or "",
            "sha256": manifest.get("sha256"), "build_seq": manifest.get("build_seq"),
            "approved_by": by, "approver_kind": kind if by else None, "from": source_environment}


def promote(project, environment, commit, by=None, kind="person", token=None):
    """Copy the store the previous environment holds into `environment`, after checking it is the
    build of `commit` and its hash is intact. Returns the record entry appended."""
    from . import gitx as _gitx, publish as _publish
    config = loaded_and_valid(project)
    names = chain(config)
    if environment not in names:
        raise ProjectError("%r is not an environment of %s: %s" % (environment, NAME, " -> ".join(names)))
    source = previous(config, environment)
    if source is None:
        raise ProjectError("%s is the first environment: a build is published to it (oto publish --to %s), nothing is "
                           "promoted into it" % (environment, environment))
    if approvers(config, environment) and not by:
        raise ProjectError("promotion to %s needs an approver (%s): --by <who approved>; in CI the environment's "
                           "reviewer" % (environment, ", ".join(approvers(config, environment))))
    repo = config["publish"]["to"]
    token = token if token is not None else os.environ.get(_publish.TOKEN_ENV)
    url = _gitx.with_token(repo, token)
    if not _gitx.has_ref(repo, source, token):
        raise ProjectError("%s holds nothing yet; %s is reached from %s, not around it: publish or promote to %s first"
                           % (source, environment, source, source))
    held = tempfile.mkdtemp(prefix="oto-promote-src-")
    work = tempfile.mkdtemp(prefix="oto-promote-")
    try:
        _gitx.run(["clone", "--quiet", "--depth", "1", "--branch", source, url, held])
        manifest = _publish.read_manifest(held)
        if not manifest:
            raise ProjectError("%s holds no %s" % (source, _publish.MANIFEST_NAME))
        store_name = project.identity()["db_name"]
        store = os.path.join(held, store_name)
        if not os.path.exists(store):
            raise ProjectError("%s holds no store %s" % (source, store_name))
        if _sha256(store) != manifest.get("sha256"):
            raise ProjectError("the store %s holds does not match its manifest (sha256 %s... vs %s...): refusing to "
                               "promote a store that was changed after it was published"
                               % (source, _sha256(store)[:12], str(manifest.get("sha256"))[:12]))
        source_commit = manifest.get("source") or ""
        if not (source_commit == commit or source_commit.endswith("@" + commit) or source_commit.endswith(commit)):
            raise ProjectError("%s holds %s, not %s: promotion moves the same commit, never a rebuild"
                               % (source, source_commit or "a store with no recorded commit", commit))
        if _gitx.has_ref(repo, environment, token):
            _gitx.run(["clone", "--quiet", "--depth", "1", "--branch", environment, url, work])
        else:
            _gitx.run(["init", "--quiet", "-b", environment, work])
        for name in os.listdir(held):
            if name == ".git":
                continue
            target = os.path.join(work, name)
            if os.path.isdir(os.path.join(held, name)):
                if os.path.isdir(target):
                    shutil.rmtree(target)
                shutil.copytree(os.path.join(held, name), target)
            else:
                shutil.copyfile(os.path.join(held, name), target)
        promoted = dict(manifest, environment=environment, promoted_at=_now(), promoted_from=source)
        with open(os.path.join(work, _publish.MANIFEST_NAME), "w", encoding="utf-8", newline="\n") as f:
            json.dump(promoted, f, indent=2)
            f.write("\n")
        entry = record_entry(environment, promoted, by=by, kind=kind, source_environment=source)
        append_record(work, entry)
        _gitx.run(["add", "-A"], cwd=work)
        _gitx.run(["-c", "user.name=oto publish", "-c", "user.email=oto-publish@localhost", "commit", "--quiet",
                   "-m", "promote %s -> %s: %s" % (source, environment, source_commit)], cwd=work)
        _gitx.run(["push", "--quiet", url, "HEAD:%s" % environment], cwd=work)
        from . import audit as _audit
        _audit.append(project, "promote", by, [], "promoted",
                      detail="%s -> %s: %s, sha256 %s%s" % (source, environment, source_commit, str(promoted.get("sha256"))[:12],
                                                          (", approved as %s" % kind) if kind else ""))
        return entry
    finally:
        shutil.rmtree(held, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def status(project, token=None):
    """{environment: the last record it holds, or None}: what is where, read from the query repository."""
    from . import gitx as _gitx, publish as _publish
    config = loaded_and_valid(project)
    repo = config["publish"]["to"]
    token = token if token is not None else os.environ.get(_publish.TOKEN_ENV)
    out = {}
    for name in chain(config):
        if not _gitx.has_ref(repo, name, token):
            out[name] = None
            continue
        held = tempfile.mkdtemp(prefix="oto-deploy-status-")
        try:
            _gitx.run(["clone", "--quiet", "--depth", "1", "--branch", name, _gitx.with_token(repo, token), held])
            record = read_record(held)
            out[name] = record[-1] if record else None
        finally:
            shutil.rmtree(held, ignore_errors=True)
    return out
