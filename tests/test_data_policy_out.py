"""The data layer and the access policy are packs of the registry (ADR-0010); the engine ships no pack
with tools of its own. They leave together, since policy composes on data: the `data` pack carries the
schema, lineage, usage and meaning tools and the data-meaning skill; the `policy` pack carries the
compiler, the snapshot, the IAM derivation, its two build stages, its command and its write and read
hooks, with data embedded beside it. The engine's repository forgets both: no oto/packs at all, no
ontology, no skill, no shipped manifest that provides a command, a stage or a hook, and the documents
say where each went and why. What the packs need from the engine stays: the connectors a store is read
through, the deploy config's overlay and the served `kg_read`, `oto decide`, the write path, the seams
(a stage from a pack's code/ included), and the guard the engine plugin runs on a session's snapshot."""
import contextlib
import io
import json
import os
import re

from oto import adr as _adr, connectors, deploy, extensions
from oto.cli import main
from oto.model import ontologies

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GONE = ("oto/packs", "oto/ontologies/data", "oto/ontologies/policy", "skills/data-meaning", "tests/fixtures/lineage", "tests/fixtures/usage",
        "tests/test_meaning.py", "tests/test_lineage.py", "tests/test_usage.py", "tests/test_data_pack.py", "tests/test_policy_pack.py",
        "tests/test_policy_iam.py", "tests/test_policy_snapshot.py", "tests/test_policy_enforcement.py")
FORGETS = ("README.md", "docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/README.md", "skills/concierge/SKILL.md",
           "oto/cli/__init__.py", "oto/extensions.py", "oto/connectors/__init__.py", "hooks/hooks.json")


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def test_the_engine_s_repository_holds_no_pack_with_tools_of_its_own():
    for path in GONE:
        assert not os.path.exists(os.path.join(ROOT, path)), path
    assert not {"data", "policy"} & set(ontologies.available())
    shipped = os.path.join(ROOT, "oto", "ontologies")
    for name in sorted(os.listdir(shipped)):
        manifest = os.path.join(shipped, name, "manifest.json")
        if os.path.exists(manifest):
            with open(manifest, encoding="utf-8") as f:
                provides = json.load(f).get("provides") or {}
            assert not any(k in provides for k in ("stages", "write_hooks", "read_hooks", "status", "adapters")), \
                "%s provides a stage, a hook or an adapter: that is a pack of the registry" % name
            assert all(c.get("name") == "arch" for c in provides.get("commands") or []), "%s provides a command the core does not own" % name
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "oto")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    imports = "\n".join(l for l in f.read().splitlines() if l.lstrip().startswith(("from ", "import ")))
                assert "oto.packs" not in imports and "oto_data" not in imports and "oto_policy" not in imports, os.path.join(dirpath, name)
    assert {c["name"] for c in extensions.commands()} == {"arch"}, "a machine with the engine alone has the core's commands and the architecture's"


def test_the_command_line_has_neither_without_the_packs():
    code, out = _cli("--help")
    assert code == 0 and "  data " not in out and "  policy " not in out and "  arch " in out, out
    for command in ("data", "policy"):
        code, out = _cli(command, "--help")
        assert code == 2 and "invalid choice" in out, (command, out)


def test_what_the_packs_need_from_the_engine_stays():
    assert connectors.OVERLAY_METHODS == ("introspect", "query_log", "native_read")
    assert "sqlite" in connectors.available() and "postgres" in connectors.available() and "bigquery" in connectors.available()
    assert deploy.native_read_allowed({"overlay": {"native_read": True}}) and not deploy.native_read_allowed({})
    code, out = _cli("decide", "--help")
    assert code == 0, "a decision attribute moves with oto decide, the core's"
    assert os.path.exists(os.path.join(ROOT, "hooks", "policy_guard.py")) and os.path.exists(os.path.join(ROOT, "hooks", "policy_snapshot.py")), \
        "the guard and the reader any plugin copies stay the engine plugin's"
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    assert any("policy_guard.py" in h["command"] for group in hooks["PreToolUse"] for h in group["hooks"])



def test_the_documents_point_at_the_packs_and_name_the_decision():
    for path in FORGETS:
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert not re.search(r"(?<![.~])oto/packs/", text) and "oto/ontologies/data" not in text and "oto/ontologies/policy" not in text \
            and "oto.packs." not in text and "skills/data-meaning/" not in text, "%s still points into the engine for the data layer or the policy" % path
    for path in ("docs/ARCHITECTURE.md", "docs/E2E-TESTING.md", "skills/README.md"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            text = f.read()
        assert "0010" in text and ("data@cynergis" in text or "oto pack add data" in text or "packs/data" in text), "%s says where the data layer went" % path
        if path != "skills/README.md":                                   # the policy pack brings no skill
            assert "policy@cynergis" in text or "oto pack add policy" in text or "packs/policy" in text, "%s says where the policy went" % path
    with open(os.path.join(ROOT, "docs", "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    for word in ("oto data introspect", "oto data confirm", "oto_data", "oto policy compile", "oto policy snapshot", "oto policy iam", "oto policy denials", "oto_policy",
                 "policy_guard.py", "X-Oto-Principal", "require_snapshot", "expires_at", "IamBinding", "AR1 to AR11", "ADR-0004", "ADR-0005", "build/iam", "runs_as", "naming.py"):
        assert word in text, "the architecture document keeps its Data and Policy rows, pointing at the registry's packs: %s" % word
    with open(os.path.join(ROOT, "docs", "E2E-TESTING.md"), encoding="utf-8") as f:
        e2e = f.read()
    for word in ("## 21.", "## 28.", "## 29.", "## 30.", "## 32.", "oto policy compile", "oto policy verify", "oto policy snapshot", "oto policy iam", "gcp.json",
                 "bindings.proposal.json", "PL9", "X-Oto-Principal", "--ttl"):
        assert word in e2e, word
    with open(os.path.join(ROOT, "skills", "packs", "SKILL.md"), encoding="utf-8") as f:
        skill = f.read()
    assert "`data`" in skill and "`policy`" in skill, "the packs skill knows both packs"


def test_the_decisions_behind_the_policy_stay_recorded():
    with open(os.path.join(ROOT, "docs", "adr", "0004-cedar-for-policy.md"), encoding="utf-8") as f:
        text = f.read()
    record = _adr.parse(text)
    assert _adr.problems(record) == [] and record["front"]["id"] == "ADR-0004" and record["front"]["status"] == "accepted"
    assert "cedar" in _adr.first_sentence(record["sections"]["Decision"]).lower()
    assert "plain python" in text.lower() and "stdlib" in text.lower(), "the hooks evaluate the JSON form in plain Python; no Cedar engine on the runner's machine"
    with open(os.path.join(ROOT, "docs", "adr", "0005-iam-is-generated-never-enforced.md"), encoding="utf-8") as f:
        text = f.read()
    record = _adr.parse(text)
    assert _adr.problems(record) == [] and record["front"]["id"] == "ADR-0005" and record["front"]["governs"] == ["workitem.epic-e"]
    decision = _adr.first_sentence(record["sections"]["Decision"]).lower()
    assert "binding" in decision and ("derived" in decision or "generated" in decision)
    with open(os.path.join(ROOT, "docs", "adr", "0010-a-domain-feature-is-a-pack-of-the-registry.md"), encoding="utf-8") as f:
        head = f.read().split("---")[1]
    assert "workitem.epic-c" in head and "workitem.epic-e" in head, "ADR-0010 governs the data and policy epics"
    with open(os.path.join(ROOT, "roadmap", "graph.json"), encoding="utf-8") as f:
        edges = {(e["from"], e["rel"], e["to"]) for e in json.load(f)["edges"]}
    assert ("decision.adr-0010", "governs", "workitem.epic-c") in edges and ("decision.adr-0010", "governs", "workitem.epic-e") in edges
