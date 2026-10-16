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

**Run it:**

```bash
sbx settings set kit.allowedSources '["docker.io/","ghcr.io/cynergis/"]'   # once per machine
export PROJECT=<your Google Cloud project id>
mkdir -p ~/oto-test/project ~/oto-test/code
sbx run ghcr.io/cynergis/oto-gcp:0.11.29 ~/oto-test/project ~/oto-test/code --name oto-test -e PROJECT
```

**Publish it** (the version is the engine's, in `spec.yaml` and in the tag):

```bash
sbx kit validate kits/oto-gcp
gh auth token | sbx secret set --registry ghcr.io --password-stdin     # a token with write:packages
sbx kit push kits/oto-gcp ghcr.io/cynergis/oto-gcp:<version>
```

A new engine release moves `OTO_SOURCE`, `version` and the tag together.
