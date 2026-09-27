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


def _blank(system, question_id):
    return {"system": system, "qid": question_id, "resolved_entity": None,
            "retrieved_entities": [], "retrieved_sources": [], "surfaced_sources": [],
            "cited_sources": [],
            "answer_status": None, "answer": None}


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

    def _resolve(self, connection, term):
        """Id, then label, then alias, then full text. In that order, and the order matters.

        A gold set identifies an entity by its id, and an id is exact. Skipping straight to search
        turns a certain answer into a guess, which is what the first version of this did: entity hit
        collapsed as soon as ranking changed which rows came back.
        """
        if not term:
            return []
        rows = connection.execute(
            "SELECT id, label, status, valid_from, valid_to FROM nodes WHERE id=? LIMIT 5", (term,)).fetchall()
        if not rows:
            rows = connection.execute(
                "SELECT id, label, status, valid_from, valid_to FROM nodes WHERE lower(label)=lower(?) LIMIT 5",
                (term,)).fetchall()
        if not rows:
            rows = connection.execute(
                "SELECT n.id, n.label, n.status, n.valid_from, n.valid_to FROM aliases a JOIN nodes n ON n.id=a.node_id "
                "WHERE lower(a.alias)=lower(?) LIMIT 5", (term,)).fetchall()
        if not rows:
            try:
                rows = connection.execute(
                    "SELECT n.id, n.label, n.status, n.valid_from, n.valid_to FROM node_fts f JOIN nodes n ON n.id=f.id "
                    "WHERE node_fts MATCH ? ORDER BY rank LIMIT 5", (_fts_query(term),)).fetchall()
            except sqlite3.Error:
                rows = []
        return rows

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
        """(chosen row, status). Status is current, superseded, absent, changed or unchanged."""
        as_of = question.get("as_of")
        kind = str(question.get("type") or "")

        if kind == "temporal_change":
            # Did this fact ever change? A supersession chain is the record of that.
            identifier = rows[0]["id"]
            chain = connection.execute(
                "SELECT count(1) FROM nodes WHERE superseded_by=? OR id IN "
                "(SELECT superseded_by FROM nodes WHERE id=? AND superseded_by IS NOT NULL)",
                (identifier, identifier)).fetchone()[0]
            return rows[0], ("changed" if chain else "unchanged")

        if as_of:
            valid = [r for r in rows if self._valid_at(r, str(as_of))]
            if not valid:
                # It exists now, but it did not then. That is the answer, and it is the one a
                # time-blind system gets wrong while sounding certain.
                return rows[0], "absent"
            return valid[0], "current"

        current = [r for r in rows if r["status"] == "current"]
        chosen = (current or rows)[0]
        return chosen, ("current" if current else chosen["status"])

    def answer(self, question):
        result = _blank(self.name, question.get("id"))
        connection = _read_only(self.database)
        try:
            rows = self._resolve(connection, question.get("entity")) \
                or self._resolve(connection, question.get("question"))
            if not rows:
                result["answer_status"] = "absent"
                return result

            if self.use_temporal:
                chosen, status = self._time_aware(connection, rows, question)
                result["answer_status"] = status
            else:
                # The ablation: no as-of reasoning, no change detection. Whatever is in the row wins.
                # This is what a time-blind system does, and it should cost it the temporal metric.
                chosen = rows[0]
                result["answer_status"] = "current"

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
            result["retrieved_sources"] = [_source_slug(p["path"]) for p in passages]
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
        result = _blank(self.name, question.get("id"))
        connection = _read_only(self.database)
        try:
            rows = connection.execute(
                "SELECT path, title FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT 10",
                (_fts_query(question.get("question")),)).fetchall()
            sources = [_source_slug(r["path"]) for r in rows]
            result["retrieved_sources"] = sources
            result["surfaced_sources"] = sources        # a passage retriever surfaces only passages
            # A lexical system can only cite the passage it pulled. That is the honest limit, and
            # measuring it is the point of the comparison.
            result["cited_sources"] = sources[:3]
            result["answer"] = rows[0]["title"] if rows else None
            # It has no notion of time, so it cannot answer a temporal question correctly except by
            # accident. Recording "unknown" rather than guessing keeps that visible.
            result["answer_status"] = "unknown"
        except sqlite3.Error as exc:
            result["answer_status"] = "error"
            result["answer"] = str(exc)[:120]
        finally:
            connection.close()
        return result


def build(database, names, ablations=False, progress=None):
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
                systems.append(dense.DenseSystem(database, progress=progress))
        else:
            unknown.append(name)
    if ablations:
        # Turning a pillar off should degrade the metric it defends. If it does not, the pillar is
        # not earning its place, and that is worth knowing.
        systems.append(OtoSystem(database, use_graph=False))
        systems.append(OtoSystem(database, use_temporal=False))
    return systems, unknown, skipped
