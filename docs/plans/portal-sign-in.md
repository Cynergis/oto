# Spec: sign in through the portal, push as the GitHub App

Status: proposed on 2026-11-12. Steps 1 to 3 of the build order are built (2026-11-13) and tested each side alone;
none has been run on a real organisation yet. The engine stays on the person's computer in this spec; "Later: a hosted
engine" says what moves when it doesn't.

## The problem

Today a person who starts a graph needs their own GitHub account, a token from it (`gh auth token`, named with
`--github-token-env`), and the registry added by hand (`oto registry add`). The portal learns of the graph afterwards,
by searching the organisation for the `oto-graph` topic and by scanning repositories for `project.config.json` and
`graph.json`. So:

- a graph exists before anything records who started it or which organization and domain it is for;
- the portal's scan attaches any repository that has those two files;
- everyone who writes to a graph needs a GitHub account with rights on the organisation.

## What changes

1. **A person signs in to the portal before working with OTO.** `oto login` does it from the terminal, through the browser.
2. **The portal's GitHub App writes to GitHub, not the person's account.** The portal hands the engine a token that
   lasts one hour and reaches one repository. The App's private key never leaves the portal.
3. **A graph is recorded when it is created**, with its organization and domain. The portal creates the repository.
   Nothing is discovered by scanning.

`--github-token-env` keeps working as it does today. The engine is shared, and a team without the portal must lose
nothing: the sign-in is another way to get a token, not the only one.

## The rule this changes

Rule 1 of [people-and-graphs.md](people-and-graphs.md) says GitHub holds identity and permissions for changing a graph, and
OTO has no user database. For a tenant of the portal that is no longer true:

| | Today | With this spec, for a portal tenant |
|---|---|---|
| Who the person is | their GitHub login | their portal account |
| Who may write to a graph | GitHub rights, from `.github/oto-access.json` | their role in the portal, on the graph's place |
| Who GitHub sees pushing | the person | the App |
| Who a commit names | the person | the person (name and email from the portal), as its author |

Git stays the source of truth for the graph, and the gates in the repository are untouched.

## The parts

### `oto login`, in the engine

```
oto login [--portal <url>] [--tenant <name>]
oto whoami
oto logout
```

- `oto login` prints a short code and opens the portal's sign-in page for the terminal. The person, signed in to the
  portal, confirms the code there. The engine then receives a session for this computer.
- A person in several tenants picks one on that page, or names it with `--tenant`.
- It writes two files under `~/.oto`, which the engine already uses:
  - `profile.json`: the portal's address, the tenant, the GitHub organisation, the registry, the person's name and email.
    No secret in it.
  - `credentials.json`: the session, readable by the person only (mode 0600).
- The registry in the profile replaces `oto registry add` for that person. `OTO_REGISTRIES` and
  `OTO_REGISTRY_TOKEN` still win when set, for automated jobs.

### The token service, in the portal

One address the signed-in engine calls: "a token for this repository, to read or to write".

- It checks the session, that the person belongs to the tenant, that the repository is one of the tenant's graphs or
  packs, and that the person's role on the graph's place allows the request (Contributor or above to write).
- It asks GitHub for an installation token narrowed to that one repository and to Contents (and Workflows on the
  first push, because the engine adds workflow files).
- It records each token it hands out: who, which repository, read or write, when. This is the record of who did
  what, since GitHub now shows the App.
- It never hands out a token that can create or administer repositories.

### Creating a graph

`oto sandbox up --kind knowledge --pack <pack> --name <name> --organization <o> --domain <d>`, signed in and with
no `--github-token-env`:

1. The engine asks the portal to create the graph. The portal checks the person may create one in that place, creates
   the private repository (and the store repository) as the App, and records the graph in the tenant with its place,
   its pack and who started it.
2. The portal returns a write token for the new repository.
3. The engine lays the project out and pushes the first commit with it, as it does today.

Creating a graph from the portal's own "New graph" page runs step 1 at once, and `oto sandbox up --clone` picks it up.
Without `--organization`, the graph is created not placed and shows in the portal's "not placed" list.

### The token in the sandbox

`oto sandbox up` already stores the token as the sandbox's own GitHub secret, so it never enters the sandbox. An
App token lasts one hour, so it has to be renewed. Proposed: `oto sandbox token <name>`, run on the person's computer,
asks the portal again and replaces the secret; `oto sandbox up` and `oto sandbox doctor` run it, and a refused push
says to run it. Whether the sandbox tool can renew a secret by itself is not checked yet.

### The App's permissions

Today: Contents read, Metadata read. Needed: Contents write, Workflows write, Administration write (used only inside
the portal, to create repositories). Each organisation approves the change once.

## What is not settled

1. **Review by a second person.** A change confirmed in a session needs no other approval (ADR-0013), so that route
   works with no GitHub account. The routes where a steward approves a pull request still need a GitHub account today.
   Approving in the portal, with the App recording it on the pull request, is a later step and needs checking against
   branch rules and code owners.
2. **`.github/oto-access.json`.** It lists GitHub logins. For a portal tenant, either the portal writes it from its
   roles, or the file is left empty and the portal's roles are the only rule. Not decided.
3. **Branch rules and deploy keys.** `oto repo` applies them and needs administration rights. With the App, the
   portal has to do this at creation. Traced on 2026-11-13, in two stages.
   Stage 1, built: once the first commit is pushed, the engine asks the portal (`POST /api/terminal/graph-setup`)
   and the portal, as its App, sets the environment `oto-main` that only main deploys from, main's deploy key in
   it (`OTO_MAIN_DEPLOY_KEY`), a write deploy key of the store (`OTO_QUERY_REPO_KEY`, which `oto publish` uses over
   SSH when there is no token: an App's token lasts an hour, so none can be stored), and the store's address
   (`OTO_QUERY_REPO`, as a variable of that environment). The App needs Environments, read and write, beside
   Administration. The portal makes each key pair, seals the private half for GitHub and keeps nothing.
   Stage 2, not built: the branch rules and the code owner. A code owner is a GitHub login or team, and a person
   who signed in through the portal has neither; and once the rules are on, nobody pushes to main, so a person
   with only the portal's token needs a way to open a pull request (the App has no Pull requests permission) and
   to have it reviewed (decision 1 above). `oto publish --promote` still takes a token only.
4. **The portal's sign-in for a terminal.** The portal uses Supabase for sign-in. That it can issue and renew a
   session for a terminal as described is assumed, not tested.
5. **Graphs made without the portal.** They keep the `oto-graph` topic and the registry's graph directory. The
   portal keeps reading those; only the scan for the two files goes.

## Build order

1. **Portal:** the sign-in page for a terminal, the token service, the record of tokens. The App's permissions are
   widened by the tenant's owner.
2. **Engine:** `oto login`, `oto whoami`, `oto logout`, and the profile.
3. **Engine and portal:** create a graph through the portal, with its place; `oto sandbox up` and `--clone` use the
   sign-in when no token variable is named.
   Built: with no `--repo`, the repository is `<the tenant's organisation>/<the sandbox's name>`. Running the same
   `oto sandbox up` again stores a new one-hour token, which is most of step 4. Not built: the portal sets no branch
   rules, code owner, deploy key or store variable on the repository it makes (point 3 below); a pack's workspace (`--kind ontology`) still takes a token of the person's own.
   Built after: `oto login` adds the tenant's registry, and a registry or a pack's source in the tenant's organisation
   is read with a one-hour token from the portal, so `oto registry add` and a GitHub account are not needed to
   install a pack. `OTO_REGISTRY_TOKEN` still wins. Not built: the sandbox's own copy of the registry, as a Claude
   Code marketplace, is still read with whatever GitHub access the sandbox has.
4. **Engine:** renewing the sandbox's token.
5. **Portal:** remove the scan for unmarked repositories.
   Built: a sync finds a graph by the `oto-graph` topic, or holds it already (made by the portal, or linked by an
   earlier sync). It opens no other repository looking for one. A graph the scan linked before stays linked. A pack's
   workspace is still looked for by its manifest.

Each step is run on the real organisation before the next starts.

## Later: a hosted engine

When the engine runs on a server and Claude reaches it over MCP, the browser sign-in authenticates the MCP server
itself and nothing is stored on the person's computer. The token service stays, called from inside the server, and
GitHub sees the same App. Steps 1 and 3 carry over unchanged; steps 2 and 4 are replaced.
