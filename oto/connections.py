# -*- coding: utf-8 -*-
"""Connections to graphs that live in Neo4j: what a person reads from, with no documents and no copy
(docs/plans/people-and-graphs.md, capability 3).

    oto graphs add <name> --uri <neo4j address> [--database D] [--slug S] [--label L] [--subject TEXT]
    oto graphs list
    oto graphs rm <name>

A folder holds any number of them. Each is `graphs/<name>/project.config.json`, the graph's address and
`serve.backend: neo4j`, with one entry in the folder's `.mcp.json`: an `oto serve` of its own, which maps
this graph's login (`<NAME>_NEO4J_USER`, `<NAME>_NEO4J_PASSWORD`) onto the fixed names the engine reads.
The files name those variables and hold no value: the login stays in the environment. `oto sandbox up`
passes each graph's variables into the sandbox it makes, and allows the graph's host for that sandbox
alone (`logins`).

One server per graph, because one process serves one graph. Each entry empties `NEO4J_URI` and
`NEO4J_AUTH`, which the engine also reads: neither may send a graph elsewhere or lend it another's login.
A variable that is not set gives an empty login, so that graph's server starts and says it cannot read,
and the other graphs' servers are not affected.
"""
import json
import os
import re
from urllib.parse import urlsplit

from .project import ProjectError

FOLDER = "graphs"
MCP_FILE = ".mcp.json"
CONFIG_FILE = "project.config.json"
BUILD = "build"
#: the addresses a Neo4j driver takes
SCHEMES = ("neo4j+s", "neo4j+ssc", "neo4j", "bolt+s", "bolt+ssc", "bolt")
BOLT_PORT = 7687
#: Aura's driver is routed from the instance's address to servers under this domain, whose names change
AURA_DOMAIN = "neo4j.io"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def server_name(name):
    return "%s-kg" % name


def variables(name):
    """The environment variables holding this graph's login: (user, password)."""
    stem = name.upper().replace("-", "_")
    return "%s_NEO4J_USER" % stem, "%s_NEO4J_PASSWORD" % stem


def rule(uri):
    """What a sandbox's network policy allows for this address, or None for an address with no host.
    On Aura, the whole domain on the Bolt port: the driver goes on to whichever server the routing table
    names (p-mt-...-0202.production-orch-0055.neo4j.io), and the name changes under a rule naming one."""
    try:
        parts = urlsplit(uri or "")
        host, port = parts.hostname, parts.port or BOLT_PORT
    except ValueError:
        return None
    if not host:
        return None
    if host == AURA_DOMAIN or host.endswith("." + AURA_DOMAIN):
        return "**.%s:%d" % (AURA_DOMAIN, port)
    return "%s:%d" % (host, port)


def _read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError) as exc:
        raise ProjectError("%s can't be read: %s. Fix or move it, then run this again; nothing was changed." % (path, exc))
    if not isinstance(found, dict):
        raise ProjectError("%s is not a JSON object. Fix or move it, then run this again; nothing was changed." % path)
    return found


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _folder(root, name):
    return os.path.join(root, FOLDER, name)


def _entry(name):
    """The server of one graph, as `.mcp.json` holds it. `${VAR:-}` is expanded by the host."""
    user, password = variables(name)
    return {"command": "oto", "args": ["serve", "--project", "%s/%s" % (FOLDER, name)],
            "env": {"NEO4J_USER": "${%s:-}" % user, "NEO4J_PASSWORD": "${%s:-}" % password, "NEO4J_URI": "", "NEO4J_AUTH": ""}}


def _check_address(uri):
    """A driver's address with a host and no login in it. The message never repeats the address: it may hold a password."""
    try:
        parts = urlsplit(uri or "")
        host = parts.hostname
        parts.port                                                     # raises on a port that isn't one
    except ValueError:
        raise ProjectError("the address is not one a Neo4j driver takes: it looks like neo4j+s://<id>.databases.neo4j.io")
    if parts.username or parts.password:
        raise ProjectError("the address holds a login, which never goes in a file: pass the address alone, and keep the login in the environment")
    if parts.scheme not in SCHEMES or not host:
        raise ProjectError("the address is not one a Neo4j driver takes (%s): it looks like neo4j+s://<id>.databases.neo4j.io" % ", ".join(SCHEMES))


def add(root, name, uri, database=None, slug=None, label=None, subject=None):
    """Write the connection. Returns {name, server, variables, already}. The same graph added again
    changes nothing; a different one under that name is refused."""
    root = os.path.abspath(os.path.expanduser(root))
    if not NAME.match(name or ""):
        raise ProjectError("a graph's name is lowercase letters, digits and single hyphens, not %r" % name)
    _check_address(uri)
    slug = slug or name
    if not SLUG.match(slug):
        raise ProjectError("a graph's slug is letters, digits, dots, dashes and underscores, not %r" % slug)
    user, password = variables(name)
    server = server_name(name)
    connection = {"uri": uri}
    if database:
        connection["database"] = database
    config = {"slug": slug, "name": label or name.replace("-", " ").title(), "server_name": server, "serve": {"backend": "neo4j"},
              "neo4j": connection, "login": {"user": user, "password": password}}
    if subject:
        config["description"] = subject
    found = {"name": name, "server": server, "variables": [user, password], "already": False}

    path = os.path.join(_folder(root, name), CONFIG_FILE)
    mcp_path = os.path.join(root, MCP_FILE)
    mcp = _read_json(mcp_path, {})
    existing = _read_json(path)
    if existing is not None:
        if existing != config:
            raise ProjectError("a graph named %s is already here, and differs: oto graphs rm %s first" % (name, name))
        found["already"] = True
    servers = mcp.setdefault("mcpServers", {})
    if server in servers and servers[server] != _entry(name):
        raise ProjectError("%s already names a server %s that is not this graph's: move it, or choose another name" % (mcp_path, server))
    servers[server] = _entry(name)
    _write_json(path, config)
    _write_json(mcp_path, mcp)
    return found


def _described(name, config):
    login = config.get("login") or {}
    default_user, default_password = variables(name)
    user, password = login.get("user") or default_user, login.get("password") or default_password
    neo4j = config.get("neo4j") or {}
    return {"name": name, "slug": config.get("slug"), "label": config.get("name"), "description": config.get("description"),
            "uri": neo4j.get("uri"), "database": neo4j.get("database"), "server": config.get("server_name") or server_name(name),
            "variables": [user, password], "rule": rule(neo4j.get("uri")),
            "login": bool(os.environ.get(user) and os.environ.get(password))}


def listed(root):
    """The connections in this folder, by name; each says whether its login is in this environment, never what it is."""
    base = os.path.join(root, FOLDER)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        config = _read_json(os.path.join(base, name, CONFIG_FILE))
        if config is not None:
            out.append(_described(name, config))
    return out


def is_connection(root):
    """A folder holding a graph's address and nothing of the graph: no vocabulary, served from Neo4j."""
    config = _read_json(os.path.join(root, CONFIG_FILE))
    return bool(config) and not os.path.exists(os.path.join(root, "ontology.config.json")) \
        and ((config.get("serve") or {}).get("backend") or "").lower() == "neo4j"


def is_folder(root):
    """A folder of connections rather than a project: it has connections and no project config of its own."""
    return not os.path.exists(os.path.join(root, CONFIG_FILE)) and bool(listed(root))


def logins(root):
    """What a sandbox needs to read this folder's graphs: each graph's server, the variables holding its
    login and the network rule for its host. A project of its own that serves from Neo4j reads the
    engine's fixed names."""
    if not os.path.isdir(root):
        return []
    out = []
    config = _read_json(os.path.join(root, CONFIG_FILE))
    if config and ((config.get("serve") or {}).get("backend") or "").lower() == "neo4j":
        uri = (config.get("neo4j") or {}).get("uri")
        if uri:
            slug = config.get("slug") or os.path.basename(root)
            out.append({"name": slug, "server": config.get("server_name") or server_name(slug), "uri": uri,
                        "variables": ["NEO4J_USER", "NEO4J_PASSWORD"], "rule": rule(uri)})
    for graph in listed(root):
        out.append({key: graph[key] for key in ("name", "server", "uri", "variables", "rule")})
    return out


def remove(root, name):
    """Take a connection out: its server and what `add` wrote. Returns {name, server, kept}:
    a file it did not write stays, and is named."""
    root = os.path.abspath(os.path.expanduser(root))
    folder = _folder(root, name)
    path = os.path.join(folder, CONFIG_FILE)
    if not NAME.match(name or "") or not os.path.exists(path):
        raise ProjectError("no graph named %s here (oto graphs list)" % name)
    server = _described(name, _read_json(path) or {})["server"]
    mcp_path = os.path.join(root, MCP_FILE)
    mcp = _read_json(mcp_path)
    if mcp is not None and server in (mcp.get("mcpServers") or {}):
        del mcp["mcpServers"][server]
        _write_json(mcp_path, mcp)
    os.remove(path)
    build = os.path.join(folder, BUILD)
    if os.path.isdir(build) and not os.listdir(build):                 # what the engine makes on its first query
        os.rmdir(build)
    kept = sorted(os.listdir(folder))
    if not kept:
        os.rmdir(folder)
    return {"name": name, "server": server, "kept": kept}
