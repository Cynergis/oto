---
name: sandbox
description: >-
  Set up a Docker sandbox with Claude Code and OTO inside, made from OTO's ready-made kit, and
  connect Claude Desktop's Code tab (or a terminal) to it. Checks what the computer has, asks the
  person for the few answers only they can give, runs the setup and says the one step left in
  Claude Desktop. Use when someone says "set up the sandbox", "run OTO in a sandbox", "I want to
  use OTO from Claude Desktop", "connect Desktop to the sandbox", or asks whether their sandbox is
  ready. Runs on the person's own computer, not inside a sandbox.
---

# Sandbox

A sandbox is a small virtual machine on the person's computer, made by Docker Sandboxes (`sbx`)
from OTO's kit. It holds Claude Code, OTO's marketplace and plugins, the engine, the Google Cloud
tools, LibreOffice and Chromium, and may reach only what the kit allows. It works on two folders
of the computer, `project` and `code`, so the person opens the files it writes as usual. Claude
Desktop's Code tab drives it over SSH; a terminal drives it with `sbx run`.

`oto sandbox` does the work; this skill decides with the person what it may do.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say flags, file names, commands or what
  a command printed, unless they ask. Say "the sandbox tool", "your Docker account", "your Claude
  sign-in", "your Google Cloud project".
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to do, ask a few questions at a time,
  read back what you understood in plain sentences, confirm, then say what is next.
- **Their computer, their choices.** Nothing that changes their computer's settings or their
  approvals is done without their yes in this conversation.

## Running the engine

On the person's computer the engine runs through `uvx`, as the plugin's server does:

```bash
uvx --from "${OTO_SOURCE:-oto-kg @ git+https://github.com/Cynergis/oto}" oto sandbox <up|status> ...
```

If `oto` is on the PATH, `oto sandbox ...` is the same. Without `uv`, say that one small tool is
needed first and give its installer: on a Mac or Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`,
on Windows in PowerShell `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`;
then a new terminal.

If `/home/agent/.oto/init.sh` exists, this session is already inside an OTO sandbox: say so, and
that `oto sandbox` is run from the computer, not from here. Stop.

## 1. Where things stand

Run `oto sandbox status --name <name> --json` (`oto-sandbox` unless the person named one). Read it
and say in a sentence or two what is there and what is missing:

| It says | Then |
|---|---|
| `sbx` null | the sandbox tool is not installed: give the command for their system (a Mac: `brew trust docker/tap && brew install docker/tap/sbx`; Windows 11: turn on Windows Hypervisor Platform in an administrator PowerShell, `Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All`, restart, then `winget install -h Docker.sbx`). They run it; you wait, then status again. |
| `signed_in` false | they sign in to Docker once: `sbx login` in a terminal opens the browser. Wait, then status again. |
| `policy` false | no network policy is chosen yet: ask (§2). |
| `anthropic_approved` false | the kit needs their approval to use their Claude sign-in: ask (§2). |
| `sandbox` set, `from_kit` true, `oto` says ready, `ssh` true | it is ready: go to §4. |
| `sandbox` set, `from_kit` false | a sandbox of that name exists but is not OTO's: ask for another name, or whether to replace it (what is only inside it is lost). |
| `outside_plugins.locked` false, `mode` blocked | things from outside would load in the sandbox (§5): say what, and that a sandbox made again from the current kit keeps them out. |

## 2. Ask, a few at a time

Ask only what is still open, in one message:

- **A name** for the sandbox (letters, numbers and hyphens; `oto-sandbox` if they have no
  preference) and **where its folders go** (a folder named after it in their home folder, unless
  they say otherwise).
- **Their Google Cloud project's id**, if the work uses Google Cloud: the id, not the name; the
  console shows it under the name. It is given to the sandbox as `PROJECT`. They may have none yet.
- **The network policy**, only when none is set: "balanced" is the usual one (Claude, code hosts and
  package sites allowed, anything else asked about); "deny-all" closes everything the kit does not
  name; "allow-all" opens everything. Recommend balanced.
- **The approval for their Claude sign-in**, only when it is missing. Say what it means: the sandbox
  may use their Claude sign-in, for Anthropic's sites only; the sandbox tool adds it to requests on
  their way out, so the sign-in itself never enters the sandbox. The sandbox tool asks this itself
  when started from a terminal; started from here it cannot ask, and without it Claude in the
  sandbox asks them to sign in at every message. Ask for a plain yes.

Only if the person says they want their own plugins or connectors in the sandbox too, explain §5 and
ask whether to make it that way. Never offer it otherwise.

Read the answers back in a sentence and confirm.

## 3. Set it up

With their confirmation, first dry-run, then run:

```bash
oto sandbox up --name <name> [--dir <folder>] [--project-id <id>] [--init-policy balanced] [--approve-anthropic] --check --json
oto sandbox up --name <name> [--dir <folder>] [--project-id <id>] [--init-policy balanced] [--approve-anthropic] --json
```

Pass `--init-policy` only with the policy they chose, `--approve-anthropic` only with their yes,
`--allow-outside-plugins` only when they asked for their own plugins in the sandbox (§5), `--recreate`
only when they agreed to replace an existing sandbox. Tell them it takes about a minute
the first time, more on a slow connection; the second run takes seconds.

`ok: false` comes with a `problem` and a `fix`: say both in plain words, and do what the fix says
only if it is theirs to agree to (ask) or theirs to do (wait for them). Never work around it.
`warnings` say an existing sandbox differs from what they asked (other folders, another project):
say so and ask whether to replace it.

## 4. Connect Claude Desktop

Say the steps from `next`, in words, once:

1. In Claude Desktop, the **Code** tab, a **new session**.
2. In the environment menu, **SSH**, then **Add SSH connection**: a name they will recognise, the
   host `<name>.sbx`, the port and the identity file left empty.
3. Choose that connection, then the folder, which is their `project` folder.

In that session Claude runs inside the sandbox, with OTO's plugins. If it asks to sign in once, they
do (`/login`); if it asks at every message, the approval is missing: §2, then `up --recreate`.
From a terminal instead: `sbx run --name <name>`.

Later, `oto sandbox status` says whether it is still ready; `oto sandbox up` starts it again after a
restart of the computer.

## 5. What the sandbox uses

Say this once, when the sandbox is ready, in a sentence or two: the sandbox uses only the OTO tools
installed inside it. What Claude Desktop brings from their computer, and the plugins, skills and
connectors of their claude.ai account, are switched off there, so the work in the sandbox does not
depend on what happens to be on their computer, and the sandbox cannot reach their mail, files or
calendar through those connectors.

One thing to know: when they add a new plugin on their computer, the first session in the sandbox
afterwards still has it. Claude says so at the start of that session and switches it off; a new
session, or typing `/reload-plugins`, works without it.

If they want their own plugins and connectors in the sandbox, it is made that way from the start
(`--allow-outside-plugins`); an existing sandbox is made again for it (`--recreate`, after their yes).
`status` says which way a sandbox is (`outside_plugins`).
