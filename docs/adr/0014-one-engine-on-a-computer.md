---
id: ADR-0014
title: A computer has one OTO engine, the oto command installed there, and the plugin runs that one
status: accepted
decided_on: 2026-11-03
decided_by: Chiheb Dkhil
governs: [workitem.epic-l]
---

# A computer has one OTO engine, the oto command installed there, and the plugin runs that one

## Context

Until this decision the engine reached a computer by four routes, each choosing its own copy. The
`oto` command, installed with `uv tool install`, is what a person types and what `oto sandbox up` is.
The plugin's server and hooks did not use it: they ran `uvx --from "${OTO_SOURCE:-oto-kg @
git+https://github.com/Cynergis/oto}"`, a copy downloaded on demand from main's latest commit, or from
whatever `OTO_SOURCE` named. A project repository's server did the same, unpinned. Inside a sandbox the
kit pinned `OTO_SOURCE` to its release.

Testing the sandbox kit on 2026-11-03 showed the cost. On one Mac, `oto` was 0.19.0, the plugin's
server in Claude Desktop ran main (0.19.0 that day), and a `claude` started from a terminal ran
0.11.31: `~/.zshrc` set `OTO_SOURCE` to an old clone in `~/Downloads/oto`, as the README had
suggested for running from a checkout. Nothing said the copies differed, and the folder went into a
committed `oto.lock.json`. The person could not tell which engine answered, nor why.

## Decision

A computer has one engine: the `oto` command installed there, once, with `uv tool install
"oto-kg[intake] @ git+https://github.com/Cynergis/oto@v<version>"`. The plugin's server runs `oto
serve`, its hooks run `oto`, and a project repository's server runs `oto serve`; none downloads a copy
of its own. `OTO_SOURCE` is read by nothing.

## Consequences

**The session start checks it.** The plugin's session hook (`hooks/engine.sh`) says in a line when the
engine is missing, installed but off the PATH Claude Code sees (`uv tool update-shell`), or not the
plugin's release, with the one command that fixes it, then prints the project's status. A session
starts without the engine; the plugin's tools do not.

**Upgrading is one command.** `uv tool install --force` at the newer release moves the engine the
person types and the one the plugin runs together. `claude plugin update` moves the plugin, and its
session start then says the engine to install.

**Developing the engine** installs the checkout as the one engine, `uv tool install --force
--editable <checkout>`, and the checkout's plugin with `claude --plugin-dir <checkout>`; back to a
release when done. No variable stands between them.

**Sandboxes and workflows.** The kit installs the engine at its release (`init.sh`), and that is the
one the plugin inside runs; it sets no `OTO_SOURCE`. A workflow installs the engine with `pip` at the
ref `oto.lock.json` records, as before. The lock records no `OTO_SOURCE`, and its restore script
installs the `oto` command and exports nothing.

**What it costs.** uv was the only prerequisite and nothing had to be on the PATH; now the engine is
installed once on each computer. The start and sandbox skills say how, and the session start names
the command.
