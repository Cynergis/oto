# Sandbox kits

A kit is a Docker Sandboxes package ([Docker Sandboxes](https://docs.docker.com/ai/sandboxes/), the `sbx`
CLI): what a sandbox runs, what it may reach, and what it sets up. A tester starts a fully set-up sandbox
from a published kit with one command, and writes no file of their own.

The kit needs **sbx 0.51.0 or later**. That release made `claude` a published kit of schema 3,
`docker.io/sbx/claude`, and a kit of schema 2, as OTO's was, can no longer build on it: v2 and v3 kits do
not combine. `oto sandbox up` and `oto sandbox status` say when the sandbox tool is older, and how to
upgrade it (`brew upgrade docker/tap/sbx` on a Mac, `winget upgrade Docker.sbx` on Windows). A sandbox
made from the schema-2 kit keeps running on 0.51; `oto sandbox up --recreate` makes it again from this
one, and its folders stay.

## oto-gcp

Claude Code with everything an OTO product on Google Cloud needs:

- **OTO:** the engine plugin from its own marketplace (`oto@cynergis-engine`, Cynergis/oto) and the engine
  itself at the version in `oto-gcp.yaml`, with its document parsers and Neo4j driver, installed as the `oto` command that the plugin runs; the `cynergis` marketplace
  (Cynergis/oto-registry) is added but none of its packs is installed: a sandbox starts with the engine
  alone, and the packs a project needs are turned on from the session with the packs skill
  (`/oto:packs`), which installs them for the project and records them in its lock;
- **Google Cloud:** the Google Cloud CLI (`gcloud`, `bq`);
- **documents:** LibreOffice and fonts (older Office files at intake), Chromium (pdf-to-template's renderer);
- **network:** the hosts these need, allowed for this sandbox alone (GitHub, Python packages, Google's APIs
  and downloads, Chromium's downloads).

**What it is made of.** `oto-gcp/oto-gcp.yaml` is a kit set ([schema 3](https://github.com/docker/sandbox-kit-spec/blob/main/docs/spec/SPEC-v3.md)):
Docker's Claude Code kit (`docker.io/sbx/claude`, what `claude` names since sbx 0.51: the agent, its
sign-in and its settings) and OTO's own declarations, merged into one kit when it is published:

| Declaration | What it does |
|---|---|
| `args` | the environment: `OTO_SANDBOX=kit`, `OTO_OUTSIDE_PLUGINS` (`blocked`) |
| `network-policy@1` | the hosts above, at run time; while the install hooks run, Debian's and Google's downloads and Python packages too |
| `lifecycle@1` | the install hooks, the start, and the files `init.sh` and `lock-plugins` in `/home/agent/.oto` |
| `agent-context@1`, `@2` | the note for the sandbox's Claude (`files/home/.claude/CLAUDE.md`) |

System packages are installed once, when the sandbox is created, as root (the lifecycle's install hooks,
after the Claude kit's own). OTO is set up for the agent user at every start (`files/home/.oto/init.sh`):
the first start installs it, later ones find it and take a few seconds. Inside the sandbox,
`/tmp/oto-init.log` says what the start did.

**The files.** A kit set ships no files of its own: what it adds is in its descriptor. The files are
edited as files, in `oto-gcp/files/home`, and `python3 tools/kit_files.py` copies them into the parts of
the descriptor it marks; `tests/test_kits.py` and CI fail while the copy is stale. CI also builds the kit
with Docker's kit frontend at every push, without publishing it: the frontend reads the descriptor
strictly, so a misspelled field fails there rather than in a tester's sandbox.

**A shell lands on the project.** `ssh <name>.sbx` and `sbx run` open in the sandbox tool's default
folder, while the person's folders are mounted at their own paths. `oto sandbox up` passes the project
folder's path as `OTO_PROJECT_DIR` (and the code folder's as `OTO_CODE_DIR`) when it creates the
sandbox, and `init.sh` writes `~/.oto/landing.sh`, sourced from `.bashrc` and `.profile`: an interactive
shell that starts in the home folder or `~/workspace` lands in the project folder; one started elsewhere
is left alone.

**Only the sandbox's own plugins load.** A Claude Desktop SSH session brings the plugins of the person's
computer along: Desktop copies each into `~/.claude/remote/plugins/<run>/<hash>` and starts Claude Code
with one `--plugin-dir` per plugin, so each loads as `<name>@inline`. The Claude sign-in brings the
plugins, skills and connectors of the person's claude.ai account. `files/home/.oto/lock-plugins` keeps
all of them out by merging into the sandbox's `~/.claude/settings.json`, which the Claude kit writes when
the sandbox is created:

| Setting | Keeps out |
|---|---|
| `"<name>@inline": false` under `enabledPlugins`, one per plugin Desktop copied in (named by its manifest, or its folder) | the computer's plugins; there is no wildcard |
| `syncClaudeAiPlugins: false` | the claude.ai account's plugins (`<name>@synced`) |
| `syncClaudeAiSkills: false` | the claude.ai account's skills (`anthropic-skills:<name>`) |
| `disableClaudeAiConnectors: true` | the claude.ai account's connectors (Gmail, Drive, Calendar…) |

It leaves every other key as it is, the sandbox's own `<name>@cynergis` plugins among them, so a plugin of
the computer with the same name as one of the sandbox's is switched off and the sandbox's copy still loads.
The `@builtin` plugins and the `mcp-gateway` server `sbx` declares stay. It keeps a copy of the file as it
was, once (`settings.json.before-oto-plugin-lock`), and changes nothing the second time.

The sandbox's Claude is told which list is its own (`files/home/.claude/CLAUDE.md`, the kit's agent context,
which joins the Claude kit's in its user memory, `~/.claude/CLAUDE.md`): Claude Desktop's `ListPlugins` and `ListSkills` tools describe the person's claude.ai account, where everything they
ever added shows as enabled, so asked "which plugins are on?" it answers from `claude plugin list` and the
skills it can invoke, not from the account.

It runs at every start (`init.sh`) and, through a `SessionStart` hook it adds, at every session start.
`oto sandbox up`, which runs on the computer, also reads the plugins Desktop would hand over (the
claude.ai account's plugins in `~/.claude/plugins/synced`, and Desktop's bundle of the account's
skills) and passes their names (`lock-plugins --names`), so the first session starts without them.
**What it cannot do:** a plugin added on the computer after that is loaded in the first session that
brings it, because Desktop starts Claude Code with it. The hook switches it off then, and tells the
person in a sentence; the next session, or `/reload-plugins` in that one, works without it, and so does
running `oto sandbox up` again before that session. Desktop's folders are its own and undocumented: if
they move, the hook still catches what they hand over, one session late.

To keep the computer's and the account's plugins in the sandbox, create it with
`oto sandbox up --allow-outside-plugins` (or `sbx run … -e OTO_OUTSIDE_PLUGINS=allowed`): the lock then
changes nothing. The choice is made when the sandbox is created. `oto sandbox status` says which way a
sandbox is, and what would load in it. It does not use the managed setting `disableSideloadFlags`, which
refuses `--plugin-dir` and so would most likely stop Desktop's sessions from starting.

**Serving from inside.** `oto sandbox up` publishes ports 8798 and 8799 to the computer's localhost
(`--publish <port>` chooses others, `--publish 0` none). Inside, `oto serve --http 8798` binds all interfaces
and needs no token (the kit sets `OTO_SANDBOX`, which the engine reads), and the person opens
`http://localhost:8798/` on the computer. A port published to a running sandbox forwards from its next start.

**Run it.** `oto sandbox up` does all of it, checks first, and sets up SSH for Claude Desktop's Code tab:

```bash
oto sandbox up --name oto-test --project-id <your Google Cloud project id> --approve-anthropic
```

`--approve-anthropic` records your approval for the kit to use your Anthropic sign-in, which `sbx` asks for
only when run at a terminal. By hand:

```bash
sbx settings set kit.allowedSources '["docker.io/","ghcr.io/cynergis/"]'   # once per machine
export PROJECT=<your Google Cloud project id>
mkdir -p ~/oto-test/project ~/oto-test/code
sbx run ghcr.io/cynergis/oto-gcp:0.20.0 ~/oto-test/project ~/oto-test/code --name oto-test -e PROJECT
```

**Trying a change.** `sbx` builds a local kit folder when it creates a sandbox from it, so a change is
tried before it is released, in a sandbox of its own:

```bash
oto sandbox up --kit kits/oto-gcp --name oto-kit-try --approve-anthropic
```

`sbx` builds the folder in a builder sandbox of its own (`sbx kit builder status`), unless it finds the
`docker` command: then it builds with Docker's default builder, which on Docker Desktop cannot write a
kit (`OCI exporter is not supported for the docker driver`). Run that one command without Docker
Desktop's folder on the PATH (`/usr/local/bin` on a Mac):

```bash
env PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin" oto sandbox up --kit kits/oto-gcp --name oto-kit-try --approve-anthropic
```

**Releasing it.** The kit's version is the engine's. A version bump moves it in the same change, in
`oto-gcp/oto-gcp.yaml` (`version` and the description), in the engine `init.sh` installs, and in the
example above; the copy of `init.sh` in the descriptor moves with the descriptor. `tests/test_kits.py` fails until they all say the new version.

When the release workflow tags `v<version>` (`tag-release.yml`), it publishes the kit from that tag as
`ghcr.io/cynergis/oto-gcp:<version>`, signed (`kit-publish.yml`): Docker's kit frontend builds it through
Buildx, for both Linux platforms, and records the digest Docker's Claude Code kit had, so each release
carries one Claude Code; `sbx kit sign` signs it. It needs:

- the secrets `DOCKER_SBX_USERNAME` and `DOCKER_SBX_TOKEN`, a Docker account and one of its personal access
  tokens, because `sbx` signs only when signed in to Docker;
- the package to grant this repository write access (package settings, Manage Actions access).

Without the secrets the release still tags, and the run says how to publish by hand. The Actions tab runs
`kit publish` by hand, to publish a version again. By hand, from a checkout of the tag:

```bash
python3 tools/kit_files.py --check
gh auth token | docker login ghcr.io --username <your GitHub login> --password-stdin   # a token with write:packages
docker buildx create --use --driver docker-container --name kit
docker buildx build kits/oto-gcp -f kits/oto-gcp/oto-gcp.yaml --platform linux/amd64,linux/arm64 \
  -t ghcr.io/cynergis/oto-gcp:<version> --push
gh auth token | sbx secret set --registry ghcr.io --password-stdin
sbx kit sign ghcr.io/cynergis/oto-gcp:<version>
```
