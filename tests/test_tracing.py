"""Tracing (roadmap F1): spans for operations, behind the `otel` extra, never with a prompt or a
payload in them. Without OpenTelemetry installed every span is a no-op and nothing changes; with it,
the kg_* tools and the build stages open spans whose attributes pass the redaction policy, and the
audit record written inside a span carries its trace id, so an audit record links to its trace.

The policy is data (`tracing.REDACT_KEYS`, `tracing.MAX_CHARS`): a value whose name says it is text
someone wrote (a prompt, a body, a query) is replaced by its size and a hash; any other value is
scanned with the privacy detectors and what they find is masked; everything is cut at the cap."""
import contextlib
import io
import json
import os

import pytest

from oto import audit, tracing
from oto.cli import main
from oto.project import Project
from oto.scaffold import init


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(args))
    return code, out.getvalue()


# ---- the redaction policy, with or without OpenTelemetry ----

def test_text_someone_wrote_never_appears_in_a_span():
    for key in ("prompt", "body", "query", "arg.query", "statement", "reason", "note", "text", "payload"):
        out = tracing.redact(key, "Dana wrote: the acquirer's file format is not published, mail dana@example.com")
        assert "Dana" not in out and "example.com" not in out and "acquirer" not in out, (key, out)
        assert out.startswith("<redacted") and "chars" in out and len(out) < 80, out
    assert tracing.redact("prompt", "") == "<redacted: 0 chars>"
    assert tracing.redact("prompt", None) == ""


def test_other_values_are_scanned_and_what_the_detectors_find_is_masked():
    out = tracing.redact("tool", "kg_search")
    assert out == "kg_search", "a plain value stays"
    key = "AKIA" + "IOSFODNN7EXAMPLE"          # AWS's documented example key, assembled so no scanner reads the test as leaking one
    out = tracing.redact("identity", "Mina Okafor <mina@example.com>, card 4111 1111 1111 1111, key %s" % key)
    assert "mina@example.com" not in out and "4111 1111 1111 1111" not in out and key not in out, out
    assert "Mina Okafor" in out, "a name is not a detector's find; the policy is about secrets and identifiers"
    assert out.count("*") >= 10
    assert tracing.redact("n", 8) == "8" and tracing.redact("ok", True) == "True"
    long = tracing.redact("identity", "x" * 500)
    assert len(long) <= tracing.MAX_CHARS + 1 and long.endswith("…")


def test_attributes_flatten_arguments_and_apply_the_policy_by_name():
    attrs = tracing.attributes({"tool": "kg_search", "arguments": {"query": "who owns the ledger", "n": 8},
                                "nested": {"a": {"b": "c"}}, "items": ["x", "y"]})
    assert attrs["tool"] == "kg_search" and attrs["arguments.n"] == "8"
    assert attrs["arguments.query"].startswith("<redacted") and "ledger" not in attrs["arguments.query"]
    assert attrs["nested.a.b"] == "c" and attrs["items"] == '["x", "y"]'
    assert all(isinstance(v, str) for v in attrs.values()), "every attribute is a string, so no exporter re-encodes a payload"


def test_without_opentelemetry_or_a_switch_a_span_is_a_no_op():
    tracing.reset()
    with tracing.span("oto.test", prompt="secret") as s:
        assert s is None
    assert tracing.current_trace_id() is None
    assert tracing.enabled() is False


# ---- with OpenTelemetry installed: real spans, in memory ----

otel = pytest.mark.skipif(not tracing.available(), reason="OpenTelemetry is not installed (pip install 'oto-kg[otel]')")


@pytest.fixture
def exporter():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    memory = InMemorySpanExporter()
    tracing.configure(memory)
    yield memory
    tracing.reset()


@pytest.fixture
def plan(tmp_path):
    root = str(tmp_path / "plan")
    with contextlib.redirect_stdout(io.StringIO()):
        init(root, slug="plan", name="The plan", ontology="organization-process")
    return root


def _spans(exporter):
    return {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}


@otel
def test_a_tool_call_opens_a_span_with_redacted_arguments(exporter, plan):
    from test_apps import _engine
    from oto.builder import build
    project = Project.standard(plan)
    with contextlib.redirect_stdout(io.StringIO()):
        build(project)
    engine = _engine(project)
    reply = engine.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                            "params": {"name": "kg_search", "arguments": {"query": "ledger replica budget mina@example.com", "n": 3}}})
    assert reply and not reply["result"]["isError"]
    spans = _spans(exporter)
    assert "kg.search" in spans, list(spans)
    attrs = spans["kg.search"]
    assert attrs["tool"] == "kg_search" and attrs["arguments.n"] == "3"
    assert attrs["arguments.query"].startswith("<redacted") and "example.com" not in json.dumps(attrs), attrs
    assert "result.chars" in attrs and int(attrs["result.chars"]) > 0


@otel
def test_the_build_opens_a_span_per_stage(exporter, plan):
    from oto.builder import build, STAGES
    with contextlib.redirect_stdout(io.StringIO()):
        build(Project.standard(plan))
    spans = _spans(exporter)
    assert "oto.build" in spans and spans["oto.build"]["project"] == "plan"
    for name, _path in STAGES:
        assert "oto.build." + name in spans, name
    stage = [s for s in exporter.get_finished_spans() if s.name == "oto.build.knowledge"][0]
    root = [s for s in exporter.get_finished_spans() if s.name == "oto.build"][0]
    assert stage.parent is not None and stage.parent.span_id == root.context.span_id, "a stage is a child of the build"


@otel
def test_an_audit_record_written_inside_a_span_carries_its_trace_id(exporter, plan):
    from oto import tracing
    project = Project.standard(plan)
    with tracing.span("oto.test.write", item="process.onboarding"):
        audit.append(project, action="test write", principal="Chiheb Dkhil", nodes=["process.onboarding"], decision="applied",
                     detail="the reason is text someone wrote")
    record = audit.read(project)[-1]
    spans = [s for s in exporter.get_finished_spans() if s.name == "oto.test.write"]
    assert spans, [s.name for s in exporter.get_finished_spans()]
    assert record["trace_id"] == format(spans[0].context.trace_id, "032x") and len(record["trace_id"]) == 32
    assert "text someone wrote" not in json.dumps(dict(spans[0].attributes)), "what a person wrote never goes on a span"
    assert audit.verify(project)["ok"]


@otel
def test_tracing_is_switched_on_by_the_environment_and_off_by_default(monkeypatch):
    tracing.reset()
    monkeypatch.delenv("OTO_TRACE", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.enabled() is False
    monkeypatch.setenv("OTO_TRACE", "console")
    tracing.reset()
    assert tracing.enabled() is True
    with tracing.span("oto.test", tool="x") as s:
        assert s is not None and tracing.current_trace_id() and len(tracing.current_trace_id()) == 32
    tracing.reset()
