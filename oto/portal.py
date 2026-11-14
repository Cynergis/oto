# -*- coding: utf-8 -*-
"""Signing this computer in to an OTO portal (docs/plans/portal-sign-in.md).

A team that uses a portal signs in there before working: `oto login` asks the portal for a sign-in,
shows a short code and opens the portal's page, and the person, signed in to the portal in their
browser, allows that code. The portal then answers with a session for this computer, which says who
the person is and which tenant they work in. With it the portal hands out GitHub tokens that last an
hour and reach one repository, so nobody needs a GitHub account or a token of their own.

Two files under ~/.oto:

    profile.json       the portal's address, the person, the tenant, its GitHub organisation and registry.
                       Nothing secret.
    credentials.json   the session. Readable by the person only.

A team with no portal loses nothing: `--github-token-env` and `oto registry add` work as before, and
nothing here is read unless someone signs in.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

PORTAL_ENV = "OTO_PORTAL"
HOME_ENV = "OTO_HOME"
PROFILE = "profile.json"
CREDENTIALS = "credentials.json"
TIMEOUT = 30


class PortalError(Exception):
    """A step that cannot go on; `fix` says what the person does about it."""

    def __init__(self, message, fix=""):
        super().__init__(message)
        self.fix = fix


def folder(home=None):
    """Where the sign-in is kept: ~/.oto, or $OTO_HOME."""
    return home or os.environ.get(HOME_ENV) or os.path.join(os.path.expanduser("~"), ".oto")


def address(url):
    """A portal's address, as it is saved: https, no path. A portal on this computer may be http."""
    url = (url or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1") or (parts.hostname or "").endswith(".localhost")
    if not parts.hostname or parts.scheme not in ("https", "http") or (parts.scheme == "http" and not local):
        raise PortalError("%r isn't a portal's address" % url, "give it as https://<your portal>, with --portal or in %s" % PORTAL_ENV)
    if parts.path.strip("/") or parts.query or parts.fragment or parts.username or parts.password:
        raise PortalError("%r has more than the portal's address in it" % url, "give only https://<your portal>")
    return "%s://%s" % (parts.scheme, parts.netloc)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise PortalError("%s can't be read: %s" % (path, exc), "run `oto login` again; it writes the file anew")
    return found if isinstance(found, dict) else None


def _write(path, payload, private=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Made private before anything is written to it, and private again when it was there with other rights.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        if private:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def profile(home=None):
    """Who this computer is signed in as, or None. Nothing secret: the session is in credentials.json."""
    return _read(os.path.join(folder(home), PROFILE))


def _session(home=None):
    found = _read(os.path.join(folder(home), CREDENTIALS)) or {}
    return found.get("session") or None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A portal answers its own addresses. A redirect would carry the session to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http(method, url, body=None, session=None):
    """One request to the portal: (status, the JSON it answered). The default transport; tests pass their own."""
    headers = {"Accept": "application/json", "User-Agent": "oto/%s" % __version__}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if session:
        headers["Authorization"] = "Bearer %s" % session
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=TIMEOUT) as reply:
            status, raw = reply.status, reply.read(1_000_000)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(1_000_000)
    except (urllib.error.URLError, OSError) as exc:
        raise PortalError("the portal at %s didn't answer: %s" % (urllib.parse.urlsplit(url).netloc, getattr(exc, "reason", exc)),
                          "check the address and your connection, then run this again")
    try:
        found = json.loads(raw.decode("utf-8"))
    except ValueError:
        found = None
    return status, found if isinstance(found, dict) else {}


def _ask(http, method, portal, path, body=None, session=None):
    status, found = http(method, "%s/api/terminal/%s" % (portal, path), body, session)
    if status == 401:
        raise PortalError("this computer isn't signed in to %s any more" % portal, "run `oto login`")
    if status != 200:
        raise PortalError(found.get("error") or "the portal at %s answered %d" % (portal, status),
                          "" if found.get("error") else "check that %s is an OTO portal's address" % portal)
    return found


def _portal(given=None, home=None):
    saved = (profile(home) or {}).get("portal")
    url = given or os.environ.get(PORTAL_ENV) or saved
    if not url:
        raise PortalError("which portal to sign in to isn't known", "name it once: oto login --portal https://<your portal>")
    return address(url)


def _who(http, portal, session):
    """The profile the portal gives for a session."""
    me = _ask(http, "GET", portal, "me", session=session)
    tenant, github = me.get("tenant") or {}, me.get("github") or {}
    return {"portal": portal, "email": me.get("email") or "", "tenant": {"id": tenant.get("id"), "name": tenant.get("name")},
            "organisation": github.get("organisation"), "registry": github.get("registry")}


def login(portal=None, home=None, say=None, browse=None, http=None, sleep=None, clock=time.monotonic):
    """Sign this computer in. Shows the code and the page through `say`, opens the page with `browse`
    (a function of the address; None opens nothing), waits until the person allows the code, then
    saves the profile and the session. Returns the profile."""
    say, http, sleep = say or (lambda line: None), http or _http, sleep or time.sleep
    portal = _portal(portal, home)
    started = _ask(http, "POST", portal, "sign-in", body={})
    device, code, page = started.get("device_code"), started.get("user_code"), started.get("verification_url")
    if not (device and code and page):
        raise PortalError("the portal at %s didn't start a sign-in" % portal, "check that it is an OTO portal's address")
    if not page.startswith(portal + "/"):
        raise PortalError("the portal sent a sign-in page that isn't its own: %s" % page, "nothing was opened; check the portal's address")
    say("Your code: %s" % code)
    say("Allow it on the portal's page, signed in as yourself: %s" % page)
    if browse:
        try:
            browse(page)
        except Exception:        # no browser here: the address above is enough
            pass
    wait = max(1, min(int(started.get("interval") or 3), 30))
    until = clock() + max(60, min(int(started.get("expires_in") or 600), 1800))
    say("Waiting for you to allow it there (the code works for %d minutes)" % round((until - clock()) / 60))
    while True:
        answer = _ask(http, "POST", portal, "poll", body={"device_code": device})
        if answer.get("status") == "approved" and answer.get("session"):
            break
        if answer.get("status") != "pending" or clock() >= until:
            raise PortalError("the code %s wasn't allowed in time" % code, "run `oto login` again and allow the new code")
        sleep(wait)
    session = answer["session"]
    who = _who(http, portal, session)
    base = folder(home)
    _write(os.path.join(base, CREDENTIALS), {"portal": portal, "session": session, "expires_at": answer.get("expires_at")}, private=True)
    _write(os.path.join(base, PROFILE), dict(who, signed_in_until=answer.get("expires_at")))
    return profile(home)


def whoami(home=None, http=None):
    """The profile, checked with the portal and saved again: a tenant may have changed its organisation.
    None when this computer isn't signed in."""
    http = http or _http
    saved, session = profile(home), _session(home)
    if not (saved and session and saved.get("portal")):
        return None
    try:
        who = _who(http, address(saved["portal"]), session)
    except PortalError as exc:
        if "isn't signed in" in str(exc):
            return None
        raise
    _write(os.path.join(folder(home), PROFILE), dict(who, signed_in_until=saved.get("signed_in_until")))
    return profile(home)


def logout(home=None, http=None):
    """End the session at the portal and remove both files. True when this computer was signed in.
    The files go even when the portal can't be reached: the session then ends by itself, on its date."""
    http = http or _http
    saved, session = profile(home), _session(home)
    told = None
    if saved and session and saved.get("portal"):
        try:
            _ask(http, "POST", address(saved["portal"]), "sign-out", body={}, session=session)
        except PortalError as exc:
            told = exc
    removed = False
    for name in (CREDENTIALS, PROFILE):
        try:
            os.remove(os.path.join(folder(home), name))
            removed = True
        except FileNotFoundError:
            pass
    if told and "isn't signed in" not in str(told):
        raise PortalError("signed out on this computer, but the portal wasn't told: %s" % told,
                          "the session ends by itself on its date; nothing else is needed")
    return removed


def signed_in(home=None):
    """The saved profile when this computer holds a session, or None. Nothing is asked of the portal."""
    try:
        saved, session = profile(home), _session(home)
    except PortalError:
        return None
    return saved if saved and session and saved.get("portal") else None


def _signed(home=None):
    saved, session = profile(home), _session(home)
    if not (saved and session and saved.get("portal")):
        raise PortalError("this computer isn't signed in to a portal", "run `oto login`")
    return address(saved["portal"]), session


def repository_token(repository, access="read", home=None, http=None):
    """A GitHub token for one repository of the tenant, from the portal: {token, expires_at, repository,
    access}. It lasts an hour. The portal decides from the person's roles and says why when it refuses.
    The token is returned to the caller and written nowhere."""
    http = http or _http
    if access not in ("read", "write"):
        raise PortalError("access is read or write, not %r" % access)
    portal, session = _signed(home)
    found = _ask(http, "POST", portal, "github-token", body={"repository": repository, "access": access}, session=session)
    if not found.get("token"):
        raise PortalError("the portal gave no token for %s" % repository)
    return found


def prepare_graph(name, home=None, http=None):
    """Have the portal set on a graph it made what the graph's workflows need to push without anyone's
    token: the environment only main deploys from, main's deploy key in it, the store's deploy key and
    the store's address. Asked once the first commit is pushed; asking again changes nothing already
    set. Returns {repository, store, done, warnings}. No key or token comes back: the portal makes the
    keys and gives them to GitHub itself."""
    http = http or _http
    portal, session = _signed(home)
    found = _ask(http, "POST", portal, "graph-setup", body={"name": name}, session=session)
    return {"repository": found.get("repository"), "store": found.get("store"),
            "done": [str(x) for x in found.get("done") or []], "warnings": [str(x) for x in found.get("warnings") or []]}


def create_graph(name, organization=None, domain=None, pack=None, home=None, http=None):
    """Have the portal make a new graph: its private repository and its store, in the tenant's GitHub
    organisation, recorded in the tenant with its place (an organization, and a domain inside it; none
    leaves it not placed) and the pack it starts from. Returns {repository, store, organization, domain,
    token, expires_at, warnings}: the token writes to the new repository for an hour, for the first
    push, and is written nowhere. The portal decides who may create a graph where, and says why not."""
    http = http or _http
    portal, session = _signed(home)
    body = {"name": name}
    for key, value in (("organization", organization), ("domain", domain), ("pack", pack)):
        if value:
            body[key] = value
    found = _ask(http, "POST", portal, "graphs", body=body, session=session)
    if not (found.get("token") and found.get("repository")):
        raise PortalError("the portal didn't say where the graph %s is" % name)
    return found
