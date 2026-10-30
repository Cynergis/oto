---
name: sandboxes
description: See every OTO sandbox on this computer and clean up the ones no longer used: which are running or stopped, when each was last used, whether its folders still exist, and which of Claude Desktop's saved SSH connections point at a sandbox that is gone. Shows the candidates as a checklist (the question tool, several answers), confirms, removes the ticked sandboxes with `oto sandbox rm`, offers to archive or delete the Desktop sessions that ran on them, and names the SSH connections only the person can remove, in Desktop's SSH environment menu. Use when someone asks "which sandboxes do I have", "clean up my sandboxes", "remove the old sandbox", "what is still running", or wants Desktop's list of connections tidied. Runs on the person's computer, where the sandbox tool is, never inside a sandbox.
---

# Sandboxes: what is there, and cleaning up

`oto sandbox up` makes a sandbox and `oto sandbox status` says where one stands; this skill is about
all of them. It reads `oto sandbox ls`, lets the person choose what goes, and removes it with
`oto sandbox rm`. What it cannot remove, it names: Claude Desktop's saved SSH connections are the
app's own, taken away in its SSH environment menu, and its sessions are archived or deleted through
the app's own session tools, each with the person's approval.

If `/home/agent/.oto/init.sh` exists, this session is inside a sandbox: say so, and that sandboxes are
listed and removed from the computer, not from here. Stop.

## Talking with the person

- **Plain, natural language, in the person's words.** "The Northwind sandbox, running, used today";
  never the JSON, the flags or what a command printed, unless they ask.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** show what is there, propose what could go and why, let them
  tick, read back what you understood, confirm, do it, then say what is left to them.
- **Removal is final.** A removed sandbox's containers, state and the secrets scoped to it are gone;
  the project and code folders on their computer stay. Say so before asking, and remove nothing
  without their yes on the exact names.

## 1. What is there

`oto sandbox ls --json` (the `--json` form, read as data): every sandbox with its `status` (running
or stopped), `made_from` and `from_kit` (OTO's kit or another agent's), `folders` with whether each
`exists`, `created_at`, `last_used_at` and `idle_days`, and `ssh` (whether `<name>.sbx` is reachable);
and `connections`, Claude Desktop's saved SSH connections to `.sbx` hosts, each with whether a
sandbox of that name still `exists`. Without `sbx`, or without a Docker sign-in, the listing says so
and there is nothing to clean: hand over to the sandbox skill.

Say it as a short list in words, one line per sandbox: name, running or stopped, last used (today, n
days ago, unknown), the folders and whether they are still there, and whether it is OTO's. Then the
connections: how many, and which point at nothing.

## 2. What could go

A sandbox is a candidate when any of these holds; say which, in words, beside its name:

- stopped and idle for more than seven days, or never used;
- its folders are gone from the computer (the work moved or was deleted);
- not made from OTO's kit (another agent's sandbox: mention it, propose nothing);
- a stale connection: Desktop knows `<name>.sbx` and no sandbox of that name exists.

A running sandbox used today is not a candidate; say so when the person asks about it. Never propose
the sandbox the person is working in.

Show the candidates with the question tool, several answers allowed (a select list with checkboxes,
at most four options a question and four a screen), one option per sandbox with its reason as the
description; the stale connections are not options (they are not the computer's to remove) but a
line under the question. Read the ticked names back, with what removal means, and confirm.

## 3. Removing

With their yes, for the ticked names:

```bash
oto sandbox rm <name> [<name> ...]        # stops it, removes containers, state and the sandbox's secrets; the folders stay
oto sandbox stop <name>                   # when they want it kept but not running
```

Read the result back: what was removed, what was not found (`missing`), what failed and why. Then
`oto sandbox ls` once more, so the person sees what is left.

## 4. What Claude Desktop keeps

Two things outlive a removed sandbox in Claude Desktop, and the skill says both, once:

- **The SSH connection** (`<name>.sbx`) stays in the environment menu until the person removes it
  there: Desktop keeps its connections in its own files, and nothing but the app edits them. Name the
  stale ones from the listing, so they know which to remove.
- **The sessions** that ran on it stay in the sidebar. In Claude Desktop, the app's session tools
  can archive a session (reversible) or delete it (final), each shown to the person for approval
  first; offer that for the sessions that ran on the removed sandbox, archive first, delete only when
  they ask for it. From a terminal there is no such tool: say the sessions are archived from the
  sidebar.

## What this skill does not do

It never removes a sandbox that is running and used today, never touches the project and code
folders, never edits Claude Desktop's files, and never deletes a session without the person's
approval on the app's own card. Making a sandbox is the sandbox skill's job; choosing its packs is
the packs skill's.
