---
name: start
description: >-
  Start a knowledge base from whatever the person has: a specification or brief, a folder of
  documents, a domain expert, or an existing ontology or pack. Makes the project, gets the
  material in, derives the first questions and hands off to the playbook that builds the
  vocabulary. Use when someone says "get started", "new project", "start from this spec", "I have
  the requirements", "build me a knowledge base for X", or opens an empty OTO project.
---

# Start

Everything in OTO begins with the questions a knowledge base must answer. This skill gets a
person from nothing to a confirmed list of them, by whichever door they came in, and then names
the playbook that turns the list into a vocabulary. It does not design classes; the
**ontology-interview** skill does.

## 1. The project

If there is no project yet:

```bash
oto init --name "<the knowledge base, in words>" --slug <short-name> --project <root>
```

That writes `project.config.json`, an empty `ontology.config.json`, an empty `graph.json` and a
README. Nothing else is assumed. If a project exists, `oto status --project <root>` says where it
is; this skill applies while the vocabulary is `none declared yet`.

## 2. What do you have?

Ask one question, offer these four, recommend from what the person said:

| You have | Do | Then |
|---|---|---|
| **A specification, brief, requirements, a design note** — anything that says what the thing is for and who needs to know what | §3: put it in the inbox, ingest, survey, read it, derive the questions, confirm them | the **ontology-interview** skill from its Phase 2 |
| **A folder of documents** (the corpus itself: handbooks, decisions, transcripts) | the **build-knowledge-base** skill, whole; it runs this derivation as its Gate 1 | — |
| **A person who knows the domain** and the time to answer | the **ontology-interview** skill from its Phase 1: ask them the questions | — |
| **An ontology or a pack that is close** (`oto ontology list`, `oto pack list`) | `oto init --ontology <name>` or `oto init --pack <name>`, then the interview from its Phase 3 to prune and rename | — |

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
- **Quote the engine.** Show `oto status`, `oto ingest` and `oto survey` as they print; do not
  paraphrase a station or invent a command.
- **Never invent facts from a specification.** It says what the system should know, not what is
  true of any instance; the graph is authored later, from documents, through the curate gates.
