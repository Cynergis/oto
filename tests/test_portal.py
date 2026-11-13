"""Signing a computer in to an OTO portal: `oto login` shows a code, the person allows it on the portal's
page, and the portal answers with a session kept under ~/.oto, private to the person. With it the portal
hands out GitHub tokens for one repository at a time (docs/plans/portal-sign-in.md)."""
import contextlib
import http.server
import io
import json
import os
import stat
import threading

import pytest

from oto import portal
from oto.cli import main

PORTAL = "https://portal.example"
SESSION = "s" * 43


class Portal:
    """The portal's five addresses, in memory. `allow_after` is how many polls the person takes to allow the code."""

    def __init__(self, allow_after=1, organisation="acme"):
        self.calls, self.polls, self.allow_after, self.signed_out = [], 0, allow_after, False
        self.organisation = organisation

    def __call__(self, method, url, body=None, session=None):
        assert url.startswith(PORTAL + "/api/terminal/"), url
        path = url.rsplit("/", 1)[-1]
        self.calls.append((method, path, body, session))
        if path == "sign-in":
            return 200, {"device_code": "d" * 43, "user_code": "ABCD-2345", "verification_url": PORTAL + "/terminal?code=ABCD-2345",
                         "expires_in": 600, "interval": 3}
        if path == "poll":
            self.polls += 1
            if self.allow_after is None:
                return 200, {"status": "expired"}
            if self.polls <= self.allow_after:
                return 200, {"status": "pending"}
            return 200, {"status": "approved", "session": SESSION, "expires_at": "2026-12-12T10:00:00.000Z"}
        if session != SESSION or self.signed_out:
            return 401, {"error": "This terminal isn't signed in to the portal. Run: oto login"}
        if path == "me":
            return 200, {"email": "ana@acme.example", "tenant": {"id": "t1", "name": "Acme"},
                         "github": {"organisation": self.organisation, "registry": "%s/oto-registry" % self.organisation} if self.organisation else None}
        if path == "sign-out":
            self.signed_out = True
            return 200, {"signed_out": True}
        if path == "github-token":
            if body["access"] == "write":
                return 403, {"error": "Adding to this graph takes the Graph steward or Contributor role on its place."}
            return 200, {"token": "ghs_one_repository", "expires_at": "2026-11-12T11:00:00Z", "repository": body["repository"], "access": "read"}
        return 404, {}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv(portal.PORTAL_ENV, raising=False)
    monkeypatch.setenv(portal.HOME_ENV, str(tmp_path / "dot-oto"))
    return str(tmp_path / "dot-oto")


def _login(fake, **more):
    said, opened = [], []
    who = portal.login(portal=PORTAL, say=said.append, browse=opened.append, http=fake, sleep=lambda s: None, **more)
    return who, said, opened


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_login_shows_the_code_waits_for_the_person_and_saves_who_they_are(home):
    fake = Portal(allow_after=2)
    who, said, opened = _login(fake)
    assert opened == [PORTAL + "/terminal?code=ABCD-2345"]
    assert "ABCD-2345" in said[0] and PORTAL + "/terminal" in said[1]
    assert fake.polls == 3, "it asks until the person has allowed the code"
    assert who == {"portal": PORTAL, "email": "ana@acme.example", "tenant": {"id": "t1", "name": "Acme"},
                   "organisation": "acme", "registry": "acme/oto-registry", "signed_in_until": "2026-12-12T10:00:00.000Z"}
    assert portal.profile() == who


def test_the_session_is_in_a_file_only_the_person_reads_and_never_in_the_profile(home):
    _login(Portal())
    with open(os.path.join(home, portal.CREDENTIALS), encoding="utf-8") as f:
        assert json.load(f)["session"] == SESSION
    if os.name == "posix":
        assert _mode(os.path.join(home, portal.CREDENTIALS)) == 0o600
    with open(os.path.join(home, portal.PROFILE), encoding="utf-8") as f:
        assert SESSION not in f.read()


def test_a_credentials_file_that_was_readable_by_others_is_made_private(home):
    os.makedirs(home)
    path = os.path.join(home, portal.CREDENTIALS)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}")
    os.chmod(path, 0o644)
    _login(Portal())
    if os.name == "posix":
        assert _mode(path) == 0o600


def test_a_code_nobody_allows_signs_nothing_in(home):
    with pytest.raises(portal.PortalError, match="wasn't allowed in time"):
        _login(Portal(allow_after=None))
    ticks = iter(range(0, 100000, 400))
    with pytest.raises(portal.PortalError, match="wasn't allowed in time"):
        _login(Portal(allow_after=10 ** 6), clock=lambda: next(ticks))
    assert portal.profile() is None and not os.path.exists(os.path.join(home, portal.CREDENTIALS))


def test_login_opens_no_page_that_is_not_the_portals_own(home):
    class Elsewhere(Portal):
        def __call__(self, method, url, body=None, session=None):
            status, found = super().__call__(method, url, body, session)
            if url.endswith("/sign-in"):
                found["verification_url"] = "https://elsewhere.example/terminal?code=ABCD-2345"
            return status, found
    opened = []
    with pytest.raises(portal.PortalError, match="isn't its own"):
        portal.login(portal=PORTAL, browse=opened.append, http=Elsewhere(), sleep=lambda s: None)
    assert opened == []


@pytest.mark.parametrize("given, kept", [("portal.example", PORTAL), ("https://portal.example/", PORTAL),
                                          ("http://localhost:5173", "http://localhost:5173")])
def test_a_portals_address_is_https_and_nothing_more(given, kept):
    assert portal.address(given) == kept


@pytest.mark.parametrize("given", ["", "http://portal.example", "ftp://portal.example", "https://portal.example/terminal",
                                   "https://ana:secret@portal.example", "https://portal.example?x=1"])
def test_anything_else_is_not_a_portals_address(given):
    with pytest.raises(portal.PortalError):
        portal.address(given)


def test_the_portal_is_named_once_then_remembered(home, monkeypatch):
    with pytest.raises(portal.PortalError, match="which portal"):
        portal.login(http=Portal(), sleep=lambda s: None)
    _login(Portal())
    assert portal.login(http=Portal(), sleep=lambda s: None)["portal"] == PORTAL
    monkeypatch.setenv(portal.PORTAL_ENV, "https://other.example")
    with pytest.raises(AssertionError):      # the variable wins over the saved portal, so the fake portal isn't the one asked
        portal.login(http=Portal(), sleep=lambda s: None)


def test_whoami_checks_with_the_portal_and_follows_a_change_there(home):
    assert portal.whoami(http=Portal()) is None
    _login(Portal())
    assert portal.whoami(http=Portal(organisation="acme-two"))["registry"] == "acme-two/oto-registry"
    assert portal.profile()["organisation"] == "acme-two"
    assert portal.whoami(http=Portal(organisation=None))["organisation"] is None
    ended = Portal()
    ended.signed_out = True
    assert portal.whoami(http=ended) is None, "a session the portal no longer knows is not signed in"


def test_logout_ends_the_session_at_the_portal_and_removes_both_files(home):
    fake = Portal()
    _login(fake)
    assert portal.logout(http=fake) is True
    assert fake.signed_out and ("POST", "sign-out", {}, SESSION) in fake.calls
    assert os.listdir(home) == []
    assert portal.logout(http=fake) is False


def test_logout_removes_the_files_even_when_the_portal_is_unreachable(home):
    _login(Portal())

    def down(method, url, body=None, session=None):
        raise portal.PortalError("the portal at portal.example didn't answer: timed out")
    with pytest.raises(portal.PortalError, match="the portal wasn't told"):
        portal.logout(http=down)
    assert os.listdir(home) == []


def test_a_token_is_for_one_repository_and_the_portal_says_why_when_it_refuses(home):
    with pytest.raises(portal.PortalError, match="isn't signed in"):
        portal.repository_token("acme/claims", http=Portal())
    fake = Portal()
    _login(fake)
    found = portal.repository_token("acme/claims", http=fake)
    assert found["token"] == "ghs_one_repository" and found["repository"] == "acme/claims"
    assert fake.calls[-1] == ("POST", "github-token", {"repository": "acme/claims", "access": "read"}, SESSION)
    with pytest.raises(portal.PortalError, match="Graph steward or Contributor"):
        portal.repository_token("acme/claims", "write", http=fake)
    with pytest.raises(portal.PortalError, match="read or write"):
        portal.repository_token("acme/claims", "admin", http=fake)
    for name in os.listdir(home):
        with open(os.path.join(home, name), encoding="utf-8") as f:
            assert "ghs_one_repository" not in f.read(), "a GitHub token is written nowhere"


# The real transport, against a server on this computer.

class _Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append((self.command, self.path, self.headers.get("Authorization"), self.rfile.read(length).decode("utf-8")))
        if self.path.endswith("/moved"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        status, body = (401, {"error": "not signed in"}) if self.path.endswith("/me") and not self.headers.get("Authorization") else (200, {"ok": True})
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = _answer

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Handler.seen = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def test_a_request_carries_the_session_as_a_bearer_and_its_body_as_json(server):
    assert portal._http("POST", server + "/api/terminal/github-token", {"repository": "acme/claims"}, SESSION) == (200, {"ok": True})
    assert portal._http("GET", server + "/api/terminal/me") == (401, {"error": "not signed in"})
    assert _Handler.seen[0] == ("POST", "/api/terminal/github-token", "Bearer " + SESSION, '{"repository": "acme/claims"}')


def test_a_redirect_is_not_followed_so_the_session_goes_nowhere_else(server):
    status, found = portal._http("GET", server + "/api/terminal/moved", session=SESSION)
    assert status == 302 and found == {}
    assert len(_Handler.seen) == 1


def test_a_portal_that_does_not_answer_says_so():
    with pytest.raises(portal.PortalError, match="didn't answer"):
        portal._http("GET", "http://127.0.0.1:1/api/terminal/me")


# The commands.

def _cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


def test_the_three_commands_from_the_command_line(home, monkeypatch):
    code, out, err = _cli("whoami")
    assert code == 1 and "isn't signed in" in err and "oto login" in err
    code, out, err = _cli("login", "--no-browser")
    assert code == 1 and "which portal" in err and "--portal" in err

    fake = Portal()
    monkeypatch.setattr(portal, "_http", fake)
    monkeypatch.setattr(portal.time, "sleep", lambda s: None)
    code, out, err = _cli("login", "--portal", PORTAL, "--no-browser")
    assert code == 0, err
    assert "ABCD-2345" in out and "Signed in: ana@acme.example, in Acme" in out and "acme/oto-registry" in out
    assert SESSION not in out + err

    code, out, err = _cli("whoami", "--json")
    assert code == 0 and json.loads(out)["tenant"] == {"id": "t1", "name": "Acme"}
    code, out, err = _cli("logout")
    assert code == 0 and "Signed out" in out
    code, out, err = _cli("logout")
    assert code == 0 and "wasn't signed in" in out
