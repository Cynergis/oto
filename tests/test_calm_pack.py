"""CALM out (ADR-0006, step 3). The architecture pack is framework-neutral: a node a framework wrote
carries `external_id`, `external_type` and `external_payload`, the model's document carries `framework`
and the header, and nothing in the pack or the engine names CALM. CALM is the calm pack: an adapter
(`oto/packs/calm.py`) its manifest provides, chosen by `oto arch import --framework calm`, with a
migration for a graph written before release 5 of the architecture pack."""
import contextlib
import io
import json
import os

import pytest

from oto import arch as _arch, audit as _audit, extensions
from oto.cli import main
from oto.curate import session as _session
from oto.model import ontologies
from oto.packs import calm as _calm
from oto.project import Project
from oto.scaffold import init

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INVOICE = os.path.join(ROOT, "tests", "fixtures", "calm", "invoice-platform.calm.json")
CORE = ("oto/arch.py", "oto/cli/arch.py", "oto/builder.py", "oto/cli/__init__.py", "oto/extensions.py", "oto/packs/factory/__init__.py", "oto/packs/policy/iam.py",
        "oto/serve/engine.py", "oto/ontologies/architecture/ontology.config.json", "oto/ontologies/architecture/questions.json",
        "oto/ontologies/architecture/ontology.rationale.json", "oto/ontologies/architecture/sample.graph.json")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


def _project(tmp_path, ontology, slug, empty=False):
    root = str(tmp_path / slug)
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug=slug, name=slug.title(), ontology=ontology, empty=empty)
    return root


def test_the_core_and_the_architecture_pack_name_no_framework():
    for path in CORE:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read().lower()
        if path.endswith(".json"):
            assert "calm_" not in text, path
        else:
            assert "calm" not in text.replace("the calm pack", ""), path
    manifest = ontologies.manifest_for("architecture")
    assert manifest["release"] >= 5 and "framework-neutral" in manifest["summary"]
    own = ontologies.load_raw("architecture")["config"]
    for kind in ("System", "Component", "DataStore", "Environment", "Role"):
        assert {"external_id", "external_type", "external_payload"} <= set(own["attributes"][kind]) and not any(a.startswith("calm_") for a in own["attributes"][kind]), kind
    assert own["attributes"]["Document"]["framework"]["type"] == "string" and "external_payload" in own["attributes"]["Document"]
    assert "external_payload" in own["attributes"]["Decision"] and "external_id" in own["attributes"]["Relationship"] and "external_id" in own["attributes"]["Flow"]
    assert own["attributes"]["Control"]["external_id"]["required"] is True


def test_the_calm_pack_is_the_adapter_and_adds_no_term():
    manifest = ontologies.manifest_for("calm")
    assert manifest["extends"] == ["architecture"] and manifest["release"] == 1
    assert manifest["provides"]["adapters"] == [{"framework": "calm", "module": "oto.packs.calm", "import": "read_model", "export": "write_model", "migrate": "migrate"}]
    assert ontologies.self_check("calm") == [], ontologies.self_check("calm")
    own = ontologies.load_raw("calm")["config"]
    assert own["classes"] == {} and own["properties"] == {}, "CALM maps onto the reified model"
    adapter = extensions.adapter("calm")
    assert adapter["pack"] == "calm" and adapter["read"] is _calm.read_model and adapter["write"] is _calm.write_model and adapter["migrate"] is _calm.migrate
    assert "calm" in extensions.adapters() and extensions.only_adapter() == "calm"
    _config, _sample, readme = ontologies.load("calm")
    assert "https://calm.finos.org/release/1.0/meta/core.json" in readme and "oto arch migrate --framework calm" in readme
    for node_type in ("actor", "ecosystem", "system", "service", "database", "network", "ldap", "webclient", "data-asset"):
        assert "`%s`" % node_type in readme, "the nine CALM node types are named where the mapping is"


def test_a_model_read_through_the_adapter_carries_the_neutral_attributes(tmp_path):
    root = _project(tmp_path, "architecture", "invoice", empty=True)
    with open(os.path.join(root, "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    graph["nodes"].append({"id": "environment.production", "type": "Environment", "label": "Production", "summary": "Where it runs.", "attributes": {},
                           "as_of": "2026-10-28", "valid_from": "2026-10-28", "source_doc": "estate", "status": "current", "sources": ["estate"], "aliases": [], "tags": []})
    with open(os.path.join(root, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    code, out = _cli("arch", "import", "--framework", "calm", "--file", INVOICE, "--at", "2026-10-28", "--environment", "environment.production", "--project", root)
    assert code == 0 and "read from invoice-platform.calm.json" in out and "oto arch export --framework calm" in out, out
    with open(os.path.join(root, "proposals", "calm-invoice-platform.json"), encoding="utf-8") as f:
        proposal = json.load(f)
    nodes = {n["id"]: n for n in proposal["nodes"]}
    intake = nodes["component.invoice-intake"]["attributes"]
    assert intake["external_id"] == "invoice-intake" and intake["external_type"] == "service" and not any(a.startswith("calm_") for a in intake)
    clerk, platform = nodes["role.ap-clerk"]["attributes"], nodes["system.invoice-platform"]["attributes"]
    assert json.loads(clerk["external_payload"]) == {"metadata": {"department": "finance"}}, "metadata and details travel as one payload"
    assert "details" in json.loads(platform["external_payload"]) and "metadata" not in json.loads(platform["external_payload"])
    document = nodes["document.calm-invoice-platform"]["attributes"]
    assert document["framework"] == "calm" and json.loads(document["external_payload"])["$schema"].startswith("https://calm.finos.org/")
    code, out = _cli("arch", "import", "--framework", "c4", "--file", INVOICE, "--at", "2026-10-28", "--project", root)
    assert code == 1 and "c4" in out and "calm" in out, out
    code, out = _cli("arch", "import", "--file", INVOICE, "--at", "2026-10-28", "--project", root)
    assert code == 0, "one adapter on the machine: it is the default\n" + out


def test_a_graph_written_before_release_5_migrates_once_and_exports_as_before(tmp_path):
    root = _project(tmp_path, "architecture", "invoice")
    path = os.path.join(root, "graph.json")
    with open(path, encoding="utf-8") as f:
        graph = json.load(f)
    back = {"external_id": "calm_id", "external_type": "calm_type"}
    touched = 0
    for n in graph["nodes"]:
        a = n.get("attributes") or {}
        for new, old in back.items():
            if new in a:
                a[old] = a.pop(new)
                touched += 1
        if "external_payload" in a and n["type"] == "Document":
            a["calm_header"] = a.pop("external_payload")
            a.pop("framework", None)
        elif "external_payload" in a and n["type"] == "Decision":
            a["calm_option"] = a.pop("external_payload")
        elif "external_payload" in a:
            payload = json.loads(a.pop("external_payload"))
            if "metadata" in payload:
                a["calm_metadata"] = json.dumps(payload["metadata"])
            if "details" in payload:
                a["calm_details"] = json.dumps(payload["details"])
    assert touched
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    code, out = _cli("arch", "export", "--framework", "calm", "--out", os.path.join(root, "before.json"), "--project", root)
    with open(os.path.join(root, "before.json"), encoding="utf-8") as f:
        assert json.load(f)["nodes"] == [], "the old names are not read: no node has an external_id until the graph migrates"
    code, out = _cli("arch", "migrate", "--framework", "calm", "--project", root)
    assert code == 1 and "--by" in out, out
    code, out = _cli("curate", "start", "--project", root)
    assert code == 0
    code, out = _cli("arch", "migrate", "--framework", "calm", "--by", "Ada", "--project", root)
    assert code == 1 and "candidate is open" in out, out
    code, out = _cli("curate", "abort", "--project", root)
    code, out = _cli("arch", "migrate", "--framework", "calm", "--by", "Ada", "--project", root)
    assert code == 0 and "node(s) migrated" in out and "oto build" in out, out
    project = Project.standard(root)
    live = _session.live(project)
    assert not any(a.startswith("calm_") for n in live["nodes"] for a in (n.get("attributes") or {}))
    intake = next(n for n in live["nodes"] if n["id"] == "component.invoice-intake")["attributes"]
    assert intake["external_id"] == "invoice-intake" and intake["external_type"] == "service"
    record = _audit.read(project)[-1]
    assert record["action"] == "arch migrate" and record["principal"] == "Ada" and "component.invoice-intake" in record["nodes"]
    assert os.path.exists(os.path.join(root, "graph.previous.json"))
    code, out = _cli("arch", "migrate", "--framework", "calm", "--by", "Ada", "--project", root)
    assert code == 0 and "nothing to do" in out, out
    code, out = _cli("build", "--project", root)
    assert code == 0, out
    code, out = _cli("arch", "export", "--framework", "calm", "--out", os.path.join(root, "out.json"), "--project", root)
    assert code == 0, out
    with open(os.path.join(root, "out.json"), encoding="utf-8") as f:
        model = json.load(f)
    assert {n["unique-id"] for n in model["nodes"]} >= {"invoice-intake", "invoice-platform", "invoice-db"}
    assert next(n for n in model["nodes"] if n["unique-id"] == "invoice-platform")["metadata"] == {"owner": "payments-platform", "tier": "2"}, "the sample's metadata, through the payload"


def test_the_compile_names_its_models_by_framework(tmp_path):
    root = _project(tmp_path, "architecture", "invoice", empty=True)
    cfg_path = os.path.join(root, "project.config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["arch"] = {"models": [{"framework": "c4", "path": "models/x.json"}]}
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    with pytest.raises(extensions.ExtensionError) as refused:
        _arch.compile_project(Project.standard(root), "2026-10-28", "Ada")
    assert "c4" in str(refused.value)
    cfg["arch"] = {}
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    with pytest.raises(_arch.ArchError) as refused:
        _arch.compile_project(Project.standard(root), "2026-10-28", "Ada")
    assert "models" in str(refused.value) and "framework" in str(refused.value)


def test_the_docs_name_the_calm_pack_and_the_migration():
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    assert "ontologies/calm" in text and "oto arch migrate" in text and "external_id" in text and "--calm" not in text
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    assert "--framework calm --file" in e2e and "--calm" not in e2e and "oto arch migrate" in e2e
    with open(os.path.join(ROOT, "oto", "ontologies", "architecture", "README.md"), encoding="utf-8") as f:
        readme = f.read()
    assert "external_id" in readme and "calm_id" not in readme and "--calm" not in readme
