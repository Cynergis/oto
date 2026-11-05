"""The server on Cloud Run (docs/plans/people-and-graphs.md, phase 5): only it holds the database login. People reach it signed in through Google's
identity-aware proxy, which it verifies on every request, so removing someone refuses their next one, and every read is logged under their name."""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from oto import connections, repo, sandbox
from oto.cli import main
from oto.project import Project
from oto.scaffold import init

from test_curate import VOCAB, _graph
from test_sandbox import fake  # noqa: F401  (a fixture: the sandbox tool, faked)



def _built(root, slug, name):
    """A project on a small vocabulary, built, as a server serves it."""
    init(root, slug=slug, name=name)
    project = Project.standard(root)
    with open(project.ontology_config_path, "w", encoding="utf-8") as f:
        json.dump(VOCAB, f)
    with open(project.graph_path, "w", encoding="utf-8") as f:
        json.dump(_graph(), f)
    assert main(["build", "--project", root]) == 0
    return root


AUDIENCE = "/projects/123/locations/europe-west1/services/fleet-kg"
ISSUER = "https://cloud.google.com/iap"


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture(scope="module")
def key():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def _jwk(private, kid="test-key"):
    numbers = private.public_key().public_numbers()
    return {"kty": "EC", "crv": "P-256", "alg": "ES256", "use": "sig", "kid": kid,
            "x": _b64(numbers.x.to_bytes(32, "big")), "y": _b64(numbers.y.to_bytes(32, "big"))}


def _token(private, kid="test-key", alg="ES256", **claims):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    now = int(time.time())
    body = dict({"iss": ISSUER, "aud": AUDIENCE, "exp": now + 300, "iat": now - 5, "email": "accounts.google.com:dana@example.org", "sub": "accounts.google.com:1"}, **claims)
    head = _b64(json.dumps({"alg": alg, "kid": kid}).encode())
    payload = _b64(json.dumps(body).encode())
    r, s = decode_dss_signature(private.sign(("%s.%s" % (head, payload)).encode("ascii"), ec.ECDSA(hashes.SHA256())))
    return "%s.%s.%s" % (head, payload, _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big")))


# ---- verifying who asks ----

def test_a_good_assertion_names_the_person(key):
    from oto.serve import iap
    assert iap.verify(_token(key), AUDIENCE, {"test-key": _jwk(key)}) == "dana@example.org"


@pytest.mark.parametrize("change, says", [
    (dict(aud="/projects/999/locations/x/services/other"), "audience"),
    (dict(iss="https://someone.else"), "issuer"),
    (dict(exp=1000), "expired"),
    (dict(iat=int(time.time()) + 3600), "future"),
    (dict(email=""), "email"),
])
def test_a_bad_assertion_is_refused(key, change, says):
    from oto.serve import iap
    with pytest.raises(iap.IapError) as caught:
        iap.verify(_token(key, **change), AUDIENCE, {"test-key": _jwk(key)})
    assert says in str(caught.value)


def test_a_signature_by_another_key_is_refused(key):
    from cryptography.hazmat.primitives.asymmetric import ec
    from oto.serve import iap
    with pytest.raises(iap.IapError):
        iap.verify(_token(ec.generate_private_key(ec.SECP256R1())), AUDIENCE, {"test-key": _jwk(key)})


def test_a_changed_token_is_refused(key):
    from oto.serve import iap
    head, payload, signature = _token(key).split(".")
    other = _b64(json.dumps({"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300, "iat": 0, "email": "mallory@example.org"}).encode())
    with pytest.raises(iap.IapError):
        iap.verify("%s.%s.%s" % (head, other, signature), AUDIENCE, {"test-key": _jwk(key)})
    assert payload


def test_an_unsigned_token_is_refused(key):
    from oto.serve import iap
    head = _b64(json.dumps({"alg": "none", "kid": "test-key"}).encode())
    payload = _b64(json.dumps({"iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 300, "iat": 0, "email": "mallory@example.org"}).encode())
    with pytest.raises(iap.IapError):
        iap.verify("%s.%s." % (head, payload), AUDIENCE, {"test-key": _jwk(key)})


def test_an_unknown_key_and_rubbish_are_refused(key):
    from oto.serve import iap
    for token in (_token(key, kid="other"), "rubbish", "", None):
        with pytest.raises(iap.IapError):
            iap.verify(token, AUDIENCE, {"test-key": _jwk(key)})


# ---- the server, behind the proxy ----

def _post(url, payload, headers=None, path="/mcp"):
    request = urllib.request.Request(url + path, data=json.dumps(payload).encode(), headers=dict({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, **(headers or {})), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


@pytest.fixture
def behind(tmp_path, key):
    """`oto serve --iap` on a built project, run as a Cloud Run container runs it: the proxy's keys in a file, the read log on stderr."""
    root = _built(str(tmp_path / "fleet"), "fleet", "The Fleet")
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"keys": [_jwk(key)]}))
    log = tmp_path / "server.log"
    env = dict(os.environ, OTO_IAP_AUDIENCE=AUDIENCE, OTO_IAP_KEYS_FILE=str(keys), PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for name in ("OTO_SERVE_TOKEN", "OTO_SANDBOX", "OTO_READ_LOG"):
        env.pop(name, None)
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, "-m", "oto.cli", "serve", "--project", root, "--iap", "--http", "0.0.0.0:%d" % port], stdout=out, stderr=out, env=env)
    url = "http://127.0.0.1:%d" % port
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/api/tools", timeout=1)
            break
        except urllib.error.HTTPError:
            break
        except Exception:
            time.sleep(0.25)

    def reads():
        rows = []
        for line in log.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") == "oto.read":
                rows.append(row)
        return rows
    yield url, reads
    proc.terminate()
    proc.wait(timeout=10)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
COUNT = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "kg_count", "arguments": {}}}


def _as(key, **claims):
    return {"X-Goog-IAP-JWT-Assertion": _token(key, **claims)}


def test_with_no_sign_in_every_route_is_refused(behind):
    url, _reads = behind
    for path, payload in (("/mcp", INIT), ("/rpc", INIT)):
        assert _post(url, payload, path=path)[0] == 401
    for path in ("/api/graph", "/api/count", "/data.json", "/"):
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url + path, timeout=10)
        assert caught.value.code == 401, path


def test_someone_signed_in_speaks_mcp_at_its_endpoint(behind, key):
    url, _reads = behind
    status, body, headers = _post(url, INIT, _as(key))
    assert status == 200 and "application/json" in headers.get("Content-Type", ""), (status, headers)
    assert json.loads(body)["result"]["serverInfo"]["name"] == "fleet-kg"
    status, body, _h = _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, _as(key))
    assert status == 202 and body == "", "a notification gets no answer"
    status, body, _h = _post(url, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, _as(key))
    assert any(t["name"] == "kg_count" for t in json.loads(body)["result"]["tools"])
    status, body, _h = _post(url, COUNT, _as(key))
    assert status == 200 and "count" in json.loads(body)["result"]["content"][0]["text"]


def test_mcp_takes_a_batch_and_refuses_a_get(behind, key):
    url, _reads = behind
    status, body, _h = _post(url, [INIT, COUNT], _as(key))
    assert status == 200 and len(json.loads(body)) == 2
    request = urllib.request.Request(url + "/mcp", headers=_as(key))
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 405, "no stream from this server: a client falls back to POST"


def test_someone_whose_sign_in_stopped_working_is_refused_on_the_next_request(behind, key):
    url, _reads = behind
    assert _post(url, COUNT, _as(key))[0] == 200
    assert _post(url, COUNT, _as(key, exp=1000))[0] == 401


def test_every_read_is_logged_under_the_persons_name_and_a_stated_name_counts_for_nothing(behind, key):
    url, reads = behind
    assert _post(url, COUNT, dict(_as(key, email="accounts.google.com:rita@example.org"), **{"X-Oto-Principal": "principal.someone-else"}))[0] == 200
    request = urllib.request.Request(url + "/api/count", headers=_as(key))
    with urllib.request.urlopen(request, timeout=10) as r:
        assert r.status == 200
    rows = reads()
    assert [(r["principal"], r["tool"]) for r in rows][:1] == [("rita@example.org", "kg_count")], rows
    assert rows[0]["ok"] is True and rows[0]["graph"] == "fleet" and rows[0]["at"]
    assert any(r["principal"] == "dana@example.org" and "/api/count" in r["tool"] for r in rows), rows


def test_a_refused_request_is_not_logged_as_a_read(behind):
    url, reads = behind
    assert _post(url, COUNT)[0] == 401
    assert reads() == []


def test_the_server_refuses_to_start_without_what_it_verifies_with(tmp_path, capsys):
    root = str(tmp_path / "fleet")
    init(root, slug="fleet", name="The Fleet")
    capsys.readouterr()
    env_before = os.environ.pop("OTO_IAP_AUDIENCE", None)
    try:
        code = main(["serve", "--project", root, "--iap", "--http", "0.0.0.0:18999"])
    finally:
        if env_before:
            os.environ["OTO_IAP_AUDIENCE"] = env_before
    assert code != 0 and "OTO_IAP_AUDIENCE" in capsys.readouterr().err


def test_iap_needs_http(tmp_path, capsys):
    root = str(tmp_path / "fleet")
    init(root, slug="fleet", name="The Fleet")
    code = main(["serve", "--project", root, "--iap"])
    assert code != 0 and "--http" in capsys.readouterr().err


def test_with_a_token_mcp_needs_it_too(tmp_path):
    root = _built(str(tmp_path / "fleet"), "fleet", "The Fleet")
    code = """
import os, sys
os.environ.update(OTO_DB=sys.argv[1], OTO_PROJECT_CONFIG=sys.argv[2])
from oto.serve import engine, http
server = http.Server(engine, "127.0.0.1", 0, token="a-token").start()
print(server.url, flush=True)
sys.stdin.read()
"""
    db = os.path.join(root, "build", "fleet.db")
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.Popen([sys.executable, "-c", code, db, os.path.join(root, "project.config.json")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    try:
        url = proc.stdout.readline().strip()
        assert _post(url, INIT)[0] == 401
        assert _post(url, INIT, {"Authorization": "Bearer a-token"})[0] == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---- the read log, away from the proxy ----

def test_the_read_log_is_off_unless_asked_for(tmp_path, monkeypatch, capsys):
    from oto.serve import readlog
    monkeypatch.delenv("OTO_READ_LOG", raising=False)
    readlog.record({"principal": "dana"}, "kg_count", {}, True, graph="fleet")
    assert capsys.readouterr().err == ""
    target = tmp_path / "reads.jsonl"
    monkeypatch.setenv("OTO_READ_LOG", str(target))
    readlog.record({"principal": "dana"}, "kg_search", {"query": "x" * 2000}, True, graph="fleet")
    row = json.loads(target.read_text())
    assert row["principal"] == "dana" and row["tool"] == "kg_search" and len(row["arguments"]["query"]) <= 300, "a read log isn't a copy of what was asked at length"


def test_a_stdio_server_never_writes_the_log_to_stdout(monkeypatch, capsys):
    from oto.serve import readlog
    monkeypatch.setenv("OTO_READ_LOG", "stderr")
    readlog.record({}, "kg_count", {}, True)
    out = capsys.readouterr()
    assert out.out == "" and json.loads(out.err)["principal"] == "(nobody named)"


# ---- kg_call, to a graph behind a token ----

def test_kg_call_sends_a_credential_named_for_that_graph(monkeypatch):
    from oto.serve import engine
    monkeypatch.delenv("OTO_CALL_TOKEN", raising=False)
    monkeypatch.delenv("OTO_CALL_TOKEN_ACME_FLEET", raising=False)
    target = {"id": "graph.acme-fleet", "attributes": {"slug": "acme-fleet"}}
    assert engine.call_headers(target) == {}
    monkeypatch.setenv("OTO_CALL_TOKEN", "any-graph")
    assert engine.call_headers(target) == {"Authorization": "Bearer any-graph"}
    monkeypatch.setenv("OTO_CALL_TOKEN_ACME_FLEET", "this-graph")
    assert engine.call_headers(target) == {"Authorization": "Bearer this-graph"}, "the graph's own wins"


def test_kg_call_really_reaches_a_graph_behind_a_token(tmp_path, monkeypatch):
    """What the spec's test found: a 401, because kg_call sent no credential."""
    root = _built(str(tmp_path / "other"), "other", "Other")
    code = """
import os, sys
os.environ.update(OTO_DB=sys.argv[1], OTO_PROJECT_CONFIG=sys.argv[2])
from oto.serve import engine, http
server = http.Server(engine, "127.0.0.1", 0, token="a-token").start()
print(server.url, flush=True)
sys.stdin.read()
"""
    env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = subprocess.Popen([sys.executable, "-c", code, os.path.join(root, "build", "other.db"), os.path.join(root, "project.config.json")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    try:
        url = proc.stdout.readline().strip()
        from oto.serve import engine
        monkeypatch.setattr(engine, "_graph_rows", lambda: [{"id": "graph.other", "label": "Other", "attributes": {"slug": "other", "reach": url}}])
        monkeypatch.setattr(engine, "_find_graph", lambda rows, graph: rows[0])
        with pytest.raises(ValueError) as caught:
            engine.call_text("graph.other", "kg_count", {})
        assert "401" in str(caught.value)
        monkeypatch.setenv("OTO_CALL_TOKEN_OTHER", "a-token")
        said = engine.call_text("graph.other", "kg_count", {})
        assert "count" in said
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---- the container and its workflow ----

def _server_files():
    return repo.files("fleet", "The Fleet")


def test_a_graphs_repository_carries_a_container_and_a_deploy_workflow():
    files = _server_files()
    docker = files[os.path.join(".github", "oto-server", "Dockerfile")]
    assert "--iap" in docker and "$PORT" in docker.replace("${PORT:-8080}", "$PORT") and "[neo4j,cloud,bigquery]" in docker and "project.config.json" in docker
    text = files[os.path.join(".github", "workflows", "oto-server.yml")]
    assert "gcloud" in text and "--iap" in text and "--no-allow-unauthenticated" in text
    assert "--set-secrets" in text and "NEO4J_PASSWORD=" in text, "the login comes from Secret Manager, never a file"
    assert "OTO_IAP_AUDIENCE=" in text and "environment: oto-main" in text and "google-github-actions/auth" in text
    assert "if: vars.OTO_GCP_PROJECT != ''" in text, "a graph that serves no one over Cloud Run does nothing here"


def test_the_container_builds_from_a_pinned_engine_with_no_token_inside():
    text = _server_files()[os.path.join(".github", "workflows", "oto-server.yml")]
    assert "Pin the engine to the lock" in text and "pip wheel" in text, "a wheel, so a private engine's token never enters the image"
    docker = _server_files()[os.path.join(".github", "oto-server", "Dockerfile")]
    assert "TOKEN" not in docker and "git+" not in docker


# ---- deploying it: the workflow's own steps, run with a stand-in gcloud ----

def _deploy_step(tmp_path, **env):
    from test_gate_and_secrets import _script, _step
    log = tmp_path / "gcloud.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(str(bin_dir / "gcloud"), '#!/bin/sh\necho "$*" >> "%s"\nif [ "$1 $2" = "projects describe" ]; then echo 123; fi\n' % log)
    text = _server_files()[os.path.join(".github", "workflows", "oto-server.yml")]
    base = dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ["PATH"]), SERVICE="fleet-kg", PROJECT="acme", REGION="europe-west1", DATASET="", RUNTIME="", MEMORY="1Gi")
    done = subprocess.run(["bash", "-e", "-c", _step(text, "Deploy it behind the proxy")], capture_output=True, text=True, env=dict(base, **env))
    assert done.returncode == 0, done.stdout + done.stderr
    return log.read_text().splitlines(), done.stdout


def test_a_graph_in_bigquery_deploys_with_no_database_login(tmp_path):
    calls, _out = _deploy_step(tmp_path, DATASET="kg", RUNTIME="reader@acme.iam.gserviceaccount.com")
    deploy = next(c for c in calls if c.startswith("run deploy"))
    assert "--set-secrets" not in deploy, "there is no database login to hand it, and naming secrets that don't exist fails the deploy"
    assert "OTO_STORE=bigquery" in deploy and "OTO_BIGQUERY_PROJECT=acme" in deploy and "OTO_BIGQUERY_DATASET=kg" in deploy
    assert "--service-account reader@acme.iam.gserviceaccount.com" in deploy, "what it may read is what this identity may read"
    assert "OTO_IAP_AUDIENCE=/projects/123/locations/europe-west1/services/fleet-kg" in deploy and "OTO_READ_LOG=stderr" in deploy


def test_a_graph_in_neo4j_still_gets_its_login_from_secret_manager(tmp_path):
    calls, _out = _deploy_step(tmp_path)
    deploy = next(c for c in calls if c.startswith("run deploy"))
    assert "--set-secrets NEO4J_USER=fleet-neo4j-user:latest,NEO4J_PASSWORD=fleet-neo4j-password:latest" in deploy and "OTO_STORE" not in deploy


def test_the_deploy_puts_it_behind_the_proxy_and_lets_the_proxy_call_it(tmp_path):
    """Google's docs: deploying with gcloud doesn't grant the proxy's service agent the invoker role, so every request would be refused."""
    calls, _out = _deploy_step(tmp_path, DATASET="kg")
    deploy = next(i for i, c in enumerate(calls) if c.startswith("run deploy"))
    assert "--iap" in calls[deploy] and "--no-allow-unauthenticated" in calls[deploy] and "--source .github/oto-server" in calls[deploy]
    grant = next(i for i, c in enumerate(calls) if c.startswith("run services add-iam-policy-binding"))
    assert grant > deploy, "the service has to exist first"
    assert "fleet-kg" in calls[grant] and "--member serviceAccount:service-123@gcp-sa-iap.iam.gserviceaccount.com" in calls[grant] and "--role roles/run.invoker" in calls[grant]
    assert "--region europe-west1" in calls[grant] and "--project acme" in calls[grant]
    assert not [c for c in calls if c.startswith("beta")], "Google's docs give the standard track for this"


def test_the_copy_in_memory_gets_room_and_the_room_can_change(tmp_path):
    calls, _out = _deploy_step(tmp_path, DATASET="kg", MEMORY="2Gi")
    assert "--memory 2Gi" in next(c for c in calls if c.startswith("run deploy"))
    text = _server_files()[os.path.join(".github", "workflows", "oto-server.yml")]
    assert "vars.OTO_SERVER_MEMORY || '1Gi'" in text


def test_it_warns_when_bigquery_is_read_by_the_default_identity(tmp_path):
    calls, out = _deploy_step(tmp_path, DATASET="kg")
    assert "--service-account" not in next(c for c in calls if c.startswith("run deploy"))
    assert "::warning::" in out and "OTO_GCP_RUNTIME_SERVICE_ACCOUNT" in out


def _deploy_workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(repo.files("fleet", "The Fleet")[os.path.join(".github", "workflows", "oto-deploy.yml")])


def test_a_merge_loads_bigquery_only_when_a_dataset_is_named():
    job = _deploy_workflow()["jobs"]["build-and-publish"]
    assert job["permissions"]["id-token"] == "write", "signing in to Google Cloud with no stored key"
    assert job["permissions"]["contents"] == "read"
    names = [s.get("name") for s in job["steps"]]
    sign_in, load = names.index("Sign in to Google Cloud, when the graph goes to BigQuery"), names.index("Load BigQuery, when a dataset is named")
    assert names.index("Build every layer") < sign_in < load
    for step in (job["steps"][sign_in], job["steps"][load]):
        assert step["if"] == "vars.OTO_BIGQUERY_DATASET != ''"
    auth = job["steps"][sign_in]
    assert auth["uses"].startswith("google-github-actions/auth") and "OTO_GCP_WORKLOAD_IDENTITY_PROVIDER" in auth["with"]["workload_identity_provider"]
    assert "OTO_GCP_LOAD_SERVICE_ACCOUNT" in auth["with"]["service_account"] and "OTO_GCP_SERVICE_ACCOUNT" in auth["with"]["service_account"]
    env = job["steps"][load]["env"]
    assert "OTO_GCP_PROJECT" in env["OTO_BIGQUERY_PROJECT"] and "OTO_BIGQUERY_DATASET" in env["OTO_BIGQUERY_DATASET"]
    run = job["steps"][load]["run"]
    assert "oto build --project . --only bigquery --target bigquery --verify" in run and "NEO4J" not in run


@pytest.mark.parametrize("step, extra", [("Load BigQuery, when a dataset is named", "bigquery"), ("Load the self-hosted Neo4j, when one is configured", "neo4j")])
def test_a_load_installs_the_engine_the_lock_names(step, extra):
    """Neither load may run a different engine from the build that made what it loads."""
    job = _deploy_workflow()["jobs"]["build-and-publish"]
    run = next(s for s in job["steps"] if s.get("name") == step)["run"]
    assert '"oto-kg[%s] @ git+${ENGINE}${ENGINE_REF}"' % extra in run


def test_a_merge_loads_it_from_settings_in_the_workflow_alone(tmp_path, monkeypatch):
    """The repository's config stays as it is, so a sandbox on this repository goes on reading its own build."""
    from fake_bigquery import FakeClient
    from oto.targets import bigquery as target
    root = _built(str(tmp_path / "fleet"), "fleet", "The Fleet")
    fake = FakeClient()
    monkeypatch.setattr(target, "open_client", lambda settings: fake)
    monkeypatch.setenv("OTO_BIGQUERY_PROJECT", "p")
    monkeypatch.setenv("OTO_BIGQUERY_DATASET", "kg")
    assert main(["build", "--project", root, "--only", "bigquery", "--target", "bigquery", "--verify"]) == 0
    assert fake.rows("nodes__b1")
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert "bigquery" not in config and "serve" not in config


def test_a_container_holding_only_the_config_answers_from_bigquery_behind_the_proxy(tmp_path, key, monkeypatch):
    """What Cloud Run runs, with all of it real but BigQuery and Google's signature: only project.config.json in the folder, and the store named by the environment."""
    from fake_bigquery import FakeClient
    from oto.targets import bigquery as target
    root = _built(str(tmp_path / "fleet"), "fleet", "The Fleet")
    fake = FakeClient()
    monkeypatch.setattr(target, "open_client", lambda settings: fake)
    monkeypatch.setenv("OTO_BIGQUERY_PROJECT", "p")
    monkeypatch.setenv("OTO_BIGQUERY_DATASET", "kg")
    assert main(["build", "--project", root, "--only", "bigquery", "--target", "bigquery"]) == 0
    monkeypatch.undo()
    saved = str(tmp_path / "bq.json")
    fake.save(saved)
    app = tmp_path / "app"
    app.mkdir()
    with open(os.path.join(root, "project.config.json"), encoding="utf-8") as f:
        (app / "project.config.json").write_text(f.read())
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"keys": [_jwk(key)]}))
    here = os.path.dirname(os.path.abspath(__file__))
    script = ("import sys; sys.path.insert(0, %r); from fake_bigquery import FakeClient; from oto.targets import bigquery as t; "
              "t.open_client = lambda settings: FakeClient.load(%r); from oto.cli import main; sys.exit(main(sys.argv[1:]))" % (here, saved))
    env = dict(os.environ, OTO_IAP_AUDIENCE=AUDIENCE, OTO_IAP_KEYS_FILE=str(keys), PYTHONPATH=os.path.dirname(here), OTO_STORE="bigquery",
               OTO_BIGQUERY_PROJECT="p", OTO_BIGQUERY_DATASET="kg")
    for name in ("OTO_SERVE_TOKEN", "OTO_SANDBOX", "OTO_READ_LOG", "OTO_DB", "OTO_PROJECT_CONFIG"):
        env.pop(name, None)
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    log = tmp_path / "server.log"
    with open(log, "w") as out:
        proc = subprocess.Popen([sys.executable, "-c", script, "serve", "--project", str(app), "--iap", "--http", "0.0.0.0:%d" % port], stdout=out, stderr=subprocess.STDOUT, env=env)
    url = "http://127.0.0.1:%d" % port
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(url + "/api/tools", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.25)
        assert _post(url, COUNT)[0] == 401, "no way in unsigned"
        code, body, _headers = _post(url, COUNT, _as(key))
        assert code == 200, body + log.read_text()
        assert json.loads(body)["result"]["content"][0]["text"].strip(), body
        assert "serving BigQuery p.kg" in log.read_text(), log.read_text()
        # the guide's first check, in a browser (docs/E2E-GCP.md): signed in, the status says the store and the build, before any sandbox is involved
        unsigned = urllib.request.Request(url + "/api/status")
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(unsigned, timeout=10)
        assert refused.value.code == 401
        with urllib.request.urlopen(urllib.request.Request(url + "/api/status", headers=_as(key)), timeout=10) as answer:
            status = json.loads(answer.read().decode())
        assert status["backend"] == "bigquery" and status["serving"] is True and status["build_seq"] is not None, status
        reads = [json.loads(line) for line in log.read_text().splitlines() if line.startswith("{") and "oto.read" in line]
        assert reads and reads[-1]["principal"] == "dana@example.org", "the read is logged under the person's name"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# ---- reaching it from a sandbox ----

def test_a_graph_read_through_a_server_is_not_called_neo4j(fake, tmp_path, capsys):  # noqa: F811
    """The server may read BigQuery, and the person reading this is deciding what to trust: only a graph with a Neo4j address says Neo4j."""
    folder = str(tmp_path / "project")
    assert main(["graphs", "add", "fleet", "--server", "https://fleet-kg-abc.a.run.app/mcp", "--project", folder]) == 0
    capsys.readouterr()
    assert main(["graphs", "list", "--project", folder]) == 0
    assert "Neo4j" not in capsys.readouterr().out
    assert main(["status", "--project", folder]) == 0
    assert "Neo4j" not in capsys.readouterr().out
    steps = sandbox.next_steps({"name": "s", "project": folder, "graphs": connections.listed(folder)})
    assert "Neo4j" not in " ".join(steps)


def test_a_connection_to_a_server_holds_no_login(tmp_path):
    folder = str(tmp_path / "project")
    code = main(["graphs", "add", "fleet", "--server", "https://fleet-kg-abc.a.run.app/mcp", "--project", folder])
    assert code == 0
    found = connections.listed(folder)[0]
    assert found["server_url"] == "https://fleet-kg-abc.a.run.app/mcp" and found["variables"] == [] and found["login"] is True
    assert connections.logins(folder) == [], "no login to pass, and no database to reach"
    assert connections.servers(folder) == [{"name": "fleet-kg", "url": "https://fleet-kg-abc.a.run.app/mcp"}]
    mcp = os.path.join(folder, ".mcp.json")
    assert not os.path.exists(mcp) or "fleet-kg" not in open(mcp, encoding="utf-8").read(), "the sandbox tool registers it, and handles the sign-in on the computer"


def test_a_server_address_must_be_https(tmp_path, capsys):
    code = main(["graphs", "add", "fleet", "--server", "http://fleet.example.org/mcp", "--project", str(tmp_path / "p")])
    assert code != 0 and "https" in capsys.readouterr().err


def test_up_registers_a_server_with_the_sandbox_tool(fake, tmp_path):  # noqa: F811
    project = tmp_path / "box" / "project"
    connections.add(str(project), "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp")
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5)
    calls = fake.calls("mcp")
    assert ["mcp", "add", "fleet-kg", "--url", "https://fleet-kg-abc.a.run.app/mcp"] in calls, calls
    assert ["mcp", "load", "fleet-kg", "--sandbox", "box"] in calls, calls
    assert any("fleet-kg" in line for line in report["done"])
    assert not fake.read().get("rules"), "no network rule: the gateway reaches it, from the computer"


CLIENT = "123-abc.apps.googleusercontent.com"


def test_a_connection_can_name_the_client_the_proxy_allows(tmp_path):
    root = str(tmp_path / "folder")
    done = connections.add(root, "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp", client_id=CLIENT)
    assert done["client_id"] == CLIENT and done["variables"] == []
    with open(os.path.join(root, "graphs", "fleet", "project.config.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["server"] == {"url": "https://fleet-kg-abc.a.run.app/mcp", "client_id": CLIENT}, "a client's id is no secret; its secret never goes in a file"
    assert connections.servers(root) == [{"name": "fleet-kg", "url": "https://fleet-kg-abc.a.run.app/mcp", "client_id": CLIENT}]
    assert connections.listed(root)[0]["client_id"] == CLIENT


def test_a_connection_with_no_client_is_as_it_was(tmp_path):
    root = str(tmp_path / "folder")
    connections.add(root, "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp")
    with open(os.path.join(root, "graphs", "fleet", "project.config.json"), encoding="utf-8") as f:
        assert json.load(f)["server"] == {"url": "https://fleet-kg-abc.a.run.app/mcp"}
    assert connections.servers(root) == [{"name": "fleet-kg", "url": "https://fleet-kg-abc.a.run.app/mcp"}]


@pytest.mark.parametrize("given", ["has space", "semi;colon", "$(id)", "-flag", ""])
def test_a_client_id_that_isnt_one_is_refused(tmp_path, given):
    from oto.project import ProjectError
    with pytest.raises(ProjectError):
        connections.add(str(tmp_path / "folder"), "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp", client_id=given)


def test_a_client_id_needs_a_server(tmp_path, capsys):
    code = main(["graphs", "add", "fleet", "--uri", "neo4j+s://a.databases.neo4j.io", "--client-id", CLIENT, "--project", str(tmp_path / "folder")])
    assert code == 1 and "--server" in capsys.readouterr().err


def test_adding_one_says_how_to_sign_in_and_where_the_secret_goes(tmp_path, capsys):
    code = main(["graphs", "add", "fleet", "--server", "https://fleet-kg-abc.a.run.app/mcp", "--client-id", CLIENT, "--project", str(tmp_path / "folder")])
    out = capsys.readouterr().out
    assert code == 0 and "sbx secret set mcp:fleet-kg:client_secret" in out and "sbx mcp auth fleet-kg" in out
    assert main(["graphs", "list", "--project", str(tmp_path / "folder")]) == 0
    assert "signs in through Google" in capsys.readouterr().out


def test_up_registers_it_to_sign_in_through_google_with_no_browser_of_its_own(fake, tmp_path):  # noqa: F811
    project = tmp_path / "box" / "project"
    connections.add(str(project), "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp", client_id=CLIENT)
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5)
    add = next(c for c in fake.calls("mcp") if c[:3] == ["mcp", "add", "fleet-kg"])
    assert add == ["mcp", "add", "fleet-kg", "--url", "https://fleet-kg-abc.a.run.app/mcp", "--client-id", CLIENT,
                   "--oauth-authorization-server", "https://accounts.google.com/.well-known/oauth-authorization-server",
                   "--scope", "openid", "--scope", "email", "--skip-auth"], add
    assert ["mcp", "load", "fleet-kg", "--sandbox", "box"] in fake.calls("mcp")
    steps = "\n".join(sandbox.next_steps(report))
    assert "sbx secret set mcp:fleet-kg:client_secret" in steps and "sbx mcp auth fleet-kg" in steps, steps
    assert "about an hour" in steps, "the person should expect to sign in again"


def test_up_on_a_server_with_no_client_asks_for_no_sign_in(fake, tmp_path):  # noqa: F811
    project = tmp_path / "box" / "project"
    connections.add(str(project), "fleet", None, server="https://fleet-kg-abc.a.run.app/mcp")
    report = sandbox.up(name="box", directory=str(tmp_path / "box"), approve=True, wait=5)
    assert "sbx mcp auth" not in "\n".join(sandbox.next_steps(report))


def test_removing_a_server_connection(tmp_path):
    folder = str(tmp_path / "project")
    assert main(["graphs", "add", "fleet", "--server", "https://fleet-kg-abc.a.run.app/mcp", "--project", folder]) == 0
    assert main(["graphs", "rm", "fleet", "--project", folder]) == 0
    assert connections.listed(folder) == []
