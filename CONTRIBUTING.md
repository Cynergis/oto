# Contributing to OTO

## The one rule

**Never commit domain data.** This repository holds the engine. Client names, project names,
private repository names, corpora and graphs belong in a private project repository.

CI enforces this. The publishability gate fails the build when it finds a client name, a private
repository reference or a secret-shaped string.

## Determinism is a contract

The compile must be reproducible. The same inputs must produce byte-identical outputs.

Before you open a pull request:

```bash
tools/run_gates.sh
```

See [docs/GATES.md](docs/GATES.md) for what each gate proves. If your change alters output, say so
in the pull request and explain why the new output is correct.

## Layout

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) walks the package in the order a project moves through
it, and says where to add an extractor, a command, a stage or an ontology. In brief:

| Path | Holds |
|---|---|
| `oto/scaffold.py`, `oto/project.py`, `oto/layout.py` | creating a project, and where its files live |
| `oto/intake/` | document extractors, the format registry, figure descriptions |
| `oto/model/` | the vocabulary: ontologies, versioning, conformance, rationale |
| `oto/validate/` | the pre-build integrity gate, the privacy gate, the self-test |
| `oto/compile/`, `oto/targets/`, `oto/builder.py` | the four deterministic stages and the transaction around them |
| `oto/curate/` | candidate graphs, supersession checks, assertions, provenance vetting |
| `oto/serve/` | the query engine, over JSON-RPC 2.0 or the CLI |
| `oto/bench/` | gold sets, the systems under test, metrics, the feedback loop |
| `oto/cli/` | one module per command |
| `oto/ontologies/` | starter vocabularies, shipped with the package |
| `skills/` | playbooks for the steps that need judgment; `.claude-plugin/` and `.claude/skills/` expose them to Claude Code |
| `tests/` | the suite; `tools/` the gate scripts CI runs |

## Naming

The command, the import name and the repository are `oto`. The distribution is `oto-kg`, because
`oto` was taken on the package index. Two namespaces, one tool.

## Signing off

OTO uses a **Developer Certificate of Origin** sign-off rather than a contributor licence agreement.
It is the light option: no paperwork, one line per commit.

Add it automatically:

```bash
git commit -s -m "your message"
```

That appends a trailer:

```
Signed-off-by: Your Name <you@example.com>
```

By adding it you state that you wrote the change, or have the right to submit it under
Apache-2.0. The full text is in [DCO](DCO). CI checks that every commit in a pull request carries
the trailer.

## Style

The compile path is stdlib-only. Keep it that way. Parsers belong in the `intake` extra.

## The explorer's bundle

The explorer under `oto/ui/explorer/` needs React and React Flow, so its source lives in
`ui-src/explorer/` and the built files are committed. After changing the source:

```bash
cd ui-src && npm install && npm run build
```

Commit the rebuilt `oto/ui/explorer/explorer.js` and `explorer.css` with the source change. A user
never runs this; the engine ships the built files and serves them with the standard library.
