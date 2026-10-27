---
name: work
description: >-
  Keep the plan as facts: what is open, blocked (on whom, why) or deployed, and the messages about
  it. Use when the person says "block this", "what's blocked", "unblock it", "mark it deployed",
  "tell X", "what's waiting for me", "reply to that", or asks where an item stands: `oto work`
  appends the fact and the gates hold it; nothing is written on the item itself.
---

# Work: the plan as facts

A work item is open, blocked or deployed, and nobody writes that on it. Every change is a dated,
attributed fact appended to the graph, and a rule derives the state. Blocks carry their reason and
whom they wait on; messages carry the item they are about. You never edit a state; you record what
happened, and the build says where things are.

## What to do

| The person says | Run |
|---|---|
| "X is blocked on Y: reason" | `oto work set <X> --state blocked --reason "..." --waiting-on <Y> --at <date>` |
| "X is unblocked", "we can go on" | `oto work set <X> --state open --at <date>` |
| "what's blocked, and on whom", "where are we" | `oto work board` |
| "tell Y about X", "ask Y" | `oto work notify <X> --at <date> [--due <date>] [--body "..."]` (`--to` for someone else) |
| "what's waiting for me" | `oto work inbox` (a new session opens with it; under `OTO_PRINCIPAL` it is yours alone) |
| "remind them", "nudge whoever hasn't answered" | `oto work remind --at <date>` (`--dry-run` to see first): one reminder a day per pending message past its due date, never a reply |
| "reply: ...", "answer that" | `oto work reply <message> --body "..." --at <date>` |
| "that settles it", "unblocked, answer them" | `oto work reply <message> --resolve --body "..." --at <date>`: the reply also lifts the block |
| "PR 60 merged X" | `oto work event merged-pr --repo <owner/name> --number <N> --item <X> --environment <qa\|preprod\|prod> --at <date>` |
| "where is X now", "its history" | `oto query ask WK13 ITEM=<X>`, then `oto query entity <transition> --as-of <date>` |
| "who changed X", "who tried to" | `oto audit for <X>`: every write that touched it, refusals included; `oto audit verify` proves the record |

Then `oto build`, and commit the graph file: the repository is the record.

## What the engine refuses, and what to say

- **`deployed` by hand.** Only a merged pull request or a promotion sets it. Say so, and ask which
  pull request or promotion did it.
- **A block without a reason and a waiting-on.** Ask for both, in their words; a block that waits on
  nobody can be unblocked by nobody.
- **A date that is not a date.** `--at` is never defaulted: ask "when did that happen?" and record
  the date they say, never "today" or "yesterday".
- **A name that is several items or none.** The refusal lists them; ask which, and pass the id.
- **A notification with nobody to tell.** The block waits on a decision or an item: ask whom to
  tell, and pass `--to`.
- **An open curate candidate.** Someone is mid-change; finish or abort it first (the **curate**
  skill).

`--by` is the git identity in the project unless the person says otherwise; the inbox finds their
Person by the email recorded on it, else by name.

## Talking with the person

- **Plain, natural language, in the person's words.** Never mention the command, the transition,
  the assertion or the file; say what is now true: "Epic M is blocked on Chiheb since the 24th,
  for the state model decision; he has been told."
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **Read back a block's reason before recording it**: it is what the person it waits on will read.
- **The board is the answer to "where are we"**: blocked first, by whom it waits on.
