# Gates

OTO is a compiler for knowledge. A compiler that silently changes its output is worse than one that
fails, so every change runs against gates. They run on every push in CI, and locally with:

```bash
tools/run_gates.sh                            # or PYTHON=.venv/bin/python tools/run_gates.sh
```

| Gate | What it protects | Command |
|---|---|---|
| tests | unit behaviour, and that a clean-then-build round trip reproduces the database byte for byte | `pytest` |
| greenfield self-test | the engine works on a domain it has never seen | `oto verify` |
| starter vocabularies | every ontology inits, builds, passes the integrity gate and answers a query | `tools/check_ontologies.py` |
| publishability | no client name, private repository reference or credential | `tools/check_publishable.py --strict` |
| dependency-free compile | a bare install pulls in nothing third-party, and still ingests Markdown | the `bare` CI job |
| module compilation | valid syntax on the oldest supported Python | `compileall` |

The dependency-free gate matters more than it looks. The compile path is stdlib-only on purpose, so a
project can build in a locked-down environment. One convenience import would end that quietly.

## Determinism is a contract

The same inputs must produce byte-identical outputs. Two changes once looked correct at every level
except bytes, and both are worth remembering:

- Indenting a SQL string changed the database. Every table and row was identical, because SQLite
  stores `CREATE TABLE` text verbatim. The schema is therefore a module-level constant, and a test
  fails if any line of it is indented.
- A figure-summary look-ahead of 30 lines instead of 29 picked up one extra label and changed four
  words in one document.

If your change alters output, say so in the pull request and explain why the new output is correct.

## Deny terms are never stored here

`check_publishable.py` needs to know which names are client names, and writing that list into a
public file names the client. Terms come from `OTO_DENY_TERMS` (a CI secret) or a gitignored
`.oto-denylist`, one term per line. With no terms configured the gate reports that name checking is
**disabled** rather than passing quietly, and `--strict` turns that into a failure.

A fork cannot read the secret, so the strict job runs only for branches in this repository. Forks
still get the credential scan, whose patterns are built in.
