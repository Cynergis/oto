"""Make the package importable when the suite runs without an install.

CI installs the package, which is the proper fix. This keeps a plain `pytest` working from any
directory during development, so a test never passes or fails because of the current directory.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The suite must see only the engine's own vocabulary (oto-core) and the packs it carries as fixtures,
# never whatever the developer keeps in ~/.oto, the packs installed there, or the packs Claude Code
# installed (whose embedded ontologies resolve by name). The engine ships no domain vocabulary
# (ADR-0011): the tests that compose one (product, software-architecture, auto-claims, ...) find it
# under tests/fixtures/packs, the registry's packs frozen at the release they left the engine with,
# resolved the way an installed pack is.
FIXTURE_PACKS = os.path.join(REPO_ROOT, "tests", "fixtures", "packs")
os.environ.setdefault("OTO_ONTOLOGIES", os.path.join(REPO_ROOT, ".no-user-ontologies"))
os.environ.setdefault("OTO_PACKS", FIXTURE_PACKS)
os.environ.setdefault("CLAUDE_CONFIG_DIR", os.path.join(REPO_ROOT, ".no-claude-config"))
os.environ.setdefault("OTO_REGISTRIES", os.path.join(REPO_ROOT, ".no-registries.json"))   # `oto ontology update` saves the registries it knows: never into the repository


# The engine ships no architecture framework (ADR-0008). The tests that need one, for what the core
# does with any framework's model, use the `plain` framework under tests/fixtures/frameworks: its
# adapter reads a model that is already the reified model (tests/fixtures/frameworks/invoice-platform.model.json).
import pytest  # noqa: E402

FRAMEWORKS = os.path.join(REPO_ROOT, "tests", "fixtures", "frameworks")
PLAIN_MODEL = os.path.join(REPO_ROOT, "tests", "fixtures", "frameworks", "invoice-platform.model.json")


@pytest.fixture
def plain_framework(monkeypatch):
    """The `plain` framework pack discovered through OTO_ONTOLOGIES, its code put on the path by the engine."""
    monkeypatch.setenv("OTO_ONTOLOGIES", FRAMEWORKS)
    sys.modules.pop("plain_model", None)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not p.endswith(os.path.join("plain", "code"))])
    return PLAIN_MODEL


# A query repository is reached over https, with the token in the URL. The tests that need git's http
# transport, and what a call sends over it, serve bare repositories through `git http-backend` on
# localhost and keep the Authorization header of every request. A request that carries the header
# actions/checkout leaves in a workflow's workspace is answered 404, as GitHub answers a token that
# cannot see a private repository.
import http.server  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402

CHECKOUT_HEADER = "basic eC1hY2Nlc3MtdG9rZW46am9iLXRva2Vu"     # x-access-token:job-token, as the checkout keeps it


class _GitOverHTTP(http.server.BaseHTTPRequestHandler):
    root = seen = None

    def log_message(self, *args):
        pass

    def _body(self):
        if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))
        chunks = []
        while True:
            size = int(self.rfile.readline().split(b";")[0], 16)
            if not size:
                while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                    pass
                return b"".join(chunks)
            chunks.append(self.rfile.read(size))
            self.rfile.readline()

    def _serve(self):
        self.seen.append(self.headers.get("Authorization"))
        if self.headers.get("Authorization") == CHECKOUT_HEADER:
            self.send_response(404)
            self.end_headers()
            return
        body = self._body()
        path, _, query = self.path.partition("?")
        env = dict(os.environ, GIT_PROJECT_ROOT=self.root, GIT_HTTP_EXPORT_ALL="1", REMOTE_USER="test", REMOTE_ADDR="127.0.0.1",
                   PATH_INFO=path, QUERY_STRING=query, REQUEST_METHOD=self.command, CONTENT_LENGTH=str(len(body)),
                   CONTENT_TYPE=self.headers.get("Content-Type", ""), GIT_PROTOCOL=self.headers.get("Git-Protocol", ""),
                   HTTP_CONTENT_ENCODING=self.headers.get("Content-Encoding", ""))
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        headers = [line.split(":", 1) for line in head.decode().split("\r\n") if ":" in line]
        self.send_response(next((int(v.split()[0]) for k, v in headers if k.lower() == "status"), 200))
        for key, value in headers:
            if key.lower() != "status":
                self.send_header(key, value.strip())
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _serve


class GitServer:
    """Bare repositories under `root`, served at `base`; `seen` is the Authorization header of every request."""
    header = CHECKOUT_HEADER

    def __init__(self, root, base, seen):
        self.root, self.base, self.seen = root, base, seen

    def workspace(self, path):
        """A folder as actions/checkout leaves it: a repository whose config sends the job's token, as an
        extra header, to every URL of the server."""
        subprocess.run(["git", "init", "--quiet", path], check=True)
        subprocess.run(["git", "-C", path, "config", "http.%s/.extraheader" % self.base, "AUTHORIZATION: " + CHECKOUT_HEADER],
                       check=True)
        return path


@pytest.fixture
def git_over_http(tmp_path):
    exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True).stdout.strip()
    if not os.path.exists(os.path.join(exec_path, "git-http-backend")):
        pytest.skip("this git has no http-backend")
    root, seen = str(tmp_path / "served"), []
    os.makedirs(root)
    handler = type("Handler", (_GitOverHTTP,), {"root": root, "seen": seen})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield GitServer(root, "http://127.0.0.1:%d" % server.server_address[1], seen)
    finally:
        server.shutdown()
        server.server_close()
