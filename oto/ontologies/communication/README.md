# Communication — messages beside the item they are about

On `work`: a `Message` is a fact in the graph, sent by someone to a person, team or role, about a
work item and the block it was sent from. It carries `from`, `body`, `sent`, `status` (pending until
read, replied, resolved) and `due`. Because it is a fact, it is dated, attributed and never edited,
and its answer can move the item it is about.

**The first message is a notification.** `oto work notify <item> --by <you> --at <date> [--due <date>]
[--body "..."]` writes one from the item's block to whom it waits on: the body carries the item, the
block's date, reason and author, then your words. `--to` tells someone else when the block waits on
a decision or an item rather than a person.

Questions (CM1–CM3, awaiting confirmation): what waits for a person (what a session opens with),
what has been said about an item and whether it is settled, which messages are overdue.

**v1 is for internal use.** Identity is whatever `--by` says or the git identity in the project;
anyone can send as anyone until the plugin connection (N2) and the audit log (N6) land. Replies,
resolution and the session-start inbox come next (N3, N4).

This is a first draft: edit it. Keep `regarding` pointing at the block as well as the item, because that
is where the reason lives.

**Reminders (release 3, roadmap N5).** `oto work remind --at <date>` sends, for every pending message
past its due date, one reminder a day: a `Message` of its own from `oto work remind` (or whoever runs
it), to the same recipients, about the same item, `reminder_of` the original and never `in_reply_to`
it, so the original stays pending and CM3 still lists it as overdue; CM4 lists the reminders a message
had. A scheduled workflow runs it for people who are not in a session. The inbox is read under the
principal's identity when one is established (`OTO_PRINCIPAL`, or `--principal`; roadmap N2): a user
sees only the messages addressed to them, and `--as` someone else is refused.
