# -*- coding: utf-8 -*-
"""Tracing: spans for operations, behind the `otel` extra, never carrying what someone wrote (F1).

OpenTelemetry covers operations: how long a tool call or a build stage took, what it was about,
how one call led to another. The audit log (audit.py) covers accountability. The two link by the
trace id: an audit record written inside a span carries the span's trace id, so an auditor can go
from a record to its trace and an operator from a slow trace to what it changed.

Nothing here is a runtime dependency. Without the `opentelemetry` packages, or without the switch,
every span is a no-op and `current_trace_id()` is None: the engine stays stdlib-only for whoever
does not ask for tracing. With `pip install 'oto-kg[otel]'` and one of:

    OTO_TRACE=console                 spans to stderr, for a look
    OTO_TRACE=1 + OTEL_EXPORTER_OTLP_ENDPOINT   spans to a collector over OTLP/HTTP (the SDK reads the
                                                OTEL_* variables itself)
    tracing.configure(exporter)       a provider of the caller's (the tests use an in-memory one)

spans are real. Span names: `kg.<tool>` for a tool call, `oto.build` and `oto.build.<stage>` for a
build, `oto.work.<command>` for the work pack's writes (oto/packs/work).

The redaction policy is data, applied to every attribute before it reaches a span:

    REDACT_KEYS   an attribute whose name is, or ends in, one of these is text someone wrote (a
                  prompt, a body, a query, a reason): the span gets its size and a hash, never it
    other values  scanned with the privacy detectors (validate/privacy.py); what they find
                  (a credential, an email, a card number) is masked in place
    MAX_CHARS     everything is cut at the cap, so no payload travels as an attribute

A nested mapping flattens to dotted names (`arguments.query`), so a tool's arguments are judged
one by one by their own names.
"""
import contextlib
import hashlib
import json
import os
import re
import sys

from .validate import privacy

#: An attribute so named carries text someone wrote: never put in a span as written.
REDACT_KEYS = ("prompt", "body", "text", "payload", "query", "question", "statement", "statements", "note",
               "reason", "content", "message", "summary", "quote", "detail", "term", "label", "title")
MAX_CHARS = 120
ENV_SWITCH = "OTO_TRACE"
ENV_ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"

_provider = None          # the TracerProvider in use, once configured
_configured = False       # whether we looked at the environment yet


def available():
    """Are the OpenTelemetry API and SDK importable? The API alone makes no span."""
    try:
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.sdk import trace as _sdk  # noqa: F401
        return True
    except ImportError:
        return False


def reset():
    """Forget the provider and the switch (the tests, between cases)."""
    global _provider, _configured
    _provider, _configured = None, False


def configure(exporter):
    """Trace into `exporter` (an OpenTelemetry SpanExporter) through a provider of our own."""
    global _provider, _configured
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from . import __version__
    _provider = TracerProvider(resource=Resource.create({"service.name": "oto", "service.version": __version__}))
    _provider.add_span_processor(SimpleSpanProcessor(exporter))
    _configured = True
    return _provider


def _configure_from_env():
    """A provider from the environment, once: console, or OTLP/HTTP when an endpoint is set."""
    global _provider, _configured
    _configured = True
    switch = (os.environ.get(ENV_SWITCH) or "").strip().lower()
    endpoint = (os.environ.get(ENV_ENDPOINT) or "").strip()
    if not available() or not (switch or endpoint) or switch in ("0", "off", "no", "false"):
        return None
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    from . import __version__
    provider = TracerProvider(resource=Resource.create({"service.name": "oto", "service.version": __version__}))
    if switch == "console" or not endpoint:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            print("oto: tracing to %s needs the OTLP exporter: pip install 'oto-kg[otel]'" % endpoint, file=sys.stderr)
            return None
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _provider = provider
    return provider


def enabled():
    if not _configured:
        _configure_from_env()
    return _provider is not None


def _tracer():
    if not enabled():
        return None
    return _provider.get_tracer("oto")


# ---- the redaction policy ----

def _is_text(key):
    name = str(key).lower()
    last = name.rsplit(".", 1)[-1]
    return last in REDACT_KEYS or any(last.endswith("_" + k) for k in REDACT_KEYS)


def _masked(text):
    """Every detector's find masked in place; the rest as written."""
    for _kind, _severity, pattern, validator in privacy.DETECTORS:
        def swap(match, validator=validator):
            value = match.group(0)
            if validator and not validator(value):
                return value
            return privacy._mask(value)
        text = pattern.sub(swap, text)
    return text


def redact(key, value):
    """One attribute value, as the policy lets it into a span: a string, always."""
    if value is None:
        return ""
    if _is_text(key):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        if not text:
            return "<redacted: 0 chars>"
        return "<redacted: %d chars, sha256 %s>" % (len(text), hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    text = _masked(text)
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


def attributes(mapping, prefix=""):
    """A mapping flattened to dotted names, every value through `redact` by its own name."""
    out = {}
    for key, value in (mapping or {}).items():
        name = ("%s.%s" % (prefix, key)) if prefix else str(key)
        if isinstance(value, dict) and not _is_text(name):
            out.update(attributes(value, name))
        else:
            out[name] = redact(name, value)
    return out


# ---- spans ----

@contextlib.contextmanager
def span(name, **attrs):
    """A span named `name` with `attrs` through the policy; yields the span, or None when tracing
    is off. An exception inside is recorded on the span and raised."""
    tracer = _tracer()
    if tracer is None:
        yield None
        return
    from opentelemetry import trace
    with tracer.start_as_current_span(name) as s:
        for key, value in attributes(attrs).items():
            s.set_attribute(key, value)
        try:
            yield s
        except Exception as exc:
            s.record_exception(exc)
            s.set_status(trace.Status(trace.StatusCode.ERROR, type(exc).__name__))
            raise


def annotate(s, **attrs):
    """More attributes on an open span, through the policy; nothing when tracing is off."""
    if s is None:
        return
    for key, value in attributes(attrs).items():
        s.set_attribute(key, value)


def current_trace_id():
    """The trace id of the span we are in, as 32 hex characters, or None."""
    if not enabled():
        return None
    from opentelemetry import trace
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")
