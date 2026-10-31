---
name: packs
description: Choose which OTO packs and plugins are turned on where Claude works, from a checklist or by advice, and turn them on: a sandbox starts with the engine alone, and this skill adds what the project needs. Shows what the registry offers as a select list with checkboxes (the question tool, several answers), or asks what the work is about and recommends; installs the chosen ones for the project, records them in the lock, and says the one step left. Use when someone asks "which packs can I turn on", "show me the plugins", "what should I install for this project", "turn on the ddd pack", "add the report packs", or opens a project in a sandbox that has only the engine. Runs inside the sandbox or on a computer; never changes what the running session has loaded.
---

# Packs: what is on, what could be, and turning it on

A sandbox made from OTO's kit starts with the engine plugin alone (`oto@cynergis-engine`). Everything
else OTO offers is a pack or a plugin of the `cynergis` registry, turned on per project. This skill is
how the person chooses, from the session they work in, in Claude Desktop over SSH or in a terminal.
It runs `claude plugin install` and `oto lock --use`; the person types `/reload-plugins`, the one
thing Claude cannot do for a session that is already running.

## Talking with the person

- **Plain, natural language, in the person's words.** Say "the domain-model pack", not `ddd@cynergis`;
  say "turned on", not "installed at project scope". No file names, commands or what a command
  printed, unless they ask.
- **Technical details only when the person asks for them.** Never offer them, not even as a choice.
- **The same clear shape every time:** say what we are about to do, show the choice, read back what
  you understood in plain sentences, confirm, do it, then say what is next.
- **Their session, their choices.** Nothing is turned on or off without their yes.

## 1. What is there

Three things, read before showing anything:

1. **What the registry offers.** The marketplace's manifest, where Claude Code keeps its copy:
   `~/.claude/plugins/marketplaces/cynergis/.claude-plugin/marketplace.json` (`claude plugin
   marketplace list` says whether the `cynergis` marketplace is known; if not, add it with
   `claude plugin marketplace add Cynergis/oto-registry`). Each entry has a `name`, a one-line
   `description`, a `category` (software, product, reporting, data, insurance, organization,
   professional-services) and a `version`. `oto pack list` adds what kind each pack is: a *pattern of*
   the architecture (agent, ddd, medallion), a *binding* of it (platform), a *playbook* (product), a
   *product type* (product-report), a *domain feature* with tools of its own (work, data, policy), the
   *estate* and the *reified model* themselves (`portfolio`, `product`, `software-architecture`,
   `architecture`), which the pattern packs extend, and a *domain vocabulary* on `oto-core` alone
   (`auto-claims`, `organization-process`, `professional-services`). A sandbox, or a machine with the
   engine alone, has no domain vocabulary until a pack is turned on: the engine ships `oto-core`, its own
   schema, and no other ([ADR-0011](../../docs/adr/0011-a-domain-vocabulary-is-a-pack-of-the-registry.md)). oto-factory and pdf-to-template are plugins from their own
   repositories, listed beside the packs.
2. **What is on already.** `claude plugin list`: each `<name>@cynergis` with its version and whether it
   is enabled. Leave those out of the choice, or show them as "already on" in one line.
3. **What the project is.** `oto status --project .` (or `--json`) names the project's ontology and the
   packs it already declares; a project is where `project.config.json` is. Outside a project, the
   choice still works, at the person's own scope (§4).

## 2. The checklist

The person wants to see what there is and tick what they want. Use the question tool with several
answers allowed (a select list with checkboxes), one question per group, each option a pack with its
description in one sentence and its kind in a few words. The tool takes at most four options per
question and four questions per screen, so:

- Group by category, software first, and leave out what is already on. A group of more than four
  splits into two questions ("Architecture packs, 1 of 2"); more than four groups go on a second
  screen, after the first is answered.
- Put the packs that fit the project first within a group (§3), and say so in the description:
  "fits: this project composes software-architecture".
- The option label is the pack's name as people say it (Domain model, Platform binding, Report
  types); the description is the registry's sentence, shortened to one line, then the kind.

Read the ticked ones back in a sentence ("The domain-model pack and the platform binding, for this
project") and confirm. Nothing is turned on from the screen itself.

## 3. The advice

The person wants help deciding. Ask at most two plain questions, only what the project does not
already say: what the work is about, and whether it has a cloud, reports, or a domain of its own.
Then recommend from what the registry's kinds mean, and show the recommendation through the same
checklist (§2), ticked by default, so they confirm rather than browse:

| The project | Recommend |
|---|---|
| describes a software estate (systems, components, interfaces, where they run) or an architecture to trace to decisions and code | `software-architecture` for the estate, or `architecture` when the model is to carry its decisions, requirements and code map (it brings the estate); then the pattern packs below |
| composes `software-architecture` or `architecture` | the pattern packs for the parts it has: `ddd` for a domain designed with domain-driven design, `agent` for a part people talk to, `medallion` for a data pipeline; `platform` when there is a cloud; `calm` when the architecture is written as a CALM model; `oto-factory` when a component is to be built from the graph |
| has stores to describe, or access to them to govern | `data` for a store's schema, lineage, usage and meaning as facts (its `data-meaning` skill drafts, a person confirms); `policy` on top of it when who may do what with the data is written down, compiled and held to; `work` for the plan as facts, with the inbox a session opens with |
| is a product, from idea to knowledge base | `product` (its playbook leads the journey), `work` for the plan as facts |
| produces reports | `product-report`, `report`, `report-medallion` when a pipeline feeds them, `pdf-to-template` to make a template from a sample PDF |
| describes an organisation, an engagement, insurance claims | `organization-process`, `professional-services`, `auto-claims` |
| runs steps that an agent executes | `flow` |

Say in one sentence why each recommended pack fits, and name one or two that would also fit but are
not needed yet, so the person knows the door is open.

## 4. Turning it on

With their yes, for each chosen pack, from the project folder:

```bash
claude plugin install <name>@cynergis --scope project    # the choice lands in the project's .claude/settings.json and travels with it
oto lock --use <name>@cynergis,... --project .           # declared, with the engine plugin, and the lock records it
```

Outside a project, `claude plugin install <name>@cynergis` alone (the person's own scope: it stays in
this sandbox or on this machine, not with a project). A pack's dependency on the engine resolves to
`oto@cynergis-engine`, which the sandbox and any machine set up for OTO already have; if Claude Code
says the engine is missing, add its marketplace (`claude plugin marketplace add Cynergis/oto`) and
install `oto@cynergis-engine` first.

Then say the one step left, once: the packs load at the next session, or now when they type
`/reload-plugins`. Say which skills arrived with them, as `/<pack>:<skill>`, read from the
installed copy (`oto status` lists them under `packs`), so the person knows what they can now ask for.

Turning one off is `claude plugin disable <name>@cynergis` (kept, not loaded) or `claude plugin
uninstall <name>@cynergis`, then `oto lock --project .` so the lock follows; the same `/reload-plugins`
afterwards.

## What this skill does not do

It never changes what the running session has loaded: that is `/reload-plugins`, the person's. It
never installs the person's own plugins, skills or connectors in a sandbox: the sandbox is kept to
its own on purpose (the sandbox skill, §5). It never writes an ontology or a graph: a pack's own
`start` skill does that, once the pack is on.
