"""The engine comes from its own marketplace; a registry carries extensions and packs, never the engine
(ADR-0009). The engine's repository is the marketplace `cynergis-engine`, listing the `oto` plugin
alone; every pack the engine generates depends on `oto@cynergis-engine`, and a registry's marketplace
allows that dependency to cross into the engine's marketplace instead of listing the engine. The
release workflow no longer pins the engine into the registry; the kit, the workflow templates and the
documents install the engine from its own marketplace before the packs."""
import json
import os
import re

from oto.model import packs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADR = os.path.join(ROOT, "docs", "adr", "0009-the-registry-carries-no-engine.md")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_engine_s_marketplace_is_named_what_the_packs_depend_on():
    market = json.loads(_read(".claude-plugin", "marketplace.json"))
    assert market["name"] == packs.ENGINE_MARKETPLACE == "cynergis-engine"
    assert [p["name"] for p in market["plugins"]] == [packs.ENGINE_PLUGIN], "the engine's marketplace lists the engine alone"
    assert packs.ENGINE_DEPENDENCY == "oto@cynergis-engine"


def test_a_generated_pack_depends_on_the_engine_from_its_own_marketplace(tmp_path, monkeypatch):
    monkeypatch.setenv("OTO_PACKS", str(tmp_path / "packs"))
    target, problems = packs.new("arch", "software-architecture", maintainer="Cynergis")
    assert problems == []
    plugin = json.loads(open(os.path.join(target, ".claude-plugin", "plugin.json"), encoding="utf-8").read())
    assert plugin["dependencies"] == ["oto@cynergis-engine"]
    # a pack written before this release, depending on the bare name, still passes the check
    plugin["dependencies"] = ["oto"]
    with open(os.path.join(target, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(plugin, f)
    assert packs.check(target) == []
    plugin["dependencies"] = ["report"]
    with open(os.path.join(target, ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(plugin, f)
    assert any("oto@cynergis-engine" in p for p in packs.check(target)), "the check names the dependency as it is written now"


def test_the_release_workflow_pins_no_engine_into_the_registry():
    release = _read(".github", "workflows", "tag-release.yml")
    assert "registry-pin.yml" not in release and "plugin: oto" not in release, "the engine is not a plugin of the registry"
    assert "kit-publish.yml" in release, "the tag still publishes the kit"
    pin = _read(".github", "workflows", "registry-pin.yml")
    assert 'default: "oto"' not in pin and 'default: "Cynergis/oto"' not in pin
    assert "ADR-0009" in pin


def test_the_kit_the_templates_and_the_documents_install_the_engine_from_its_own_marketplace():
    init = _read("kits", "oto-gcp", "files", "home", ".oto", "init.sh")
    assert "claude plugin marketplace add Cynergis/oto " in init or "claude plugin marketplace add Cynergis/oto\n" in init or "add Cynergis/oto  " in init
    assert 'claude plugin install "oto@cynergis-engine"' in init and "Cynergis/oto-registry" in init
    assert init.index("Cynergis/oto ") < init.index("Cynergis/oto-registry") or init.index("(Cynergis/oto)") < init.index("(Cynergis/oto-registry)"), \
        "the engine's marketplace first"
    assert "oto@cynergis-engine" in _read("kits", "README.md") and "oto@cynergis-engine" in _read("kits", "oto-gcp", "files", "home", ".claude", "CLAUDE.md")
    from oto import repo as _repo
    files = _repo.files("acme", "Acme")
    for path, text in files.items():
        if "plugins:" in text:
            assert "oto@cynergis-engine" in text and "oto@oto" not in text, path
    for path in ("README.md", "docs/E2E-TESTING.md"):
        text = _read(*path.split("/"))
        assert "oto@cynergis-engine" in text and "oto@oto" not in text and "0009" in text, path


def test_the_decision_is_recorded_and_accepted():
    text = open(ADR, encoding="utf-8").read()
    head = text.split("---")[1]
    assert "id: ADR-0009" in head and "status: accepted" in head and "decided_by: Chiheb Dkhil" in head
    decision = text.split("## Decision")[1].split("## Consequences")[0]
    assert re.search(r"own marketplace", decision) and "registry" in decision and ("never the engine" in decision or "no engine" in decision)
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        graph = json.load(f)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["decision.adr-0009"]["attributes"]["status"] == "accepted" and nodes["decision.adr-0009"].get("evidence")
    assert ("decision.adr-0009", "governs", "workitem.epic-l") in {(e["from"], e["rel"], e["to"]) for e in graph["edges"]}
