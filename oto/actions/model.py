# -*- coding: utf-8 -*-
"""The action file: `actions/<id>.json`, one action each, authored and versioned like a rule.

    {
      "id": "action.check-repository",
      "label": "Check that a repository exists",
      "description": "Reads the repository's metadata and records whether it exists.",
      "subject": "Repository",
      "executed_by": "team.payments",
      "annotations": {"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true},
      "inputSchema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
                      "required": ["owner", "repo"]},
      "bind": {"owner": "$attr.owner", "repo": "$attr.name"},
      "when": [{"node": "r", "type": "Repository", "where": {"status": "intended"}}],
      "invoke": {"transport": "mcp", "server": "github", "tool": "get_repository"},
      "needs": ["GITHUB_TOKEN"],
      "result": {"kind": "proposal", "then": {"node": "$subject", "status": "current",
                                              "attributes": {"default_branch": "$response.default_branch"}}},
      "schedule": "daily"
    }

`label`, `description`, `inputSchema` and `annotations` are MCP's tool shape and are returned as
they are. `subject` is the class the action acts on; `bind` fills inputs from the subject node's
own fields only (`$attr.<name>`, `$id`, `$label`); `when` is the rules' pattern language, whose
first pattern must bind the subject; `invoke` is declared, never performed; `needs` names
environment variables, never values; `result` says how a recorded response becomes a document in
the inbox or a proposal, and `result.require` lists the response paths that must be present or no
proposal is written (a "not found" answer must not realise a fact); `schedule` is allowed on a
read-only action only.

At build time each action becomes an `Action` node whose source is its file, with an
`executed_by` edge. Nothing here writes `graph.json`.
"""
import json
import os
import re

DIR = "actions"
ID_OK = re.compile(r"^action\.[a-z0-9][a-z0-9-]*$")
ENV_OK = re.compile(r"^[A-Z][A-Z0-9_]*$")
TRANSPORTS = {"mcp": ("server", "tool"), "cli": ("command",), "http": ("method", "url"), "script": ("path",)}
RESULT_KINDS = ("document", "proposal")
ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")
SCHEDULES = ("hourly", "daily", "weekly")
BIND_OK = re.compile(r"^\$(id|label|attr\.[A-Za-z0-9_-]+)$")
CLASS = "Action"


def directory(project):
    return os.path.join(project.data, DIR)


def load(project):
    """Every action file, sorted by file name: [(relative path, dict or None, error)]."""
    return load_dir(directory(project))


def load_dir(root):
    """The action files under one directory, sorted by file name."""
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json") or name.startswith("."):
            continue
        rel = os.path.join(DIR, name)
        try:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                payload = json.load(f)
        except ValueError as exc:
            out.append((rel, None, "not JSON: %s" % exc))
            continue
        if not isinstance(payload, dict):
            out.append((rel, None, "must be one object"))
            continue
        out.append((rel, payload, None))
    return out


def read_only(action):
    return bool((action.get("annotations") or {}).get("readOnlyHint"))


def subject_variable(action):
    """The variable the first `when` pattern binds, which is the subject."""
    when = action.get("when") or []
    if when and isinstance(when[0], dict) and "node" in when[0]:
        return when[0]["node"]
    return None


def problems(loaded, vocabulary):
    """What is wrong with the action files, before anything is listed. Empty means usable."""
    from ..reason import rules as _rules
    classes = (vocabulary or {}).get("classes") or {}
    properties = (vocabulary or {}).get("properties") or {}
    out = []
    if loaded and CLASS not in classes:
        out.append("class %r is not declared in ontology.config.json; actions need it (oto-core declares it: "
                   "`oto ontology diff` shows the upstream change, or add the class by hand)" % CLASS)
    for rel in ("acts_on", "executed_by"):
        if loaded and rel not in properties:
            out.append("relation %r is not declared; actions need it (oto-core declares it)" % rel)
    seen = set()
    for rel, action, error in loaded:
        label = rel
        if error:
            out.append("%s: %s" % (label, error))
            continue
        aid = action.get("id")
        if not isinstance(aid, str) or not ID_OK.match(aid):
            out.append("%s: `id` must look like action.<kebab-name>" % label)
        elif aid in seen:
            out.append("%s: duplicate id %r" % (label, aid))
        elif os.path.basename(rel) != aid + ".json":
            out.append("%s: the file must be named after its id: %s.json" % (label, aid))
        seen.add(aid)
        for field in ("label", "description"):
            if not isinstance(action.get(field), str) or not action[field].strip():
                out.append("%s: `%s` is required" % (label, field))
        subject = action.get("subject")
        if not isinstance(subject, str) or not subject:
            out.append("%s: `subject` must name the class the action acts on" % label)
        elif subject not in classes:
            out.append("%s: subject class %r is not declared" % (label, subject))
        by = action.get("executed_by")
        if by is not None and (not isinstance(by, str) or not by.strip()):
            out.append("%s: `executed_by` must be a node id (a team)" % label)
        annotations = action.get("annotations")
        if not isinstance(annotations, dict):
            out.append("%s: `annotations` is required: MCP's readOnlyHint at least" % label)
        else:
            for key, value in annotations.items():
                if key not in ANNOTATIONS:
                    out.append("%s: annotation %r is not one of %s" % (label, key, ", ".join(ANNOTATIONS)))
                elif not isinstance(value, bool):
                    out.append("%s: annotation %r must be true or false" % (label, key))
            if "readOnlyHint" not in annotations:
                out.append("%s: annotations must say readOnlyHint, true or false" % label)
        schema = action.get("inputSchema")
        props = {}
        if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            out.append("%s: `inputSchema` must be a JSON schema object with `properties`" % label)
        else:
            props = schema["properties"]
            for name in schema.get("required") or []:
                if name not in props:
                    out.append("%s: inputSchema requires %r, which it does not declare" % (label, name))
        bind = action.get("bind") or {}
        if not isinstance(bind, dict):
            out.append("%s: `bind` must map input names to $id, $label or $attr.<name>" % label)
        else:
            for name, source in bind.items():
                if props and name not in props:
                    out.append("%s: bind names input %r, which inputSchema does not declare" % (label, name))
                if not isinstance(source, str) or not BIND_OK.match(source):
                    out.append("%s: bind for %r must be $id, $label or $attr.<name> (the subject's own fields only)" % (label, name))
        when = action.get("when")
        if not isinstance(when, list) or not when:
            out.append("%s: `when` must be a non-empty list of patterns, the first binding the subject" % label)
        else:
            first = when[0] if isinstance(when[0], dict) else {}
            if "node" not in first or first.get("type") != subject:
                out.append("%s: the first `when` pattern must be {\"node\": <var>, \"type\": %r}" % (label, subject))
            pseudo = {"id": aid or "?", "kind": "policy", "when": when, "then": {"flag": "ready"}, "why": "readiness"}
            for problem in _rules.problems([pseudo], vocabulary or {}):
                out.append("%s: when: %s" % (label, problem.split(": ", 1)[-1]))
        invoke = action.get("invoke")
        if not isinstance(invoke, dict) or invoke.get("transport") not in TRANSPORTS:
            out.append("%s: `invoke.transport` must be one of %s" % (label, ", ".join(TRANSPORTS)))
        else:
            for key in TRANSPORTS[invoke["transport"]]:
                if not isinstance(invoke.get(key), str) or not invoke[key].strip():
                    out.append("%s: invoke.%s is required for the %s transport" % (label, key, invoke["transport"]))
            if invoke["transport"] == "script":
                path = os.path.join(os.path.dirname(rel), invoke.get("path") or "")
                if ".." in (invoke.get("path") or "") or os.path.isabs(invoke.get("path") or ""):
                    out.append("%s: invoke.path must be relative, under actions/" % label)
        needs = action.get("needs") or []
        if not isinstance(needs, list) or not all(isinstance(n, str) and ENV_OK.match(n) for n in needs):
            out.append("%s: `needs` must list environment variable names (UPPER_SNAKE), never values" % label)
        result = action.get("result")
        if not isinstance(result, dict) or result.get("kind") not in RESULT_KINDS:
            out.append("%s: `result.kind` must be document or proposal" % label)
        elif result["kind"] == "proposal":
            then = result.get("then")
            if not isinstance(then, dict) or then.get("node") != "$subject":
                out.append("%s: result.then must describe the subject: {\"node\": \"$subject\", ...}" % label)
            else:
                status = then.get("status")
                if status is not None and status not in ("current", "intended", "superseded"):
                    out.append("%s: result.then.status must be current, intended or superseded" % label)
                if "attributes" in then and not isinstance(then["attributes"], dict):
                    out.append("%s: result.then.attributes must be an object" % label)
            require = result.get("require")
            if require is not None and (not isinstance(require, list) or not all(isinstance(r, str) and r.startswith("$response") for r in require)):
                out.append("%s: result.require must list $response.<path> values that must be present for the proposal" % label)
        timeout = action.get("timeout")
        if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0 or timeout > 3600):
            out.append("%s: `timeout` must be a number of seconds between 1 and 3600" % label)
        schedule = action.get("schedule")
        if schedule is not None:
            if schedule not in SCHEDULES:
                out.append("%s: schedule must be one of %s" % (label, ", ".join(SCHEDULES)))
            elif not read_only(action):
                out.append("%s: only a read-only action (readOnlyHint true) may carry a schedule" % label)
    return out


def node_for(rel, action):
    """The `Action` node an action file becomes at build time. Its source is the file."""
    annotations = dict(action.get("annotations") or {})
    invoke = dict(action.get("invoke") or {})
    attributes = {"subject": action.get("subject"), "transport": invoke.get("transport"),
                  "read_only": bool(annotations.get("readOnlyHint")),
                  "destructive": bool(annotations.get("destructiveHint")),
                  "idempotent": bool(annotations.get("idempotentHint")),
                  "needs": list(action.get("needs") or []),
                  "result": (action.get("result") or {}).get("kind")}
    if action.get("schedule"):
        attributes["schedule"] = action["schedule"]
    attributes["definition"] = json.loads(json.dumps(action))     # the whole file, for the catalog
    return {"id": action["id"], "type": CLASS, "label": action["label"], "aliases": [],
            "summary": action.get("description") or "", "attributes": attributes, "tags": ["action"],
            "status": "current", "source_doc": rel, "sources": [rel],
            "evidence": [{"doc": rel, "where": "file", "quote": (action.get("description") or "")[:200]}]}


def nodes_and_edges(loaded):
    """The nodes and edges every readable action file contributes; unreadable ones are skipped
    (the check names them)."""
    nodes, edges = [], []
    for rel, action, error in loaded:
        if error or not isinstance(action.get("id"), str) or not action.get("label"):
            continue
        nodes.append(node_for(rel, action))
        if action.get("executed_by"):
            edges.append({"from": action["id"], "rel": "executed_by", "to": action["executed_by"]})
    return nodes, edges
