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
sbx run ghcr.io/cynergis/oto-gcp:0.11.30 ~/oto-test/project ~/oto-test/code --name oto-test -e PROJECT
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
