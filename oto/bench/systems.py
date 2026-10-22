# -*- coding: utf-8 -*-
"""The systems under test.

Two ship. `oto` is the real engine: resolve the question to entities, walk the graph, return the
sources those facts cite. `lexical` is a full-text baseline over the same corpus and the same database,
which is the point: any difference comes from the method, not from a different corpus or a different
machine.

A baseline that is quietly handicapped proves nothing. The lexical system gets the same index, the
same passages and the same k. Where it wins, the report says so.
"""
import os
import re
import sqlite3


def _read_only(path):
    connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


#: Words that match almost everything. Leaving them in makes every query match most of the corpus,
#: which turns retrieval into noise and the comparison into nonsense.
STOP_WORDS = frozenset("""
a an the and or but of to in on for with by as at is are was were be been being it its this that
these those from into within across each per via not no only what which who whom whose when where
why how do does did done can could should would may might will shall about over under more most
any all some such than then there here we you they he she our your their his her them us new
""".split())


def _fts_query(text):
    """A safe, useful FTS5 query from free text.

    Every token is quoted, because unquoted user text is a syntax error waiting to happen. Stop words
    are dropped: a query containing "the" matches nearly the whole corpus, and a retrieval that
    returns everything has told you nothing.
    """
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower())
              if len(t) > 2 and t not in STOP_WORDS]
    if not tokens:
        tokens = [t for t in re.findall(r"[A-Za-z0-9]+", (text or "").lower()) if t]
    return " OR ".join('"%s"' % t for t in tokens) or '"x"'


def _source_slug(path):
    """documents/20260601-x.md -> 20260601-x, so a citation matches a gold source."""
    return os.path.splitext(os.path.basename(path or ""))[0]


def _blank(system, question_id, kind):
    return {"system": system, "qid": question_id, "answer_kind": kind, "resolved_entity": None,
            "retrieved_entities": [], "retrieved_sources": [], "surfaced_sources": [],
            "cited_sources": [], "abstained": False, "match": None, "confidence": None,
            "answer_status": None, "answer": None}


#: Index folders whose pages the build generates from the graph: one per entity, named after its id.
GENERATED = ("entities", "cards")


def sources_of(connection, path, cache):
    """The source documents one indexed passage stands for. A document or a note stands for itself;
    a generated entity page or card stands for the sources of its entity, which is what citing it
    rests on. Without this, a retriever that found the right entity's card is marked wrong."""
    slug = _source_slug(path)
    folder = str(path or "").replace("\\", "/").split("/")[0]
    if folder not in GENERATED:
        return [slug]
    if slug not in cache:
        import json
        row = connection.execute("SELECT sources, source_doc FROM nodes WHERE id=?", (slug.replace("__", "."),)).fetchone()
        found = list(json.loads(row["sources"] or "[]") or []) if row else []
        if row and row["source_doc"] and row["source_doc"] not in found:
            found.append(row["source_doc"])
        cache[slug] = found or [slug]
    return cache[slug]


def credited(connection, paths, cache):
    """Paths in rank order, as the sources they stand for, each once."""
    out = []
    for path in paths:
        for source in sources_of(connection, path, cache):
            if source not in out:
                out.append(source)
    return out


class OtoSystem:
    """The engine: resolve, traverse, cite what the facts themselves cite."""

    name = "oto"

    def __init__(self, database, use_graph=True, use_temporal=True):
        self.database = database
        self.use_graph = use_graph
        self.use_temporal = use_temporal
        if not use_graph:
            self.name = "oto-no_graph"
        elif not use_temporal:
            self.name = "oto-no_temporal"

    _names = None

    def _name_index(self, connection):
        """{lowercased name: (grade, [ids])}: every label, alias and lexicon phrase, read once."""
        if self._names is None:
            names = {}

            def add(name, grade, nid):
                if name and len(name.strip()) > 1:
                    entry = names.setdefault(name.strip().lower(), (grade, []))
                    if nid not in entry[1]:
                        entry[1].append(nid)
            for row in connection.execute("SELECT id, label FROM nodes ORDER BY id"):
                add(row["label"], "label", row["id"])
            for row in connection.execute("SELECT node_id, alias FROM aliases ORDER BY node_id"):
                add(row["alias"], "alias", row["node_id"])
            try:
                for row in connection.execute("SELECT phrase, target, status FROM lexicon ORDER BY phrase, target"):
                    if row["target"] and row["status"] != "not_ingested":
                        add(row["phrase"], "lexicon", row["target"])
            except sqlite3.Error:
                pass
            self._names = names
        return self._names

    def _resolve(self, connection, question):
        """(rows, grade): the entities the question names exactly, by id, label, alias or lexicon
        phrase, and how. The question's `entity` is the name as asked; without one, the question is
        scanned for names, longest first. A full-text hit binds nothing: it is a near miss, and an
        answer built on it is a guess. Its grade is "text", so the report can say what was refused.
        """
        names = self._name_index(connection)
        given = str(question.get("entity") or "").strip()
        found = {}                                            # id -> the grade of the name that named it
        if given:
            if connection.execute("SELECT 1 FROM nodes WHERE id=?", (given,)).fetchone():
                found[given] = "id"
            elif given.lower() in names:
                grade, ids = names[given.lower()]
                found = {nid: grade for nid in ids}
        else:
            text = " " + " ".join(re.findall(r"[\w-]+", str(question.get("question") or "").lower())) + " "
            for name in sorted(names, key=len, reverse=True):
                phrase = " " + " ".join(re.findall(r"[\w-]+", name)) + " "
                if phrase.strip() and phrase in text:
                    grade, ids = names[name]
                    for nid in ids:
                        found.setdefault(nid, grade)
                    text = text.replace(phrase, " | ")       # a shorter name inside this one is not a second name
        if not found:
            try:
                hit = connection.execute("SELECT 1 FROM node_fts WHERE node_fts MATCH ? LIMIT 1",
                                         (_fts_query(given or question.get("question")),)).fetchone()
            except sqlite3.Error:
                hit = None
            return [], {}, ("text" if hit else None)
        marks = ",".join("?" * len(found))
        rows = connection.execute("SELECT id, label, status, valid_from, valid_to FROM nodes WHERE id IN (%s) ORDER BY id"
                                  % marks, list(found)).fetchall()
        return rows, found, None

    @staticmethod
    def _valid_at(row, date):
        """Is this version of the fact true on that date?

        Valid time, not transaction time: a fact is true on D when it became true on or before D and
        had not stopped by D. Reporting today's status for an as-of question is the commonest way a
        knowledge base answers confidently and wrongly.
        """
        valid_from = row["valid_from"] if "valid_from" in row.keys() else None
        valid_to = row["valid_to"] if "valid_to" in row.keys() else None
        if valid_from and str(valid_from) > date:
            return False
        if valid_to and str(valid_to) <= date:
            return False
        return True

    def _time_aware(self, connection, rows, question):
        """(chosen row, status), or (None, "ambiguous") when the name points at more than one entity
        at the time asked about. Versions of one entity are not ambiguous: at most one is current.
        Status is current, superseded, absent, changed or unchanged."""
        as_of = question.get("as_of")
        kind = str(question.get("type") or "")
        current = [r for r in rows if r["status"] == "current"]
        if as_of:
            valid = [r for r in rows if self._valid_at(r, str(as_of))]
            if len(valid) > 1 or (not valid and len(current) > 1):
                return None, "ambiguous"
            if valid:
                return valid[0], "current"
            # It exists now, but it did not then. That is the answer, and it is the one a
            # time-blind system gets wrong while sounding certain.
            return (current or rows)[0], "absent"
        if len(current) > 1:
            return None, "ambiguous"
        chosen = (current or rows)[0]
        if kind == "temporal_change":
            # Did this fact ever change? A supersession chain is the record of that.
            identifier = chosen["id"]
            chain = connection.execute(
                "SELECT count(1) FROM nodes WHERE superseded_by=? OR id IN "
                "(SELECT superseded_by FROM nodes WHERE id=? AND superseded_by IS NOT NULL)",
                (identifier, identifier)).fetchone()[0]
            return chosen, ("changed" if chain else "unchanged")
        return chosen, ("current" if current else chosen["status"])

    def answer(self, question):
        result = _blank(self.name, question.get("id"), "entity")
        connection = _read_only(self.database)
        try:
            rows, grades, near = self._resolve(connection, question)
            if not rows:
                # Nothing is named exactly as asked. Abstaining is the answer; the grade says whether
                # a text hit was refused, so the report can show what guessing would have bound.
                result.update(abstained=True, match=near)
                return result

            if self.use_temporal:
                chosen, status = self._time_aware(connection, rows, question)
                if chosen is None:
                    result.update(abstained=True, match="ambiguous")
                    return result
                result["answer_status"] = status
            else:
                # The ablation: no as-of reasoning, no change detection, no notion that two entities
                # share a name. Whatever row sorts first wins: this is what a time-blind system does,
                # and it should cost it the temporal metric and the precision of its answers.
                chosen = rows[0]
                result["answer_status"] = "current"
            result["match"] = grades.get(chosen["id"])

            result["resolved_entity"] = chosen["id"]
            entities = [chosen["id"]]

            if self.use_graph:
                for row in connection.execute(
                        "SELECT dst FROM edges WHERE src=? UNION SELECT src FROM edges WHERE dst=?",
                        (chosen["id"], chosen["id"])).fetchall():
                    entities.append(row[0])
            result["retrieved_entities"] = entities

            # A citation is what the ANSWER relied on, which is the fact returned, not every
            # neighbour retrieval happened to walk past. Citing the whole neighbourhood destroys
            # precision: measured on the reference graph, it made citation F1 four times worse than
            # turning the graph off entirely.
            cited = []
            for row in connection.execute(
                    "SELECT sources, source_doc FROM nodes WHERE id=?", (chosen["id"],)).fetchall():
                import json
                for source in (json.loads(row["sources"] or "[]") or []):
                    cited.append(source)
                if row["source_doc"]:
                    cited.append(row["source_doc"])
            result["cited_sources"] = sorted(set(cited))

            passages = connection.execute(
                "SELECT path FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 10",
                (_fts_query(question.get("question")),)).fetchall()
            result["retrieved_sources"] = credited(connection, [p["path"] for p in passages], {})
            # Two different lists, deliberately both reported. `retrieved_sources` is passage search
            # only, which is what a retriever does. `surfaced_sources` is everything this system put
            # in front of the answer, entity sources first because it resolves the entity first.
            # Scoring an entity-first system on the passage list alone marks it wrong on questions it
            # answered correctly: on the reference corpus two questions scored citation F1 1.0 and
            # coverage 0.0 at the same time, which cannot both be true. Both columns are printed so
            # the architectural difference is visible rather than hidden inside one number.
            ordered = list(result["cited_sources"])
            for slug in result["retrieved_sources"]:
                if slug not in ordered:
                    ordered.append(slug)
            result["surfaced_sources"] = ordered
            result["answer"] = chosen["label"]
        except sqlite3.Error as exc:
            result["answer_status"] = "error"
            result["answer"] = str(exc)[:120]
        finally:
            connection.close()
        return result


class LexicalSystem:
    """Full-text search over the same corpus. The baseline, given every advantage it can have."""

    name = "lexical"

    def __init__(self, database):
        self.database = database

    def answer(self, question):
        result = _blank(self.name, question.get("id"), "passage")
        connection = _read_only(self.database)
        try:
            rows = connection.execute(
                "SELECT path, title FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 10",
                (_fts_query(question.get("question")),)).fetchall()
            sources = credited(connection, [r["path"] for r in rows], {})
            result["retrieved_sources"] = sources
            result["surfaced_sources"] = sources        # a passage retriever surfaces only passages
            # A lexical system can only cite the passage it pulled. That is the honest limit, and
            # measuring it is the point of the comparison.
            result["cited_sources"] = sources[:3]
            result["answer"] = rows[0]["title"] if rows else None
            result["abstained"] = not sources
            # It has no notion of time, so it cannot answer a temporal question correctly except by
            # accident. Recording "unknown" rather than guessing keeps that visible.
            result["answer_status"] = "unknown"
        except sqlite3.Error as exc:
            result["answer_status"] = "error"
            result["answer"] = str(exc)[:120]
        finally:
            connection.close()
        return result


def build(database, names, ablations=False, progress=None, dense_min_similarity=None):
    """The systems to run.

    Returns (systems, unknown, skipped). A system asked for and not built is reported, never dropped
    silently: a comparison missing its strongest opponent should say so on the face of it.
    """
    systems, unknown, skipped = [], [], []
    for name in names:
        if name == "oto":
            systems.append(OtoSystem(database))
        elif name == "lexical":
            systems.append(LexicalSystem(database))
        elif name == "dense":
            from . import dense
            usable, reason = dense.available()
            if not usable:
                skipped.append(("dense", reason))
            else:
                systems.append(dense.DenseSystem(database, progress=progress, min_similarity=dense_min_similarity))
        else:
            unknown.append(name)
    if ablations:
        # Turning a pillar off should degrade the metric it defends. If it does not, the pillar is
        # not earning its place, and that is worth knowing.
        systems.append(OtoSystem(database, use_graph=False))
        systems.append(OtoSystem(database, use_temporal=False))
    return systems, unknown, skipped
