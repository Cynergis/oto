# -*- coding: utf-8 -*-
"""Who holds which role on a graph: a file, reviewed like code (docs/plans/people-and-graphs.md, phase 3).

    .github/oto-access.json    stewards, reviewers, contributors, readers; each a GitHub login, or team:<org>/<slug>
    oto repo access            what the file says
    oto repo access --apply    set GitHub to match, on the knowledge repository and its store
    oto repo access --check    say where GitHub has drifted from the file, and exit 1
    oto repo access --owners   write .github/CODEOWNERS from the stewards

Stewards own the file, because `.github/` is under a code owner, so changing it is a pull request a steward approves.
OTO keeps no list of people: GitHub holds identity and permissions, and this file says what they should be.

`readers` is a record for now, of who was given the graph's Neo4j login: nothing applies or enforces it until the server
on Cloud Run. And none of it holds if the organisation's base permission lets every member read every repository, so
`--check` says when it does.
"""
import json
import os
import re

from .project import ProjectError

FILE = os.path.join(".github", "oto-access.json")
ROLES = ("stewards", "reviewers", "contributors", "readers")
KEYS = ROLES + ("store", "_about")
ABOUT = ("Who holds which role on this graph. Stewards own this file: changing it is a pull request a steward approves, and `oto repo access --apply` "
         "sets GitHub to match. Each entry is a GitHub login, or team:<org>/<slug>. `readers` records who was given the graph's Neo4j login, and nothing "
         "enforces it until the server on Cloud Run.")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
TEAM = re.compile(r"^team:[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
#: what each role gets, on the graph's repository and on its store. Only the deploy workflow writes to the store.
PERMISSIONS = {"stewards": "admin", "reviewers": "push", "contributors": "push"}
STORE_PERMISSIONS = {"stewards": "admin", "reviewers": "pull", "contributors": "pull"}
RANK = {"pull": 0, "triage": 1, "push": 2, "maintain": 3, "admin": 4}
ROLE_NAMES = {"read": "pull", "write": "push"}


def starter():
    return {"_about": ABOUT, "stewards": [], "reviewers": [], "contributors": [], "readers": []}


def starter_text():
    return json.dumps(starter(), indent=2, ensure_ascii=False) + "\n"


def load(root):
    """The access file, or None where there is none."""
    path = os.path.join(root, FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError) as exc:
        raise ProjectError("%s can't be read: %s" % (FILE, exc))
    if not isinstance(found, dict):
        raise ProjectError("%s is not a JSON object" % FILE)
    return found


def write(root, access):
    path = os.path.join(root, FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(access, f, indent=2, ensure_ascii=False)
        f.write("\n")


def problems(access):
    """What is wrong with an access file, in words."""
    out = ["unknown key %r: the file holds %s" % (key, ", ".join(ROLES + ("store",))) for key in sorted(set(access) - set(KEYS))]
    for role in ROLES:
        entries = access.get(role, [])
        if not isinstance(entries, list):
            out.append("`%s` is a list of logins and team:<org>/<slug>" % role)
            continue
        for entry in entries:
            if not isinstance(entry, str) or not (LOGIN.match(entry) or TEAM.match(entry)):
                out.append("`%s` holds %r, which is neither a login nor team:<org>/<slug>" % (role, entry))
    if isinstance(access.get("stewards", []), list) and not access.get("stewards"):
        out.append("no steward: name at least one, or nobody can change this file or approve a promotion")
    store = access.get("store")
    if store is not None and not (isinstance(store, str) and REPOSITORY.match(store)):
        out.append("`store` is the store repository, owner/name, not %r" % (store,))
    return out


def _entries(access, role):
    value = access.get(role)
    return [e for e in value if isinstance(e, str)] if isinstance(value, list) else []


def wanted(access, store=False):
    """{users: {login: permission}, teams: {org/slug: permission}} the file asks for, on the graph's repository or its store.
    Someone in two roles gets the higher."""
    table = STORE_PERMISSIONS if store else PERMISSIONS
    out = {"users": {}, "teams": {}}
    for role, permission in table.items():
        for entry in _entries(access, role):
            kind, name = ("teams", entry[len("team:"):]) if entry.startswith("team:") else ("users", entry)
            if RANK[permission] >= RANK.get(out[kind].get(name), -1):
                out[kind][name] = permission
    return out


def code_owners_text(access):
    """`.github/CODEOWNERS` from the stewards: they own what the gate runs on, and the promotion file."""
    from . import repo as _repo
    handles = " ".join("@" + (e[len("team:"):] if e.startswith("team:") else e) for e in _entries(access, "stewards"))
    head = ["# Written by `oto repo access --owners`, from the stewards in .github/oto-access.json. What the gate runs on: its workflows and rules,",
            "# the access file itself, the lock that pins the engine, and the file that promotes a build. A change to these needs a steward's approval.",
            ""]
    return "\n".join(head + ["%-20s %s" % (path, handles) for path in _repo.OWNED]) + "\n"


def write_owners(root, access):
    """Write CODEOWNERS from the stewards. Returns True when it changed."""
    from . import repo as _repo
    path = os.path.join(root, _repo.CODEOWNERS_FILE)
    text = code_owners_text(access)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def who_may_approve(access):
    """(logins, teams) whose approval the route gate counts: the reviewers and the stewards. (None, None) when the file names nobody,
    because a project that hasn't filled it in yet still asks only for write access."""
    entries = _entries(access or {}, "reviewers") + _entries(access or {}, "stewards")
    if not entries:
        return None, None
    return [e for e in entries if not e.startswith("team:")], [e[len("team:"):] for e in entries if e.startswith("team:")]


# ---- GitHub ----

def _current(run, owner_name):
    """What GitHub says now: the same shape as `wanted`, direct collaborators and teams only. Organisation owners aren't listed: they
    aren't anyone's to take away here."""
    from . import repo as _repo
    code, out, err = run("api", "repos/%s/collaborators?affiliation=direct&per_page=100" % owner_name)
    if code != 0:
        raise ProjectError("could not read who has access to %s: %s" % (owner_name, (err or out).strip()[-300:]))
    users = {}
    for user in _repo._json(out, []) or []:
        role = user.get("role_name") or ""
        users[user.get("login")] = ROLE_NAMES.get(role, role)
    code, out, err = run("api", "repos/%s/teams?per_page=100" % owner_name)
    if code != 0:
        raise ProjectError("could not read which teams reach %s: %s" % (owner_name, (err or out).strip()[-300:]))
    teams = {}
    for team in _repo._json(out, []) or []:
        org = (team.get("organization") or {}).get("login") or owner_name.split("/")[0]
        teams["%s/%s" % (org, team.get("slug"))] = team.get("permission")
    return {"users": users, "teams": teams}


def _differences(want, have):
    """(missing or wrong: [(kind, name, wanted, held)], extra: [(kind, name, held)]), names compared without case, as GitHub does."""
    wrong, extra = [], []
    for kind in ("users", "teams"):
        held = {k.lower(): (k, v) for k, v in have[kind].items()}
        asked = {k.lower(): (k, v) for k, v in want[kind].items()}
        for key, (name, permission) in sorted(asked.items()):
            if key not in held:
                wrong.append((kind, name, permission, None))
            elif held[key][1] != permission:
                wrong.append((kind, name, permission, held[key][1]))
        for key, (name, permission) in sorted(held.items()):
            if key not in asked:
                extra.append((kind, name, permission))
    return wrong, extra


def _set(run, owner_name, kind, name, permission):
    if kind == "users":
        return run("api", "--method", "PUT", "repos/%s/collaborators/%s" % (owner_name, name), "-f", "permission=%s" % permission)
    org, slug = name.split("/", 1)
    return run("api", "--method", "PUT", "orgs/%s/teams/%s/repos/%s" % (org, slug, owner_name), "-f", "permission=%s" % permission)


def _unset(run, owner_name, kind, name):
    if kind == "users":
        return run("api", "--method", "DELETE", "repos/%s/collaborators/%s" % (owner_name, name))
    org, slug = name.split("/", 1)
    return run("api", "--method", "DELETE", "orgs/%s/teams/%s/repos/%s" % (org, slug, owner_name))


def _word(kind, name):
    return "the team %s" % name if kind == "teams" else name


def _repositories(access, repository):
    """[(owner/name, on the store?)] the file governs."""
    out = [(repository, False)]
    if isinstance(access.get("store"), str):
        out.append((access["store"], True))
    return out


def apply(root, repository, token=None, gh=None):
    """Set GitHub to match the file, on the graph's repository and its store. Whoever isn't named loses direct access, except the person running
    this, who would lock themselves out mid-way: they are kept, and said. Returns {set, removed, kept, owners_differ}."""
    from . import repo as _repo
    access = load(root)
    if access is None:
        raise ProjectError("no %s here: `oto init --repo` writes one" % FILE)
    found = problems(access)
    if found:
        raise ProjectError("%s can't be applied:\n  - %s" % (FILE, "\n  - ".join(found)))
    run = _repo._github(token, gh)
    me = (_repo.github_login(token, gh) or "").lower()
    out = {"set": [], "removed": [], "kept": [], "owners_differ": not _owners_match(root, access)}
    for owner_name, on_store in _repositories(access, repository):
        want = wanted(access, store=on_store)
        wrong, extra = _differences(want, _current(run, owner_name))
        for kind, name, permission, _held in wrong:
            code, said, err = _set(run, owner_name, kind, name, permission)
            if code != 0:
                raise ProjectError("could not give %s %s on %s: %s" % (_word(kind, name), permission, owner_name, (err or said).strip()[-300:]))
            out["set"].append("%s: %s on %s" % (_word(kind, name), permission, owner_name))
        for kind, name, _held in extra:
            if kind == "users" and name.lower() == me:
                out["kept"].append("%s on %s: you're running this, and the file doesn't name you. Add yourself, or have someone else remove you" % (name, owner_name))
                continue
            code, said, err = _unset(run, owner_name, kind, name)
            if code != 0:
                raise ProjectError("could not remove %s from %s: %s" % (_word(kind, name), owner_name, (err or said).strip()[-300:]))
            out["removed"].append("%s from %s" % (_word(kind, name), owner_name))
    return out


def _owners_match(root, access):
    from . import repo as _repo
    try:
        with open(os.path.join(root, _repo.CODEOWNERS_FILE), encoding="utf-8") as f:
            return f.read() == code_owners_text(access)
    except OSError:
        return False


def drift(root, repository, token=None, gh=None):
    """Where GitHub differs from the file, in words: [] means it matches."""
    from . import repo as _repo
    access = load(root)
    if access is None:
        raise ProjectError("no %s here: `oto init --repo` writes one" % FILE)
    out = list(problems(access))
    run = _repo._github(token, gh)
    org = repository.split("/")[0]
    code, said, _err = run("api", "orgs/%s" % org)
    base = _repo._json(said, {}).get("default_repository_permission") if code == 0 else None
    if base and base != "none":
        out.append("the organisation's base permission is %s: every member can read every repository, documents included, whatever this file says. "
                   "Per-graph access needs it set to none" % base)
    for owner_name, on_store in _repositories(access, repository):
        wrong, extra = _differences(wanted(access, store=on_store), _current(run, owner_name))
        for kind, name, permission, held in wrong:
            out.append("%s has %s on %s, and the file gives %s" % (_word(kind, name), held or "no access", owner_name, permission))
        for kind, name, held in extra:
            out.append("%s still has %s on %s, and the file doesn't name them" % (_word(kind, name), held, owner_name))
    if not _owners_match(root, access):
        out.append("%s isn't the stewards the file names: oto repo access --owners writes it, then commit it" % _repo.CODEOWNERS_FILE)
    return out
