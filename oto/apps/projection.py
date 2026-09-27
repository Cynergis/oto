# -*- coding: utf-8 -*-
"""The projection language: the graph payload, shaped the way one app wants it.

A projection is JSON. Plain objects and lists recurse; a string that starts with `$` is a field
path resolved against the row in scope; an object with a `$`-key is an operator. It is evaluated
by the engine over the payload `serve/payload.py` builds, so it is the same live and static and
needs no browser to test.

    "$id"  "$label"  "$summary"  "$status"  "$type"  "$as_of"  "$valid_from"  "$valid_to"
    "$source_doc"  "$sources"  "$tags"  "$aliases"  "$evidence"  "$degree"  "$attrs"  "$attr.<name>"
    "$row"                                   the whole row in scope
    "$rel"  "$derived_by"  "$edge_status"    inside $out / $in: the edge that was followed

    {"$nodes": "Class" | ["A", "B"], "$where": {...}, "$sort": "-attr.date", "$limit": 5,
     "$history": true, "$map": {...} | "$field": "$label" | "$group": "attr.status"}
    {"$out": "rel" | ["rel", "rel2"], "$select": "$id" | {...}, "$derived": "include|exclude|mark",
     "$where": {...}, "$sort": ..., "$limit": ..., "$history": true}        (and "$in")
    {"$first": expr}  {"$count": expr}  {"$const": value}  {"$concat": [exprs]}
    {"$format": "{label} ({id})"}            field paths in braces, no `$`
    {"$lexicon": true}  {"$documents": true}  {"$findings": true}  {"$ledger": true}
    {"$edges": true}  {"$pending": true}     the payload's other parts, with $where/$sort/$limit/$map
    {"$graph": true}                         the whole payload, for an app that reads it as is
    {"$payload": "counts.by_class"}          one top-level field of the payload, dotted path allowed
    {"$include": "relative/file.json"}       a projection kept in its own file

`$where` is a map of field path (no `$`) to a value, or to {"$in": [...]}, {"$ne": v},
{"$exists": bool}, {"$contains": "text"}. Superseded facts are excluded unless `$history` is true.
"""
import json
import os


class ProjectionError(ValueError):
    """A projection that cannot be evaluated; the message names the operator and the reason."""


ROW_KEYS = ("id", "label", "summary", "status", "type", "as_of", "valid_from", "valid_to", "source_doc",
            "sources", "tags", "aliases", "evidence", "degree", "supersedes", "superseded_by")
LIST_OPS = ("$nodes", "$out", "$in", "$lexicon", "$documents", "$findings", "$ledger", "$edges", "$pending")


class Projector:
    def __init__(self, payload, base_dir=None):
        self.payload = payload
        self.base_dir = base_dir
        self.by_id = {n["id"]: n for n in payload.get("nodes") or []}
        self.out_edges, self.in_edges = {}, {}
        for e in payload.get("edges") or []:
            self.out_edges.setdefault(e["from"], []).append(e)
            self.in_edges.setdefault(e["to"], []).append(e)

    # ---- entry ----
    def evaluate(self, expr, row=None, edge=None):
        if isinstance(expr, str):
            return self.path(expr, row, edge) if expr.startswith("$") else expr
        if isinstance(expr, list):
            return [self.evaluate(x, row, edge) for x in expr]
        if isinstance(expr, dict):
            if any(k.startswith("$") for k in expr):
                return self.operator(expr, row, edge)
            return {k: self.evaluate(v, row, edge) for k, v in expr.items()}
        return expr

    # ---- field paths ----
    def path(self, text, row=None, edge=None):
        name = text[1:]
        if name == "row":
            return row
        if edge is not None:
            if name == "rel":
                return edge.get("rel")
            if name == "derived_by":
                return edge.get("derived_by")
            if name == "edge_status":
                return edge.get("status")
        if row is None:
            raise ProjectionError("field path %r used outside a row (put it under $map or $select)" % text)
        if name == "attrs":
            return row.get("attributes") or {}
        if name.startswith("attr."):
            return (row.get("attributes") or {}).get(name[5:])
        if "." in name:
            head, rest = name.split(".", 1)
            value = row.get(head)
            for part in rest.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        return row.get(name)

    def _field(self, path_no_dollar, row):
        return self.path("$" + path_no_dollar, row)

    # ---- operators ----
    def operator(self, expr, row, edge):
        if "$include" in expr:
            return self.evaluate(self._include(expr["$include"]), row, edge)
        if "$const" in expr:
            return expr["$const"]
        if "$graph" in expr:
            return self.payload
        if "$payload" in expr:
            value = self.payload
            for part in str(expr["$payload"]).split("."):
                value = value.get(part) if isinstance(value, dict) else None
            return value
        if "$nodes" in expr:
            return self._collection(expr, self._nodes(expr), row)
        if "$out" in expr or "$in" in expr:
            return self._neighbours(expr, row)
        for key, source in (("$lexicon", self._lexicon), ("$documents", lambda: list(self.payload.get("documents") or [])),
                            ("$findings", lambda: list(self.payload.get("findings") or [])),
                            ("$ledger", lambda: list(self.payload.get("ledger") or [])),
                            ("$edges", lambda: list(self.payload.get("edges") or [])),
                            ("$pending", lambda: list(self.payload.get("pending") or []))):
            if key in expr:
                return self._collection(expr, source(), row)
        if "$first" in expr:
            value = self.evaluate(expr["$first"], row, edge)
            return value[0] if isinstance(value, list) and value else (None if isinstance(value, list) else value)
        if "$count" in expr:
            value = self.evaluate(expr["$count"], row, edge)
            return len(value) if isinstance(value, (list, dict)) else (0 if value in (None, "") else 1)
        if "$concat" in expr:
            parts = self.evaluate(expr["$concat"], row, edge)
            return "".join("" if p is None else str(p) for p in parts)
        if "$format" in expr:
            return self._format(expr["$format"], row, edge)
        unknown = sorted(k for k in expr if k.startswith("$"))
        raise ProjectionError("unknown operator %s" % ", ".join(unknown))

    def _include(self, rel):
        if not self.base_dir:
            raise ProjectionError("$include %r needs the app directory" % rel)
        base = os.path.abspath(self.base_dir)
        path = os.path.abspath(os.path.join(base, rel))
        if not path.startswith(base + os.sep):
            raise ProjectionError("$include %r leaves the app directory" % rel)
        if not os.path.exists(path):
            raise ProjectionError("$include %r: no such file" % rel)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _format(self, template, row, edge):
        out, i = [], 0
        while i < len(template):
            j = template.find("{", i)
            if j < 0:
                out.append(template[i:]); break
            k = template.find("}", j)
            if k < 0:
                out.append(template[i:]); break
            out.append(template[i:j])
            value = self.path("$" + template[j + 1:k], row, edge)
            out.append("" if value is None else str(value))
            i = k + 1
        return "".join(out)

    # ---- collections ----
    def _nodes(self, expr):
        classes = expr["$nodes"]
        if isinstance(classes, str):
            classes = [classes]
        if classes == ["*"]:
            return list(self.by_id.values())
        return [n for n in self.payload.get("nodes") or [] if n.get("type") in classes]

    def _lexicon(self):
        grouped = {}
        for r in self.payload.get("lexicon") or []:
            entry = grouped.setdefault(r["canonical"], {"term": r["canonical"], "phrases": [], "targets": [],
                                                        "status": r.get("status"), "note": r.get("note")})
            if r.get("phrase") and r["phrase"] not in entry["phrases"]:
                entry["phrases"].append(r["phrase"])
            if r.get("target") and r["target"] not in entry["targets"]:
                entry["targets"].append(r["target"])
        return list(grouped.values())

    def _collection(self, expr, rows, outer_row):
        history = bool(expr.get("$history"))
        if not history:
            rows = [r for r in rows if r.get("status") != "superseded"]
        if "$where" in expr:
            rows = [r for r in rows if self._matches(expr["$where"], r)]
        if "$sort" in expr:
            rows = self._sorted(rows, expr["$sort"])
        if "$limit" in expr:
            rows = rows[:int(expr["$limit"])]
        if "$group" in expr:
            groups = {}
            for r in rows:
                groups.setdefault(self._field(expr["$group"], r), []).append(r)
            keys = sorted(groups, key=lambda k: (k is None, str(k)))
            return [{"key": k, "items": [self._shape(expr, r) for r in groups[k]]} for k in keys]
        return [self._shape(expr, r) for r in rows]

    def _shape(self, expr, r, edge=None):
        if "$map" in expr:
            return self.evaluate(expr["$map"], r, edge)
        if "$field" in expr:
            return self.evaluate(expr["$field"], r, edge)
        if "$select" in expr:
            return self.evaluate(expr["$select"], r, edge)
        return r

    def _neighbours(self, expr, row):
        if row is None:
            raise ProjectionError("$out / $in used outside a row")
        direction = "$out" if "$out" in expr else "$in"
        rels = expr[direction]
        if isinstance(rels, str):
            rels = [rels]
        history = bool(expr.get("$history"))
        derived = expr.get("$derived", "include")
        edges = (self.out_edges if direction == "$out" else self.in_edges).get(row["id"], [])
        out = []
        for e in edges:
            if rels != ["*"] and e["rel"] not in rels:
                continue
            if e.get("status") == "superseded" and not history:
                continue
            if e.get("status") == "derived" and derived == "exclude":
                continue
            other = self.by_id.get(e["to"] if direction == "$out" else e["from"])
            if other is None or (other.get("status") == "superseded" and not history):
                continue
            out.append((e, other))
        rows = [o for _e, o in out]
        if "$where" in expr:
            out = [(e, o) for e, o in out if self._matches(expr["$where"], o)]
        if "$sort" in expr:
            order = {id(o): i for i, o in enumerate(self._sorted([o for _e, o in out], expr["$sort"]))}
            out.sort(key=lambda pair: order[id(pair[1])])
        if "$limit" in expr:
            out = out[:int(expr["$limit"])]
        shaped = []
        for e, o in out:
            value = self._shape(expr, o, e) if ("$select" in expr or "$map" in expr) else o["id"]
            if derived == "mark":
                if isinstance(value, dict):
                    value = dict(value, derived_by=e.get("derived_by"))
                else:
                    value = {"value": value, "derived_by": e.get("derived_by")}
            shaped.append(value)
        return shaped

    # ---- where and sort ----
    def _matches(self, where, r):
        for key, want in (where or {}).items():
            have = self._field(key, r)
            if isinstance(want, dict):
                if "$in" in want and have not in want["$in"]:
                    return False
                if "$ne" in want and have == want["$ne"]:
                    return False
                if "$exists" in want and (have not in (None, "", [], {})) != bool(want["$exists"]):
                    return False
                if "$contains" in want and (not isinstance(have, (str, list)) or want["$contains"] not in have):
                    return False
            elif have != want:
                return False
        return True

    def _sorted(self, rows, spec):
        specs = spec if isinstance(spec, list) else [spec]
        for one in reversed(specs):
            reverse = one.startswith("-")
            key = one.lstrip("-+")
            rows = sorted(rows, key=lambda r: self._sort_key(self._field(key, r)), reverse=reverse)
        return rows

    @staticmethod
    def _sort_key(value):
        if value is None:
            return (1, "")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, value)
        return (0, str(value))


def project(expr, payload, base_dir=None):
    return Projector(payload, base_dir).evaluate(expr)


# ---- what a projection refers to, for validation ----

def references(expr, out=None, base_dir=None):
    """Classes, relations and attribute names a projection names: {"classes", "relations", "attributes", "includes"}."""
    out = out if out is not None else {"classes": set(), "relations": set(), "attributes": set(), "includes": []}
    if isinstance(expr, str):
        if expr.startswith("$attr."):
            out["attributes"].add(expr[6:])
        return out
    if isinstance(expr, list):
        for x in expr:
            references(x, out, base_dir)
        return out
    if isinstance(expr, dict):
        for key, value in expr.items():
            if key == "$nodes":
                for c in ([value] if isinstance(value, str) else value):
                    if c != "*":
                        out["classes"].add(c)
            elif key in ("$out", "$in"):
                for r in ([value] if isinstance(value, str) else value):
                    if r != "*":
                        out["relations"].add(r)
            elif key == "$include":
                out["includes"].append(value)
                if base_dir:
                    path = os.path.join(base_dir, value)
                    if os.path.exists(path):
                        with open(path, encoding="utf-8") as f:
                            references(json.load(f), out, base_dir)
            elif key == "$format" and isinstance(value, str):
                i = 0
                while True:
                    j = value.find("{attr.", i)
                    if j < 0:
                        break
                    k = value.find("}", j)
                    if k < 0:
                        break
                    out["attributes"].add(value[j + 6:k]); i = k + 1
            elif key in ("$where", "$sort", "$group"):
                keys = value.keys() if isinstance(value, dict) else ([value] if isinstance(value, str) else value)
                for k in keys:
                    k = str(k).lstrip("-+")
                    if k.startswith("attr."):
                        out["attributes"].add(k[5:])
            else:
                references(value, out, base_dir)
    return out
