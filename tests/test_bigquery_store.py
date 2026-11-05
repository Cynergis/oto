"""BigQuery as a graph's store: a build loaded into a dataset, and a server answering from a copy of it in memory.

The answers must match the build's to the character, a half-finished load must never be read, and a server must
notice a new load without a restart. These run against a strict client in memory (fake_bigquery.py); the calls OTO makes
are checked against the real client's signatures where it's installed. A real dataset is `oto connectors check bigquery`.
"""
import contextlib
import copy
import importlib
import io
import json
import os
import shutil
import subprocess
import sys

import pytest

from fake_bigquery import FakeClient, NotFound
from oto import connections, connectors, deploy
from oto.builder import build
from oto.cli import main
from oto.connectors import conformance
from oto.project import Project, ProjectError
from oto.serve import payload as _payload
from oto.serve.store import BigQueryStore, SqliteStore
from oto.targets import bigquery as target
from test_store import _built
from test_store_equivalence import _answers, _project

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WHERE = {"bigquery": {"project": "p", "dataset": "kg"}}


def _quietly(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch):
    for name in ("OTO_BIGQUERY_PROJECT", "OTO_BIGQUERY_DATASET", "OTO_BIGQUERY_REFRESH", "OTO_STORE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("kb") / "kb")
    project = _quietly(_project, root, neo4j=False)
    _quietly(build, project)
    return project


@pytest.fixture
def plan(built):
    return connectors.get("bigquery").plan(built)


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(target, "open_client", lambda settings: settings.get("client") or fake)
    return fake


def _load(fake, planned):
    return target.load(fake, "p", "kg", planned)


def _store():
    return BigQueryStore.from_config(WHERE)


def _changed(planned, label="Renamed"):
    out = copy.deepcopy(planned)
    out["nodes"][0]["label"] = label
    return out


# ---- a load ----

def test_a_load_is_one_finished_build_in_tables_of_its_own(client, plan):
    done = _load(client, plan)
    assert done["seq"] == 1 and not done["unchanged"]
    assert len(client.rows("nodes__b1")) == len(plan["nodes"]) and done["tables"]["nodes"] == len(plan["nodes"])
    assert "docs_fts" not in done["tables"], "the passages' search table is filled from docs, not loaded twice"
    assert not [t for t in client.names() if t.startswith("docs_fts") or "_data" in t or "_idx" in t or "_docsize" in t], "SQLite's own index tables aren't data"
    built = client.rows("oto_builds")
    assert len(built) == 1 and built[0]["seq"] == 1 and built[0]["hash"] == done["hash"] and "CREATE TABLE nodes" in built[0]["schema_sql"]
    assert client.view("nodes") == "nodes__b1", "people query the graph by the plain name"


def test_a_table_with_no_rows_still_exists_and_comes_back_empty(client, plan):
    empty = dict(plan, questions=[])
    _load(client, empty)
    assert client.rows("questions__b1") == []
    store = _store()
    assert not store.questions()
    store.close()


def test_the_same_build_loaded_again_changes_nothing(client, plan):
    first = _load(client, plan)
    loads = client.count("load")
    again = _load(client, plan)
    assert again["unchanged"] and again["seq"] == first["seq"] and client.count("load") == loads
    assert len(client.rows("oto_builds")) == 1


def test_a_new_build_replaces_the_last_and_only_the_last_two_are_kept(client, plan):
    for seq, label in enumerate(("A", "B", "C"), 1):
        assert _load(client, _changed(plan, label))["seq"] == seq
    names = client.names()
    assert "nodes__b3" in names and "nodes__b2" in names and "nodes__b1" not in names
    assert client.view("nodes") == "nodes__b3"
    assert [r["seq"] for r in client.rows("oto_builds")] == [1, 2, 3], "the record of what was loaded stays"


def test_a_dataset_that_isnt_there_says_how_to_make_it(plan):
    with pytest.raises(ProjectError) as caught:
        target.load(FakeClient(datasets=()), "p", "kg", plan)
    assert "bq mk --dataset" in str(caught.value) and "p:kg" in str(caught.value)


# ---- never a half-finished load ----

@pytest.mark.parametrize("stops_at", ["edges__b2", "oto_builds"])
def test_a_load_that_stops_midway_changes_nothing_a_reader_sees(client, plan, stops_at):
    _load(client, plan)
    client.fail_on = stops_at
    with pytest.raises(Exception):
        _load(client, _changed(plan))
    store = _store()
    assert store.seq == 1 and store.node(plan["nodes"][0]["id"])["label"] == plan["nodes"][0]["label"]
    store.close()
    client.fail_on = None
    assert _load(client, _changed(plan))["seq"] == 2, "the next load simply goes over what was left"
    assert not [t for t in client.names() if "__b3" in t]
    store = _store()
    assert store.node(plan["nodes"][0]["id"])["label"] == "Renamed"
    store.close()


def test_a_reader_caught_by_a_new_load_starts_again(client, plan):
    _load(client, plan)
    client.missing_once = {"edges__b1"}
    store = _store()
    assert store.counts()["nodes"] >= 1
    store.close()


def test_a_reader_that_cant_finish_says_so(client, plan, monkeypatch):
    _load(client, plan)
    real = client.list_rows

    def never(table):
        if str(table).endswith("edges__b1"):
            raise NotFound("gone")
        return real(table)
    monkeypatch.setattr(client, "list_rows", never)
    with pytest.raises(ProjectError) as caught:
        target.read(client, "p", "kg")
    assert "edges" in str(caught.value)


# ---- what a reader gets ----

def test_the_server_answers_exactly_as_the_build_does(client, built, plan):
    from oto.serve import engine
    _load(client, plan)
    sqlite, store = SqliteStore(built.layout.database), _store()
    try:
        root = os.path.dirname(built.config_path)
        a, a_search = _answers(engine, sqlite, root)
        b, b_search = _answers(engine, store, root)
        differences = [k for k in a if a[k] != b[k]]
        assert not differences, "\n\n".join("%s %s\n--- sqlite ---\n%s\n--- bigquery ---\n%s" % (k[0], k[1], a[k], b[k]) for k in differences)
        assert a_search == b_search, "search goes through the same engine, so it matches too"
        pa = _payload.build(sqlite, root, None, passages=True)
        pb = _payload.build(store, root, None, passages=True)
        assert pb["backend"] == "bigquery"
        pa["backend"] = pb["backend"] = None
        assert pa == pb, "the whole graph as data differs between the two"
    finally:
        engine.use(None)
        sqlite.close()
        store.close()


def test_rows_come_back_in_their_order_whatever_order_bigquery_lists_them(client, built, plan):
    _load(client, plan)
    sqlite, store = SqliteStore(built.layout.database), _store()
    try:
        for table in ("nodes", "aliases", "edges", "docs", "node_fts", "docs_fts", "changelog", "terms"):
            query = 'SELECT * FROM "%s" ORDER BY rowid' % table
            assert [tuple(r) for r in sqlite.con.execute(query)] == [tuple(r) for r in store.con.execute(query)], table
    finally:
        sqlite.close()
        store.close()


def test_what_it_reads_is_free_and_needs_only_read_access(client, plan):
    _load(client, plan)
    client.calls.clear()
    store = _store()
    store.newer()
    store.close()
    assert {c[0] for c in client.calls} == {"list_rows"}, "listing a table runs no query job, so it bills nothing and needs only dataViewer"


def test_a_copy_is_not_a_file_so_nothing_depends_on_a_build_here(client, plan):
    _load(client, plan)
    store = _store()
    assert store.kind == "bigquery" and store.path is None and store.features() >= {"derived", "lexicon", "terms", "questions"}
    store.close()


# ---- the engine ----

@pytest.fixture
def engine_on(client, built, monkeypatch):
    """The engine as `oto serve` runs it on BigQuery, and as it was afterwards."""
    from oto.serve import engine

    def start(refresh=0):
        config = os.path.join(str(built.src), "project.config.json")
        monkeypatch.setenv("OTO_PROJECT_CONFIG", config)
        monkeypatch.setenv("OTO_BIGQUERY_PROJECT", "p")
        monkeypatch.setenv("OTO_BIGQUERY_DATASET", "kg")
        monkeypatch.setenv("OTO_STORE", "bigquery")
        monkeypatch.setenv("OTO_BIGQUERY_REFRESH", str(refresh))
        importlib.reload(engine)
        return engine
    yield start
    monkeypatch.undo()
    importlib.reload(engine)


def test_a_server_serves_the_newest_load_with_no_restart(client, plan, engine_on):
    _load(client, plan)
    engine = engine_on()
    assert engine.BACKEND == "bigquery" and engine.STORE.kind == "bigquery"
    first = engine.STORE
    engine.ensure_fresh()
    assert engine.STORE is first, "nothing new was loaded, so nothing is copied again"
    _load(client, _changed(plan))
    engine.ensure_fresh()
    assert engine.STORE is not first and engine.STORE.node(plan["nodes"][0]["id"])["label"] == "Renamed"


def test_a_server_looks_for_a_new_load_only_so_often(client, plan, engine_on):
    _load(client, plan)
    engine = engine_on(refresh=3600)
    first = engine.STORE
    _load(client, _changed(plan))
    client.calls.clear()
    engine.ensure_fresh()
    assert engine.STORE is first and not client.calls, "a question doesn't wait on BigQuery"


def test_a_server_that_cant_look_keeps_answering(client, plan, engine_on):
    _load(client, plan)
    engine = engine_on()
    first = engine.STORE
    client.unreachable = True
    engine.ensure_fresh()
    assert engine.STORE is first and first.node(plan["nodes"][0]["id"])


def test_a_server_started_before_the_first_load_recovers_by_itself(client, plan, engine_on):
    engine = engine_on()
    assert engine.STORE is None and "oto build --target bigquery" in engine.no_data_message()
    _load(client, plan)
    engine.ensure_fresh()
    assert engine.STORE is not None and engine.BIGQUERY_COMPLAINT is None


def test_a_load_from_a_newer_engine_is_refused(client, plan, engine_on):
    _load(client, plan)
    for row in client.tables["p.kg.meta__b1"]["rows"]:
        if row["key"] == "schema_version":
            row["value"] = "999"
    engine = engine_on()
    assert engine.STORE is None and "Upgrade the engine" in engine.no_data_message()


def test_with_no_login_the_server_says_so_and_never_falls_back(client, plan, engine_on):
    _load(client, plan)
    client.unreachable = True
    engine = engine_on()
    assert engine.STORE is None and "cannot read" in engine.no_data_message().lower()


def test_without_the_client_it_names_the_extra(monkeypatch):
    monkeypatch.setattr(target, "available", lambda: False)
    with pytest.raises(ValueError) as caught:
        BigQueryStore.from_config(WHERE)
    assert "oto-kg[bigquery]" in str(caught.value)


def test_with_no_dataset_it_says_what_to_set(monkeypatch):
    with pytest.raises(ValueError) as caught:
        BigQueryStore.from_config({})
    assert "bigquery.dataset" in str(caught.value) and "OTO_BIGQUERY_DATASET" in str(caught.value)


# ---- the connector ----

def test_it_passes_the_conformance_kit(built, monkeypatch):
    fake = FakeClient(datasets=())
    monkeypatch.setattr(target, "open_client", lambda settings: fake)
    connector = connectors.get("bigquery")
    assert connector.MANIFEST["modes"] == ["materialize", "overlay"]
    settings = {"project": "p", "dataset": "kg", "region": "eu"}

    def sessions(name):
        return connector.connect(connector.kit_settings(settings, name))
    result = conformance.run(connector, built, sessions)
    assert result["passed"], conformance.report(result)
    assert fake.datasets == {"p.kg_kit_a", "p.kg_kit_b"}, "the kit's stores are its own, beside the graph"


def test_read_back_finds_a_row_that_changed(client, plan):
    connector = connectors.get("bigquery")
    session = connector.connect({"project": "p", "dataset": "kg"})
    connector.publish(session, plan)
    assert connector.read_back(session, plan) == []
    client.tables["p.kg.edges__b1"]["rows"][0]["rel"] = "something_else"
    found = connector.read_back(session, plan)
    assert found and any("edges" in line for line in found)
    client.tables["p.kg.edges__b1"]["rows"].pop()
    assert connector.read_back(session, plan)


def test_the_overlay_still_reads_a_dataset_it_doesnt_own(client):
    connector = connectors.get("bigquery")
    session = connector.connect({"project": "p", "dataset": "kg", "client": client})
    assert connector.native_read(session, "SELECT 1 AS one")["rows"] == [[1]]
    with pytest.raises(ValueError):
        connector.native_read(session, "DROP TABLE nodes")


# ---- the commands ----

def _configured(root, serve=True, targets=True):
    path = os.path.join(root, "project.config.json")
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    config.update(WHERE)
    if targets:
        config["targets"] = ["sqlite", "bigquery"]
    if serve:
        config["serve"] = {"backend": "bigquery"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f)


@pytest.fixture
def project_here(tmp_path):
    root = str(tmp_path / "kb")
    _quietly(_built, root)
    return root


def _say(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(args))
    return code, out.getvalue()


def _cli_on(saved, *args, cwd=REPO):
    """The real CLI in a process of its own, with the client swapped for the saved one."""
    script = ("import sys; sys.path.insert(0, %r); from fake_bigquery import FakeClient; from oto.targets import bigquery as t; "
              "t.open_client = lambda settings: FakeClient.load(%r); from oto.cli import main; sys.exit(main(sys.argv[1:]))" % (HERE, saved))
    env = {k: v for k, v in os.environ.items() if not k.startswith("OTO_")}
    done = subprocess.run([sys.executable, "-c", script] + list(args), cwd=cwd, env=dict(env, PYTHONPATH=REPO), capture_output=True, text=True, timeout=180)
    return done.returncode, done.stdout, done.stderr


def test_a_build_with_the_target_loads_and_verifies_it(client, project_here):
    _configured(project_here, serve=False)
    code, out = _say("build", "--project", project_here, "--verify")
    assert code == 0 and "bigquery: loaded" in out and "p.kg" in out and "bigquery: verified" in out
    assert len(client.rows("nodes__b1")) > 0


def test_a_build_without_the_target_touches_nothing(client, project_here):
    code, out = _say("build", "--project", project_here)
    assert code == 0 and "bigquery: not configured" in out and not client.calls


def test_target_on_the_command_line_loads_it_once(client, project_here):
    _configured(project_here, serve=False, targets=False)
    code, out = _say("build", "--project", project_here, "--target", "bigquery")
    assert code == 0 and "bigquery: loaded" in out


def test_the_cli_reads_it_and_an_outage_is_an_honest_error(client, project_here, tmp_path):
    _configured(project_here)
    assert _say("build", "--project", project_here)[0] == 0
    saved = str(tmp_path / "bq.json")
    client.save(saved)
    code, out, err = _cli_on(saved, "query", "--project", project_here, "entity", "m.1")
    assert code == 0 and "[Machine — " in out and "serving BigQuery" in err, out + err
    code, out, err = _cli_on(saved, "query", "--project", project_here, "--backend", "sqlite", "entity", "m.1")
    assert code == 0 and "loaded into memory" in err
    os.remove(saved)
    code, out, err = _cli_on(saved, "query", "--project", project_here, "entity", "m.1")
    assert code == 1 and "cannot read" in out.lower() and "[Machine — " not in out, "never answers from a stale local copy"


def test_a_folder_holding_only_the_config_can_serve_it(client, project_here, tmp_path):
    """What the container on Cloud Run holds: the project's config, and no documents or graph."""
    _configured(project_here)
    assert _say("build", "--project", project_here)[0] == 0
    saved = str(tmp_path / "bq.json")
    client.save(saved)
    bare = tmp_path / "app"
    bare.mkdir()
    shutil.copy(os.path.join(project_here, "project.config.json"), str(bare / "project.config.json"))
    assert connections.is_connection(str(bare))
    code, out, err = _cli_on(saved, "query", "--project", str(bare), "entity", "m.1")
    assert code == 0 and "[Machine — " in out, out + err
    code, out, err = _cli_on(saved, "status", "--project", str(bare))
    assert code == 0 and "serving BigQuery p.kg" in out, out + err


def test_status_says_what_it_serves_and_what_is_next(client, project_here):
    _configured(project_here)
    from oto.cli import status as _status
    state = _status._serving(Project.standard(project_here))
    assert state["backend"] == "bigquery" and state["bigquery"]["reachable"] and not state["bigquery"]["loaded"]
    assert "NO load" in _status._serve_line(state)
    assert _say("build", "--project", project_here)[0] == 0
    client.tables.clear()
    code, out = _say("status", "--project", project_here)
    assert code == 0 and "next: oto build --target bigquery" in out
    assert _say("build", "--project", project_here)[0] == 0
    code, out = _say("status", "--project", project_here)
    assert code == 0 and "serving BigQuery p.kg" in out and "next: oto build --target bigquery" not in out


def test_status_says_when_it_cant_read(client, project_here):
    _configured(project_here)
    client.unreachable = True
    from oto.cli import status as _status
    state = _status._serving(Project.standard(project_here))
    assert not state["bigquery"]["reachable"] and "network" in state["bigquery"]["problem"]
    assert "NOT serving" in _status._serve_line(state)


def test_preflight_refuses_serving_from_what_the_build_doesnt_load(project_here):
    from oto.validate.preflight import preflight
    _configured(project_here, targets=False)
    found = preflight(Project.standard(project_here))["warnings"]
    assert any("serves from BigQuery" in line and "does not load it" in line for line in found), found
    _configured(project_here)
    assert not any("BigQuery" in line for line in preflight(Project.standard(project_here))["warnings"])


def test_a_deploy_config_can_name_it():
    base = {"repo": "acme/kg", "graph": "kg", "publish": {"to": "https://github.com/acme/kg-store"},
            "environments": [{"name": "dev", "approvers": []}], "promotion": deploy.PROMOTION}
    assert any("connection" in p for p in deploy.problems(dict(base, connector="bigquery")))
    fine = dict(base, connector="bigquery", connection={"endpoint": "my-project", "database": "kg", "auth": "workload-identity"})
    assert deploy.problems(fine) == []
    assert any("database" in p for p in deploy.problems(dict(base, connector="bigquery", connection={"endpoint": "my-project", "auth": "adc"})))
    assert deploy.problems(deploy.starter("acme/kg", "https://github.com/acme/kg-store", "kg", connector="bigquery")) == []


def test_the_kit_by_hand_uses_datasets_of_its_own(project_here, monkeypatch):
    _configured(project_here)
    fake = FakeClient(datasets=("p.kg",))
    monkeypatch.setattr(target, "open_client", lambda settings: fake)
    assert _say("build", "--project", project_here)[0] == 0
    before = fake.names()
    code, out = _say("connectors", "check", "bigquery", "--project", project_here)
    assert code == 0 and "passed" in out, out
    assert fake.names() == before, "the kit leaves the graph's own dataset alone"
    assert {"p.kg_kit_a", "p.kg_kit_b"} <= fake.datasets


# ---- the real client ----

def test_every_call_fits_the_real_client(plan):
    """No project, no network: the real client's signatures, and its real configuration and row objects."""
    bigquery = pytest.importorskip("google.cloud.bigquery")
    from unittest import mock
    real = mock.create_autospec(bigquery.Client, instance=True)
    real.list_rows.return_value = []
    real.list_tables.return_value = []
    done = target.load(real, "p", "kg", plan)
    assert done["seq"] == 1
    loads = real.load_table_from_json.call_args_list
    assert loads and all(isinstance(c.kwargs["job_config"], bigquery.LoadJobConfig) for c in loads)
    nodes = next(c for c in loads if c.args[1] == "p.kg.nodes__b1")
    assert nodes.kwargs["job_config"].write_disposition == "WRITE_TRUNCATE" and nodes.kwargs["job_config"].source_format == "NEWLINE_DELIMITED_JSON"
    assert {f.name: f.field_type for f in nodes.kwargs["job_config"].schema}["degree"] == "INT64"
    commit = next(c for c in loads if c.args[1] == "p.kg.oto_builds")
    assert commit.kwargs["job_config"].write_disposition == "WRITE_APPEND"
    assert all(isinstance(c.args[0], bigquery.Table) for c in real.create_table.call_args_list)

    # the rows back, as the real Row objects
    def as_rows(rows):
        if not rows:
            return []
        names = {name: i for i, name in enumerate(rows[0])}
        return [bigquery.table.Row(tuple(r[n] for n in names), names) for r in rows]
    by_table = {c.args[1]: c.args[0] for c in loads}
    by_table.setdefault("p.kg.oto_builds", [])
    real.list_rows.side_effect = lambda table: as_rows(by_table.get(table, []))
    con, record = target.read(real, "p", "kg")
    assert record["seq"] == 1 and con.execute("SELECT count(*) FROM nodes").fetchone()[0] == len(plan["nodes"])
    con.close()


def test_the_real_exceptions_read_as_missing():
    exceptions = pytest.importorskip("google.api_core.exceptions")
    assert target._missing(exceptions.NotFound("gone"))
    assert not target._missing(exceptions.Forbidden("no"))
