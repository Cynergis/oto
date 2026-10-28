# Sandbox kits

A kit is a Docker Sandboxes package ([Docker Sandboxes](https://docs.docker.com/ai/sandboxes/), the `sbx`
CLI): what a sandbox runs, what it may reach, and what it sets up. A tester starts a fully set-up sandbox
from a published kit with one command, and writes no file of their own.

## oto-gcp

Claude Code with everything an OTO product on Google Cloud needs:

- **OTO:** the `cynergis` marketplace and its plugins (product, software-architecture, product-report, report,
  flow, medallion, report-medallion, platform, work, pdf-to-template, and the engine plugin `oto`), and the
  engine itself at the version in `spec.yaml`, pinned through `OTO_SOURCE`;
- **Google Cloud:** the Google Cloud CLI (`gcloud`, `bq`);
- **documents:** LibreOffice and fonts (older Office files at intake), Chromium (pdf-to-template's renderer);
- **network:** the hosts these need, allowed for this sandbox alone (GitHub, Python packages, Google's APIs
  and downloads, Chromium's downloads).

System packages are installed once, when the sandbox is created (`setup.install`). OTO is set up for the
agent user at every start (`files/home/.oto/init.sh`): the first start installs it, later ones find it and
take a few seconds. Inside the sandbox, `/tmp/oto-init.log` says what the start did.

**Only the sandbox's own plugins load.** A Claude Desktop SSH session brings the plugins of the person's
computer along: Desktop copies each into `~/.claude/remote/plugins/<run>/<hash>` and starts Claude Code
with one `--plugin-dir` per plugin, so each loads as `<name>@inline`. The Claude sign-in brings the
plugins, skills and connectors of the person's claude.ai account. `files/home/.oto/lock-plugins` keeps
all of them out by merging into the sandbox's `~/.claude/settings.json`:

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
sbx run ghcr.io/cynergis/oto-gcp:0.14.0 ~/oto-test/project ~/oto-test/code --name oto-test -e PROJECT
```

**Releasing it.** The kit's version is the engine's. A version bump moves it in the same change, in
four places: `version`, `OTO_SOURCE` and the description in `spec.yaml`, the engine `init.sh` installs, and
the example above. `tests/test_kits.py` fails until they all say the new version.

When the release workflow tags `v<version>` (`tag-release.yml`), it publishes the kit from that tag as
`ghcr.io/cynergis/oto-gcp:<version>`, signed (`kit-publish.yml`). It needs:

- the secrets `DOCKER_SBX_USERNAME` and `DOCKER_SBX_TOKEN`, a Docker account and one of its personal access
  tokens, because `sbx` publishes only when signed in to Docker;
- the package to grant this repository write access (package settings, Manage Actions access).

Without the secrets the release still tags, and the run says how to publish by hand. The Actions tab runs
`kit publish` by hand, to publish a version again. By hand, from a checkout of the tag:

```bash
sbx kit validate kits/oto-gcp
gh auth token | sbx secret set --registry ghcr.io --password-stdin     # a token with write:packages
sbx kit push kits/oto-gcp ghcr.io/cynergis/oto-gcp:<version> --sign
```
