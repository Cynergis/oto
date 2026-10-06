# -*- coding: utf-8 -*-
"""Draft a document's proposal with a model, for review by a person and the gates.

Everything else in OTO is standard library and never calls a model. This module is the one
exception, and it is optional: it needs the `draft` extra (`pip install "oto-kg[draft] @ ..."`)
and an Anthropic credential, and nothing imports it unless `oto draft` is run. It exists for
volume, and for hosts with no interactive agent: a workflow can draft a hundred documents while a
person reviews, where a Claude Code session would read them one at a time.

What it produces is exactly what a drafter produces: `proposals/<slug>.json`, with evidence on
every fact, in the vocabulary's classes, reusing the ids the brief matched. Nothing about the
gates changes. The proposal is dry-run merged so the report a person reads is the same report a
hand-written proposal gets, and the file records which model drafted it. The reviewer still reads
the document; a model's draft is a first draft, not a fact.

The request: the drafting rules as the system prompt, the vocabulary, the brief, and the full
document as the user turn; the response constrained to the proposal's JSON schema, so the model
cannot answer in prose. Claude Opus 5 by default, adaptive thinking (the model's default), high
effort, streamed so a long document does not hit a request timeout, and Anthropic's server-side
refusal fallback enabled so a declined request is re-run on a substitute rather than failing.
"""
import datetime
import json
import os

DEFAULT_MODEL = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_OUTPUT_TOKENS = 64000


class DraftError(Exception):
    """The model could not produce a usable proposal, and why."""


def available():
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


SYSTEM = """You draft the facts one document asserts, for a knowledge graph that a person will review.
You do not decide what enters the graph. Be faithful to the document and easy to check.

Rules, none of which bend:
1. Only what the document states. If it implies something but does not state it, leave it out, or
   include it with "source_type": "inference" and a note in `report.inferences`. A confident wrong
   fact is worse than a missing one.
2. A thing with identity, dates or relationships is a node. A value about a thing is an attribute on
   its node, using the attribute names and types the vocabulary declares for that class. Prefer
   attributes; they are cheaper.
3. Every node's `type` is a class the vocabulary declares. If the document names a kind of thing no
   class covers, do not invent a class and do not force it into the wrong one: list it in
   `report.needs_vocabulary` and leave the fact out.
4. Reuse ids. The brief lists the terms of this document and the entity id the graph already holds
   for each. A matched term is listed with the existing id and nothing new but `evidence` and any
   alias the document adds; do not restate its label or summary. A new entity gets a new id:
   lowercase, dotted, `<class>.<label-slug>`, stable, never a number.
5. When the document contradicts a fact the graph holds and is newer, write the supersession: the old
   id with "status": "superseded", "valid_to" and "superseded_by"; a new id with "supersedes", its own
   "valid_from", a "change_note" in the document's words, and evidence. When you cannot tell which is
   newer, do not supersede; list it in `report.contradictions`.
6. Every node you introduce carries `evidence`: `{"doc": <slug>, "where": <page, section or slide>,
   "quote": <the sentence that says it>}`. Every edge uses a declared relation whose domain and range
   fit the two nodes' classes. Dates are YYYY-MM-DD or absent, never guessed.
7. The report is for the reviewer: what the document does not say that a reader might assume, and
   anything you were unsure about. Be generous; that is what the review is for."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["source_doc", "as_of", "nodes", "edges", "report"],
    "properties": {
        "source_doc": {"type": "string"},
        "as_of": {"type": "string", "description": "the document's own date, YYYY-MM-DD; today if it has none"},
        "nodes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id"],
            "properties": {
                "id": {"type": "string"}, "type": {"type": "string"}, "label": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "attributes": {"type": "object", "additionalProperties": True},
                "tags": {"type": "array", "items": {"type": "string"}},
                "valid_from": {"type": "string"}, "valid_to": {"type": "string"},
                "status": {"type": "string", "enum": ["current", "superseded", "proposed"]},
                "supersedes": {"type": "string"}, "superseded_by": {"type": "string"},
                "change_note": {"type": "string"},
                "source_type": {"type": "string", "enum": ["document", "inference"]},
                "evidence": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["doc", "where", "quote"],
                    "properties": {"doc": {"type": "string"}, "where": {"type": "string"}, "quote": {"type": "string"}}}}}}},
        "edges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["from", "rel", "to"],
            "properties": {"from": {"type": "string"}, "rel": {"type": "string"}, "to": {"type": "string"}}}},
        "report": {"type": "object", "additionalProperties": False,
                   "required": ["document_date_basis", "reused_ids", "supersessions", "contradictions",
                                "needs_vocabulary", "inferences", "not_asserted", "unsure"],
                   "properties": {k: ({"type": "string"} if k == "document_date_basis"
                                      else {"type": "array", "items": {"type": "string"}})
                                  for k in ("document_date_basis", "reused_ids", "supersessions", "contradictions",
                                            "needs_vocabulary", "inferences", "not_asserted", "unsure")}},
    },
}


def vocabulary_text(config):
    lines = ["Classes:"]
    for name, spec in (config.get("classes") or {}).items():
        lines.append("  %s: %s" % (name, spec.get("definition") or ""))
    lines.append("Relations (domain -> range):")
    for name, spec in (config.get("properties") or {}).items():
        lines.append("  %s: %s -> %s. %s" % (name, spec.get("domain") or "?", spec.get("range") or "?", spec.get("definition") or ""))
    attributes = config.get("attributes") or {}
    if attributes:
        lines.append("Attributes (per class, with type):")
        from .model.vocabulary import concepts_of
        for kind, declared in attributes.items():
            for attr, spec in declared.items():
                allowed = concepts_of(spec["type"], config.get("schemes") or {}) if str(spec["type"]).startswith("scheme:") else None
                lines.append("  %s.%s: %s%s. %s" % (kind, attr, spec["type"],
                                                    " (one of: %s)" % ", ".join(allowed) if allowed else "", spec.get("definition") or ""))
    return "\n".join(lines)


def build_request(project, slug, model=DEFAULT_MODEL):
    """The request for one document, as a dict the caller passes to the SDK. Pure: no network."""
    from .curate import session as _session
    from .intake.survey import brief, brief_report

    with open(project.ontology_config_path, encoding="utf-8") as f:
        config = json.load(f)
    path = os.path.join(project.layout.corpus, slug + ".md")
    if not os.path.exists(path):
        raise DraftError("no document %s.md in the corpus; run `oto ingest` first" % slug)
    with open(path, encoding="utf-8") as f:
        document = f.read()
    candidate = _session.candidate(project) if _session.exists(project) else None
    the_brief = brief_report(brief(project.layout.corpus, slug, _session.live(project), candidate))

    user = ("The vocabulary this graph declares. Use only these classes, relations and attributes.\n\n"
            + vocabulary_text(config)
            + "\n\nThe brief for this document: its terms, and the entity id the graph already holds for each.\n\n"
            + the_brief
            + "\n\nThe document, slug `%s`, in full:\n\n" % slug + document
            + "\n\nDraft its proposal. `source_doc` is `%s`." % slug)
    return {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def call(client, request):
    """Send the request, streamed, and return the final message. Separated so a test can inject a
    fake client and the real path stays three lines."""
    with client.beta.messages.stream(**request) as stream:
        return stream.get_final_message()


def parse_response(message):
    """The proposal dict from a response, or DraftError saying why there is none."""
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        why = getattr(details, "explanation", None) or getattr(details, "category", None) or "no reason given"
        raise DraftError("the model declined this document: %s" % why)
    if message.stop_reason == "max_tokens":
        raise DraftError("the draft was cut off at %d output tokens; split the document" % MAX_OUTPUT_TOKENS)
    text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), None)
    if text is None:
        raise DraftError("the response held no text block")
    try:
        proposal = json.loads(text)
    except ValueError as exc:
        raise DraftError("the response was not valid JSON: %s" % exc)
    if not isinstance(proposal, dict) or "nodes" not in proposal:
        raise DraftError("the response is not a proposal")
    return proposal


def review(project, proposal, today):
    """Dry-run merge the proposal, so the report a person reads is the one any proposal gets."""
    from .curate import batch, session as _session

    graph = _session.candidate(project) if _session.exists(project) else _session.live(project)
    _merged, report = batch.merge(graph, proposal, today)
    return report


def run(project, slug, model=DEFAULT_MODEL, client=None, force=False):
    """Draft one document: request, call, parse, dry-run, write. Returns (path, proposal, report, usage)."""
    if client is None:
        if not available():
            raise DraftError("the draft extra is not installed: pip install \"oto-kg[draft] @ git+<the engine repository>\"")
        import anthropic
        client = anthropic.Anthropic()          # credentials from the environment
    proposals = os.path.join(os.path.dirname(project.src), "proposals")
    os.makedirs(proposals, exist_ok=True)
    out = os.path.join(proposals, slug + ".json")
    if os.path.exists(out) and not force:
        raise DraftError("%s exists; pass --force to redraft over it" % os.path.relpath(out, os.path.dirname(project.src)))

    request = build_request(project, slug, model=model)
    try:
        message = call(client, request)
    except Exception as exc:                       # noqa: BLE001 - the SDK's own errors, reported plainly
        if type(exc).__module__.startswith("anthropic"):
            raise DraftError("the API call failed (%s): %s" % (type(exc).__name__, exc))
        raise
    proposal = parse_response(message)
    proposal["source_doc"] = slug
    today = datetime.date.today().isoformat()
    proposal["drafted_by"] = {"model": getattr(message, "model", model), "at": today,
                              "note": "a model's first draft; a person reviews it against the document"}
    report = review(project, proposal, today)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    usage = getattr(message, "usage", None)
    return out, proposal, report, usage
