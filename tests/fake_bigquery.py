"""A BigQuery client in memory, strict where OTO depends on BigQuery's behaviour: rows go through JSON and must fit
their column's type, a listing promises no order (this one shuffles), and a table that isn't there raises NotFound.
`tests/test_bigquery_store.py` checks the calls OTO makes against the real client's signatures, where that's installed;
this is everything else. It can be saved and loaded, so a test can hand it to the CLI in another process."""
import json
import random
import re
import types


class NotFound(Exception):
    code = 404


class BadRequest(Exception):
    code = 400


class Row:
    def __init__(self, row):
        self._row = row

    def items(self):
        return list(self._row.items())

    def values(self):
        return list(self._row.values())


class Rows(list):
    def __init__(self, columns, rows):
        super().__init__(types.SimpleNamespace(values=lambda r=r: list(r)) for r in rows)
        self.schema = [types.SimpleNamespace(name=c) for c in columns]


class Job:
    def __init__(self, result=None, statement_type=None):
        self._result = result
        self.statement_type = statement_type

    def result(self, max_results=None):
        return self._result


def _name(table):
    """The last part of a table's id, from "project.dataset.table" or from an object naming it."""
    if isinstance(table, str):
        return table
    return "%s.%s.%s" % (table.project, table.dataset_id, table.table_id)


def _dataset_of(full):
    return full.rsplit(".", 1)[0]


class FakeClient:
    def __init__(self, datasets=("p.kg",), seed=7):
        self.datasets = set(datasets)
        self.tables = {}                 # "project.dataset.table": {"schema": [[name, type]], "rows": [...]}
        self.views = {}                  # "project.dataset.view": the full name of the table it reads
        self.calls = []
        self.fail_on = None              # a table's last name: a load into it fails
        self.missing_once = set()        # a table's last name: reading it raises NotFound, once
        self.unreachable = False
        self._seed = seed

    # ---- what a test reads ----
    def rows(self, table, dataset="p.kg"):
        return sorted(self.tables["%s.%s" % (dataset, table)]["rows"], key=lambda r: r.get("oto_row", 0))

    def names(self, dataset="p.kg"):
        prefix = dataset + "."
        return sorted(t[len(prefix):] for t in self.tables if t.startswith(prefix))

    def view(self, name, dataset="p.kg"):
        return self.views["%s.%s" % (dataset, name)].rsplit(".", 1)[1]

    def count(self, call):
        return sum(1 for c in self.calls if c[0] == call)

    # ---- the client ----
    def _check(self):
        if self.unreachable:
            raise OSError("the network is down")

    def get_dataset(self, dataset):
        self._check()
        if dataset not in self.datasets:
            raise NotFound("Not found: Dataset %s" % dataset)
        return types.SimpleNamespace(dataset_id=dataset)

    def create_dataset(self, dataset, exists_ok=False):
        self._check()
        name = dataset if isinstance(dataset, str) else "%s.%s" % (dataset.project, dataset.dataset_id)
        self.datasets.add(name)
        return dataset

    def _dataset_exists(self, full):
        if _dataset_of(full) not in self.datasets:
            raise NotFound("Not found: Dataset %s" % _dataset_of(full))

    def create_table(self, table, exists_ok=False):
        self._check()
        full = _name(table)
        self._dataset_exists(full)
        self.calls.append(("create_table", full))
        if full in self.tables and not exists_ok:
            raise BadRequest("Already Exists: Table %s" % full)
        if full not in self.tables:
            self.tables[full] = {"schema": [[f.name, f.field_type] for f in table.schema], "rows": []}
        return table

    def delete_table(self, table, not_found_ok=False):
        self._check()
        full = _name(table)
        self.calls.append(("delete_table", full))
        if full not in self.tables and not not_found_ok:
            raise NotFound("Not found: Table %s" % full)
        self.tables.pop(full, None)

    def list_tables(self, dataset):
        self._check()
        if dataset not in self.datasets:
            raise NotFound("Not found: Dataset %s" % dataset)
        return [types.SimpleNamespace(table_id=t.rsplit(".", 1)[1]) for t in sorted(self.tables) if _dataset_of(t) == dataset]

    def load_table_from_json(self, rows, destination, job_config=None):
        self._check()
        full = _name(destination)
        self._dataset_exists(full)
        self.calls.append(("load", full, len(rows)))
        if self.fail_on and full.endswith("." + self.fail_on):
            raise RuntimeError("the load into %s failed" % self.fail_on)
        schema = [[f.name, f.field_type] for f in job_config.schema]
        kinds = dict(schema)
        kept = []
        for row in json.loads(json.dumps(rows, ensure_ascii=False)):
            for key, value in row.items():
                if key not in kinds:
                    raise BadRequest("no such field %s in %s" % (key, full))
                if value is not None and not isinstance(value, {"STRING": str, "INT64": int, "FLOAT64": (int, float)}[kinds[key]]):
                    raise BadRequest("%s of %s is %r, not %s" % (key, full, value, kinds[key]))
            kept.append(row)
        if job_config.write_disposition == "WRITE_APPEND" and full in self.tables:
            self.tables[full]["rows"].extend(kept)
        else:
            self.tables[full] = {"schema": schema, "rows": kept}
        return Job()

    def list_rows(self, table):
        self._check()
        full = _name(table)
        self.calls.append(("list_rows", full))
        last = full.rsplit(".", 1)[1]
        if last in self.missing_once:
            self.missing_once.discard(last)
            raise NotFound("Not found: Table %s" % full)
        if full not in self.tables:
            raise NotFound("Not found: Table %s" % full)
        rows = list(self.tables[full]["rows"])
        random.Random(self._seed).shuffle(rows)                # a listing promises no order
        return [Row(r) for r in rows]

    def query(self, sql, job_config=None):
        self._check()
        self.calls.append(("query", sql))
        made = re.match(r"CREATE OR REPLACE VIEW `([^`]+)` AS SELECT \* EXCEPT\(oto_row\) FROM `([^`]+)`$", sql)
        if made:
            if made.group(2) not in self.tables:
                raise NotFound("Not found: Table %s" % made.group(2))
            self.views[made.group(1)] = made.group(2)
            return Job(statement_type="CREATE_VIEW")
        return Job(self._answer(sql), statement_type="SELECT")

    def _answer(self, sql):
        """Just enough of the overlay's reads for the conformance kit."""
        if sql.strip() == "SELECT 1 AS one":
            return Rows(["one"], [[1]])
        found = re.search(r"`[^.`]+\.([^.`]+)\.INFORMATION_SCHEMA\.(TABLES|COLUMNS)`", sql)
        if found:
            prefix = [d for d in self.datasets if d.endswith("." + found.group(1))][0] + "."
            own = [(t, v) for t, v in sorted(self.tables.items()) if t.startswith(prefix)]
            if found.group(2) == "TABLES":
                return Rows(["table_name", "table_type"], [[t[len(prefix):], "BASE TABLE"] for t, _v in own])
            return Rows(["table_name", "column_name", "data_type", "is_nullable", "ordinal_position"],
                        [[t[len(prefix):], c[0], c[1], "YES", i + 1] for t, v in own for i, c in enumerate(v["schema"])])
        if "KEY_COLUMN_USAGE" in sql:
            return Rows(["table_name", "column_name", "constraint_type", "ref_table", "ref_column"], [])
        if "JOBS_BY_PROJECT" in sql:
            return Rows(["creation_time", "user_email", "query", "total_bytes_processed", "statement_type"], [])
        raise BadRequest("this fake doesn't answer: %s" % sql)

    def close(self):
        pass

    # ---- across a process ----
    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"datasets": sorted(self.datasets), "tables": self.tables, "views": self.views}, f)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        client = cls(datasets=saved["datasets"])
        client.tables, client.views = saved["tables"], saved["views"]
        return client
