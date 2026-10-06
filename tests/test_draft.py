"""The model-driven drafter: the one model call in OTO, optional, and reviewed like any proposal."""
import json
import os
import tempfile
import types

import pytest

from oto import draft
from oto.cli import main
from oto.project import Project
from oto.scaffold import init

DOC = "# Fraud memo\n\nThe Fraud Unit reports to the Claims Manager as of 2026-03-15.\n"


def _project(root):
    init(root, name="KB", ontology="auto-claims")
    project = Project.standard(root)
    os.makedirs(project.layout.corpus, exist_ok=True)
    with open(os.path.join(project.layout.corpus, "fraud-memo.md"), "w", encoding="utf-8") as f:
        f.write(DOC)
    return project


def _message(text=None, stop_reason="end_turn", model="claude-opus-5"):
    block = types.SimpleNamespace(type="text", text=text or "")
    usage = types.SimpleNamespace(input_tokens=1200, output_tokens=300)
    return types.SimpleNamespace(stop_reason=stop_reason, content=[block] if text is not None else [],
                                 model=model, usage=usage, stop_details=None)


class FakeStream:
    def __init__(self, message):
        self.message = message
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def get_final_message(self):
        return self.message


class FakeClient:
    """Records the request and answers with a canned message, so no network is involved."""
    def __init__(self, message):
        self.message, self.requests = message, []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=self._stream))
    def _stream(self, **request):
        self.requests.append(request)
        return FakeStream(self.message)


GOOD = {"source_doc": "fraud-memo", "as_of": "2026-03-15",
        "nodes": [{"id": "role.fraud-unit-lead", "type": "Role", "label": "Fraud unit lead",
                   "evidence": [{"doc": "fraud-memo", "where": "§1", "quote": "The Fraud Unit reports to the Claims Manager"}]}],
        "edges": [],
        "report": {"document_date_basis": "the date in the memo's first sentence", "reused_ids": [],
                   "supersessions": [], "contradictions": [], "needs_vocabulary": ["Unit: the Fraud Unit is an organisational unit, no class covers it"],
                   "inferences": [], "not_asserted": ["who leads the unit"], "unsure": []}}


def test_the_request_carries_the_rules_the_vocabulary_the_brief_and_the_whole_document():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        request = draft.build_request(project, "fraud-memo")
    assert request["model"] == "claude-opus-5" and request["max_tokens"] == draft.MAX_OUTPUT_TOKENS
    assert "Only what the document states" in request["system"] and "evidence" in request["system"]
    user = request["messages"][0]["content"]
    assert "Classes:" in user and "Claim:" in user and "Relations (domain -> range):" in user
    assert "Attributes (per class, with type):" in user and "Claim.state: scheme:ClaimState (one of: open, reopened, closed, denied)" in user
    assert "The brief for this document" in user and "Claims Manager" in user
    assert DOC.strip() in user, "the whole document, never truncated"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"] == draft.SCHEMA
    assert request["output_config"]["effort"] == "high"
    assert request["betas"] == [draft.FALLBACK_BETA] and request["fallbacks"] == "default"
    assert "thinking" not in request, "adaptive thinking is the model's default; nothing to disable"


def test_a_missing_document_is_a_draft_error():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with pytest.raises(draft.DraftError, match="no document"):
            draft.build_request(project, "nope")


def test_parse_reads_the_json_and_names_a_refusal_or_a_cut_off():
    assert draft.parse_response(_message(json.dumps(GOOD)))["source_doc"] == "fraud-memo"
    refusal = _message(None, stop_reason="refusal")
    refusal.stop_details = types.SimpleNamespace(category="cyber", explanation="declined")
    with pytest.raises(draft.DraftError, match="declined"):
        draft.parse_response(refusal)
    with pytest.raises(draft.DraftError, match="cut off"):
        draft.parse_response(_message("{", stop_reason="max_tokens"))
    with pytest.raises(draft.DraftError, match="not valid JSON"):
        draft.parse_response(_message("not json"))
    with pytest.raises(draft.DraftError, match="not a proposal"):
        draft.parse_response(_message(json.dumps({"hello": 1})))


def test_run_writes_the_proposal_with_its_drafter_and_a_dry_run_report():
    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        client = FakeClient(_message(json.dumps(GOOD)))
        path, proposal, report, usage = draft.run(project, "fraud-memo", client=client)
        assert client.requests[0]["messages"][0]["content"].endswith("`fraud-memo`.")
        assert path.endswith(os.path.join("proposals", "fraud-memo.json"))
        written = json.load(open(path, encoding="utf-8"))
        assert written["drafted_by"]["model"] == "claude-opus-5" and "first draft" in written["drafted_by"]["note"]
        assert written["source_doc"] == "fraud-memo"
        assert report["added"] == ["role.fraud-unit-lead"] and usage.output_tokens == 300
        with pytest.raises(draft.DraftError, match="--force"):
            draft.run(project, "fraud-memo", client=client)
        draft.run(project, "fraud-memo", client=client, force=True)
        # What it wrote is a proposal like any other: the merge accepts it.
        assert main(["curate", "start", "--project", root]) == 0
        assert main(["curate", "add", "--project", root, "--from", path, "--dry-run"]) == 0


def test_an_sdk_error_is_reported_as_a_draft_error_not_a_traceback():
    class Boom(Exception):
        pass
    Boom.__module__ = "anthropic._exceptions"

    class FailingClient(FakeClient):
        def _stream(self, **request):
            raise Boom("rate limited")

    with tempfile.TemporaryDirectory() as root:
        project = _project(root)
        with pytest.raises(draft.DraftError, match="Boom.*rate limited"):
            draft.run(project, "fraud-memo", client=FailingClient(None))


def test_cli_without_the_extra_says_how_to_install_it(monkeypatch, capsys):
    monkeypatch.setattr(draft, "available", lambda: False)
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        capsys.readouterr()
        assert main(["draft", "fraud-memo", "--project", root]) == 1
        assert "oto-kg[draft]" in capsys.readouterr().err


def test_cli_reports_the_draft_and_the_reviewers_next_step(monkeypatch, capsys):
    monkeypatch.setattr(draft, "call", lambda client, request: _message(json.dumps(GOOD)))
    monkeypatch.setattr(draft, "available", lambda: True)
    import sys
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda: object()))
    with tempfile.TemporaryDirectory() as root:
        _project(root)
        capsys.readouterr()
        assert main(["draft", "fraud-memo", "--project", root]) == 0
        out = capsys.readouterr().out
        assert "drafted proposals/fraud-memo.json with claude-opus-5" in out
        assert "tokens: 1200 in, 300 out" in out
        assert "needs vocabulary:" in out and "Fraud Unit" in out
        assert "oto curate add --from proposals/fraud-memo.json --dry-run" in out


def test_the_base_install_never_imports_the_sdk():
    """The compile and serve paths stay standard-library; only `oto draft` reaches for the model."""
    import subprocess, sys
    code = ("import sys, oto.cli, oto.builder, oto.serve.engine, oto.curate.batch, oto.intake.pipeline; "
            "print('anthropic' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={"PATH": os.environ.get("PATH", ""), "OTO_ONTOLOGIES": os.environ.get("OTO_ONTOLOGIES", "")})
    assert out.stdout.strip() == "False", out.stderr
