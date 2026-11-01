---
name: start
description: >-
  Start a knowledge base from whatever the person has: a specification or brief, a folder of
  documents, a domain expert, or an existing ontology or pack. Makes the project, gets the
  material in, derives the first questions and hands off to the playbook that builds the
  vocabulary. Use when the way in is still to choose: someone says "get started", "new project",
  "start from this spec", "I have the requirements", "build me a knowledge base for X", or opens an
  empty OTO project. A folder of documents already in hand goes straight to build-knowledge-base.
---

# Start

Everything in OTO begins with the questions a knowledge base must answer. This skill gets a
person from nothing to a confirmed list of them, by whichever door they came in, and then names
the playbook that turns the list into a vocabulary. It does not design classes; the
**ontology-interview** skill does.

## Talking with the person

- **Plain, natural language, in the person's words.** Never say question numbers, ids, class or
  field names, file names or commands, and never paste what a command printed.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to do, ask a few questions at a time,
  read back what you understood in plain sentences, confirm, then say what is next.

## 1. What is being made

Two kinds of thing start here, and the first question is which:

- **An ontology**, to be used by several teams: made in an **ontology workspace**, a pack in the
  making in a directory of its own, by the ontology-interview skill. `oto pack new <name> --to <dir>
  [--extends <base>]` opens it; the questions below are its Phase 1.
- **A knowledge base** on an ontology that exists: a knowledge project started from a pack, whose
  vocabulary is derived from it. `oto pack list` says what exists; `oto pack add <name>` then
  `oto init --name "<the knowledge base, in words>" --slug <short-name> --project <root> --pack <name>`.

When neither a pack nor an ontology fits what the person describes, the ontology comes first, and
the knowledge base is the first project on it. A project with no pack at all
(`oto init --name ... --project <root>` alone) owns its vocabulary and is for a one-off; say so if
that is what the person wants. If a project exists, `oto status --project <root>` says where it is.

## 2. What do you have?

Ask one question, offer these four, recommend from what the person said:

| You have | Do | Then |
|---|---|---|
| **A specification, brief, requirements, a design note** — anything that says what the thing is for and who needs to know what | §3: put it in the inbox, ingest, survey, read it, derive the questions, confirm them | the **ontology-interview** skill from its Phase 2 |
| **A folder of documents** (the corpus itself: handbooks, decisions, transcripts) | the **build-knowledge-base** skill, whole; it runs this derivation as its Gate 1 | — |
| **A person who knows the domain** and the time to answer | the **ontology-interview** skill from its Phase 1: ask them the questions | — |
| **A pack that is close** (`oto pack list`) | `oto init --pack <name>` for the knowledge base; what it lacks is a pack that extends it, made in a workspace (`oto pack new <name> --to <dir> --extends <pack>`) by the interview from its Phase 3 | — |

Usually two combine: a specification *and* an expert (derive, then ask them to add and strike);
an existing ontology *and* a specification (start from the ontology, read the spec to see what it
lacks). Say which combination you are running.

## 3. From a specification

1. Put the material in the inbox and read it in full. Prose, Markdown, Word, PDF and slides all
   extract; a pasted text goes into `inbox/specification.md` with a heading saying what it is.

   ```bash
   oto ingest --project <root>
   oto survey --project <root>
   ```

   The survey lists each document's headings and the phrases that recur; read the extracted
   text under `build/documents/` yourself. Do not skim: the questions must use the words the
   material uses.

2. Derive ten to twenty questions. For each role the specification names or implies, ask of the
   text: what does this person need to know to do their part; what must be true before the next
   step may happen, and who decides; what goes wrong when something is not known; what must
   still be answerable about the past (what was true when, who changed it, why). Write each as a
   question a person would ask, with who asks it. Prefer the ones asked under pressure.

3. Show the list, **labelled as derived by you**, and ask the person to add their own, strike
   what is wrong, and confirm. Nothing is designed until they do. If they are not there, say in
   the project's README that the questions are the agent's reading of the specification, dated,
   and go on.

4. Hand the confirmed list to the **ontology-interview** skill from its Phase 2: the questions
   become classes, relations, attributes, shapes, `questions.json` and the rationale, and the
   gates from there on are that skill's.

## Guardrails

- **Questions before nouns.** The specification will be full of nouns; do not turn them into
  classes. A class with no question behind it does not go in, and the engine refuses it later.
- **The person confirms the list.** A derived question is a guess at what matters; it becomes
  the contract only when someone who knows the domain says so.
- **Read the engine; tell it in plain words.** Base what you say on `oto status`, `oto ingest` and
  `oto survey` as they print, never on memory; show their output only when asked; never invent a
  command.
- **Never invent facts from a specification.** It says what the system should know, not what is
  true of any instance; the graph is authored later, from documents, through the curate gates.
