# OTO on Google Cloud, end to end: a new pack, a graph in BigQuery, an agent in a sandbox

This test drives OTO on one stack. You design a new pack, **kanban-board**, and build a graph on it.
The graph lives in BigQuery rather than Neo4j, and a server on Cloud Run answers from it behind
Google's identity-aware proxy. Claude, in a sandbox, then asks it questions through OTO's skills and
MCP, signed in as you, with no database login inside the sandbox. Earlier packs and graphs aren't
touched.

[ADR-0015](adr/0015-bigquery-holds-the-graph.md) says why BigQuery holds the graph the way it does, and
[plans/people-and-graphs.md](plans/people-and-graphs.md) describes the server. The wider guide is
[E2E-TESTING.md](E2E-TESTING.md).

## What has run, and what hasn't

**It hasn't run on Google Cloud yet.** The first person to follow this guide is testing it too, so
expect a step to need a fix. Each section says what passes. When one doesn't, keep the step and the
message: [If it fails](#if-it-fails) lists the likely causes.

| Part | Where it stands |
|---|---|
| Making a pack, its gates, publishing it, a project on it | Ran on real GitHub and a real registry, on other packs |
| BigQuery load and read | Tested against an in-memory BigQuery and the real client's signatures, never a real dataset |
| The workflows that load and deploy | Their steps ran with a stand-in for `gcloud`. No container has been built or deployed |
| The server behind the proxy | A real server process, with a test signing key. Never behind Google's proxy |
| Signing in from a sandbox | The real sandbox tool accepted the registration and Google's first sign-in screen opened. Nobody has finished a sign-in |
| Reading the log, removing a person | Tested with stand-ins. Not run in Cloud Logging or IAP |

The Google Cloud commands come from Google's documentation, read on 2026-11-05. `tests/test_e2e_gcp.py`
holds this guide to the engine: every `oto` command parses, and every setting named is one the
workflows read. It can't tell you whether Google agrees.

## Before you start

You need these on your computer:

- **The engine, in a release later than 0.21.2**, which has none of this. `bigquery` is needed only for
  the optional check in step 11.
- **The sandbox tool**, 0.51 or later, signed in with `sbx login`.
- **`gcloud` and `bq`**, signed in with `gcloud auth login` as someone who owns the project.
- **`gh`**, signed in, with the `repo` and `workflow` scopes and the right to create repositories in
  the organisation.

You also need a Google Cloud project with billing on, and a Google account to read the graph with.
Nothing here is sized or priced yet, so check the project's billing report when you finish.

```bash
uv tool install --force "oto-kg[intake,neo4j,bigquery] @ git+https://github.com/Cynergis/oto@v<version>"
oto version
sbx version
```

Set these in the terminal you use for every step on your computer. None of them is a secret:

```bash
export PROJECT=<your Google Cloud project id>
export REGION=europe-west1                                     # one region, for Cloud Run and the dataset
export ME=<the Google account you sign in with>
export ORG=Cynergis
export PACK=kanban-board                                       # the registry already has a pack called kanban, and publishing that name would replace it
export GRAPH=team-board                                        # the graph's sandbox, repository and slug. Its server is team-board-kg
export DATASET=team_board                                      # one dataset per graph. BigQuery names take no hyphens
export READER=board-reader                                     # the sandbox that reads the graph
export DEPLOY=$GRAPH-deploy@$PROJECT.iam.gserviceaccount.com   # builds the container and deploys it
export LOAD=$GRAPH-load@$PROJECT.iam.gserviceaccount.com       # loads BigQuery on a merge
export READ=$GRAPH-read@$PROJECT.iam.gserviceaccount.com       # what the server runs as
```

To choose another pack name, change `PACK` and check that the registry doesn't already have it:

```bash
gh api "repos/$ORG/oto-registry/contents/packs" --jq '.[].name'
```

## 1. The pack: a Kanban vocabulary, by interview

A sandbox holds the workspace, a pack in the making, and a new private repository backs it:

```bash
GITHUB_TOKEN="$(gh auth token)" oto sandbox up --name "$PACK" --kind ontology --repo "$ORG/$PACK" --github-token-env GITHUB_TOKEN --approve-anthropic --init-policy balanced
```

`--approve-anthropic` is your yes for the sandbox to use your Claude sign-in. `--init-policy` counts only
when no network policy is set yet. The token is used for this one command and stored as the
sandbox's GitHub secret, never in a file.

Open it in Claude Desktop: the Code tab, a new session, the environment menu, **SSH**, **Add SSH
connection**, with the host `kanban-board.sbx`. Then choose the project folder it printed. From a
terminal, `sbx run --name "$PACK"` does the same. Then ask:

> Use the ontology-interview skill to design a Kanban vocabulary with me.

It starts from the questions a board must answer, not from a list of nouns. Ten real ones are plenty
here: which cards are blocked and by what, which column is over its limit, how long a card has been
in progress, who holds what. It shows the classes each question needs and asks before writing
anything. It leaves each term's confirmation empty until you've read the reason and agreed, because
the strict check refuses a term nobody confirmed.

Claude runs the gates in the sandbox, in the project folder. You can run them too:

```bash
oto pack format .
oto pack check . --strict
oto pack try .
oto query --project trial questions
```

**Pass** when the strict check is clean and the trial answers every question the pack requires.

Ask Claude to put it on a branch and open a pull request. `pack check` runs on it. The rules ask for an
approval and a code owner's, and you can't approve your own pull request, so if you're alone you merge
as an administrator, which GitHub records:

```bash
gh pr merge <number> --repo "$ORG/$PACK" --admin --merge
```

Then release it. This adds a pack to the organisation's registry, where every sandbox can see it:

```bash
git -C ~/"$PACK"/project checkout main
git -C ~/"$PACK"/project pull --ff-only
oto pack publish --from ~/"$PACK"/project --to "https://github.com/$ORG/oto-registry.git" --note "The Kanban board vocabulary, first release"
claude plugin marketplace update cynergis
oto pack add "$PACK"
oto pack show "$PACK"
```

**Pass** when `oto pack show` says release 1, and the registry's tags are `kanban-board--v1.0.0` and the
older pack's `kanban--v1.0.0`, with nothing new for the older one:

```bash
git ls-remote --tags "https://github.com/$ORG/oto-registry.git" 'kanban*'
```

## 2. The graph on it, in its own sandbox

```bash
GITHUB_TOKEN="$(gh auth token)" oto sandbox up --name "$GRAPH" --kind knowledge --pack "$PACK" --repo "$ORG/$GRAPH" --github-token-env GITHUB_TOKEN --approve-anthropic
```

This creates the private repository `Cynergis/team-board` with its workflows and branch rules, and names
you the graph's steward. It also creates a store repository beside it, `Cynergis/team-board-store`, for
publishing a SQLite copy. This test doesn't use that copy, so the first `oto deploy` run ends red when
it tries to publish with no token. Turn that off, and let the session route merge on its own:

```bash
gh variable delete OTO_QUERY_REPO --repo "$ORG/$GRAPH"
gh repo edit "$ORG/$GRAPH" --enable-auto-merge
gh api "repos/$ORG/$GRAPH/environments/oto-main/deployment-branch-policies" --jq '.branch_policies[].name'
```

**Pass** when the last command prints `main`. Step 4 relies on it: signing in to Google is held to that
environment, so if it isn't held to `main`, stop here.

The graph starts with the pack's sample, so there's something to load before you add anything. In a
session on `team-board.sbx`, in the project folder:

```bash
oto status --project .
oto query --project . questions
```

## 3. Google Cloud: the services, the dataset, three identities

Each identity does one job. The deployer never reads the graph, the loader only writes this dataset,
and the server only reads it.

```bash
gcloud config set project "$PROJECT"
export NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com compute.googleapis.com iap.googleapis.com bigquery.googleapis.com iamcredentials.googleapis.com sts.googleapis.com cloudresourcemanager.googleapis.com
gcloud beta services identity create --service=iap.googleapis.com --project="$PROJECT"
bq mk --dataset --location="$REGION" "$PROJECT:$DATASET"

gcloud iam service-accounts create "$GRAPH-deploy"
gcloud iam service-accounts create "$GRAPH-load"
gcloud iam service-accounts create "$GRAPH-read"
```

A new identity can take a few seconds to exist. If a grant below says it doesn't, run the grant again.

The server reads this dataset and nothing else. Reading runs no query job, so reading alone isn't billed
as queries and it needs no job role. The loader writes this dataset and may run jobs in the project:

```bash
bq query --location="$REGION" --use_legacy_sql=false "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`$PROJECT\`.$DATASET TO \"serviceAccount:$READ\""
bq query --location="$REGION" --use_legacy_sql=false "GRANT \`roles/bigquery.dataEditor\` ON SCHEMA \`$PROJECT\`.$DATASET TO \"serviceAccount:$LOAD\""
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$LOAD" --role=roles/bigquery.jobUser --condition=None --quiet
```

The deployer builds from source, deploys, and lets the proxy call the service. It may run the server
as `$READ`. The build runs as the project's default identity, which Google says may need its role
granted by hand:

```bash
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY" --role=roles/run.admin --condition=None --quiet
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY" --role=roles/run.sourceDeveloper --condition=None --quiet
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY" --role=roles/iap.admin --condition=None --quiet
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$DEPLOY" --role=roles/serviceusage.serviceUsageConsumer --condition=None --quiet
gcloud iam service-accounts add-iam-policy-binding "$READ" --member="serviceAccount:$DEPLOY" --role=roles/iam.serviceAccountUser --quiet
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$NUMBER-compute@developer.gserviceaccount.com" --role=roles/run.builder --condition=None --quiet
```

These are the roles Google lists for deploying from source with IAP, and they may be more than a
deployer needs. Tightening them is for after the run.

**Pass** when `bq ls "$PROJECT:"` lists the dataset and `gcloud iam service-accounts list` lists the three
identities.

## 4. GitHub signs in to Google with no stored key

GitHub proves which workflow is asking, and Google trusts that for this repository only. A workflow on a
branch can ask for that proof too, so the provider also requires the environment `oto-main`, which
deploys from `main` alone (step 2 checked it). Both workflows that need Google run in it.

```bash
gcloud iam workload-identity-pools create github --project="$PROJECT" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc "$GRAPH" --project="$PROJECT" --location=global --workload-identity-pool=github --display-name="$GRAPH on main" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" --attribute-condition="assertion.repository == '$ORG/$GRAPH' && assertion.environment == 'oto-main'"
export MEMBER="principalSet://iam.googleapis.com/projects/$NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$ORG/$GRAPH"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY" --role=roles/iam.workloadIdentityUser --member="$MEMBER" --quiet
gcloud iam service-accounts add-iam-policy-binding "$LOAD" --role=roles/iam.workloadIdentityUser --member="$MEMBER" --quiet
export PROVIDER=$(gcloud iam workload-identity-pools providers describe "$GRAPH" --project="$PROJECT" --location=global --workload-identity-pool=github --format="value(name)")
```

Repositories created since July 2026 have a new default subject in GitHub's token, so this checks the
repository and environment rather than the subject. Google says changes here can take up to five
minutes to reach everything.

Then tell the repository. These are settings, not secrets:

```bash
gh variable set OTO_GCP_PROJECT --repo "$ORG/$GRAPH" --body "$PROJECT"
gh variable set OTO_GCP_REGION --repo "$ORG/$GRAPH" --body "$REGION"
gh variable set OTO_BIGQUERY_DATASET --repo "$ORG/$GRAPH" --body "$DATASET"
gh variable set OTO_GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$ORG/$GRAPH" --body "$PROVIDER"
gh variable set OTO_GCP_SERVICE_ACCOUNT --repo "$ORG/$GRAPH" --body "$DEPLOY"
gh variable set OTO_GCP_LOAD_SERVICE_ACCOUNT --repo "$ORG/$GRAPH" --body "$LOAD"
gh variable set OTO_GCP_RUNTIME_SERVICE_ACCOUNT --repo "$ORG/$GRAPH" --body "$READ"
```

`OTO_SERVER_MEMORY` is optional. The default is 1Gi, and the container holds a copy of the graph in
memory.

## 5. The first load into BigQuery

From here on, a merge that changes the graph loads it. For the first load, run the workflow by hand:

```bash
gh workflow run oto-deploy.yml --repo "$ORG/$GRAPH"
gh run watch --repo "$ORG/$GRAPH"
bq ls "$PROJECT:$DATASET"
bq query --location="$REGION" --use_legacy_sql=false "SELECT id, type, label FROM \`$PROJECT.$DATASET.nodes\` LIMIT 10"
```

Pick the newest run when `gh run watch` asks.

**Pass** when:

- the run says `bigquery: loaded`, then `bigquery: verified: the loaded graph matches the build`
- the dataset holds `oto_builds`, a table `<table>__b1` for each table, and a view under each plain name
- your query returns the pack's sample

Run the workflow once more. **Pass** when it says the dataset already holds this build, and `bq ls` shows
no `__b2`.

## 6. The server on Cloud Run, behind the proxy

If the project has no organisation, or you sign in from outside it, read this first:

```bash
gcloud projects describe "$PROJECT" --format="value(parent.type)"
```

- **It prints `organization`, and your account is in that organisation:** carry on. The proxy's own
  sign-in works for people inside the organisation with nothing to set up.
- **Otherwise:** Google says the first time you turn the proxy on may have to happen in the console. In
  the console, open **Google Auth Platform**, then **Branding**, choose **External** as the audience, and
  add yourself as a test user. Run the workflow below. If it stops on that setup, open the service in
  Cloud Run, turn on IAP under its security settings, and rerun the workflow. Then on the
  Identity-Aware Proxy page, open the service's settings, choose **Custom OAuth**, then **Auto Generate
  Credentials**, and save. This way its secret stays in the console.

Deploy it:

```bash
gh workflow run oto-server.yml --repo "$ORG/$GRAPH"
gh run watch --repo "$ORG/$GRAPH"
gcloud run services describe "$GRAPH-kg" --region "$REGION"
export URL=$(gcloud run services describe "$GRAPH-kg" --region "$REGION" --format='value(status.url)')
curl -s -o /dev/null -w '%{http_code}\n' "$URL/api/status"
```

**Pass** when the workflow builds the container and deploys it, the description says `Iap Enabled: true`,
and `curl` gets a redirect to Google's sign-in or a refusal, never `200`.

Now let yourself in. Access is one person at a time:

```bash
gcloud iap web add-iam-policy-binding --member="user:$ME" --role=roles/iap.httpsResourceAccessor --region="$REGION" --resource-type=cloud-run --service="$GRAPH-kg"
```

Open `$URL/api/status` in a browser and sign in.

**Pass** when you see `"backend": "bigquery"`, `"serving": true` and a `build_seq`. That shows the proxy
reaches the service, the server trusts the proxy's signature, and it read the graph from BigQuery with
no login. It involves no sandbox, so if this fails, the problem is in the deployment. Note how long this
first answer took: a server starting from zero copies the whole graph first.

## 7. A client for signing in from a sandbox

The proxy's own sign-in is for a browser, and Google doesn't let a program use it. A program needs a
desktop client of your own, on the proxy's allowlist.

In the console, open **Google Auth Platform**. If it asks you to set up **Branding** first, do so, with
**Internal** as the audience inside an organisation. Then under **Clients**, create a client of type
**Desktop app**. Its id isn't a secret. Its secret stays with you and goes straight to the sandbox tool in step 8. Don't
paste it into a chat or a file.

```bash
export CLIENT_ID=<the id Google gave the client>
cat > iap-programmatic.yaml <<EOF
access_settings:
  oauth_settings:
    programmatic_clients: ["$CLIENT_ID"]
EOF
gcloud iap settings set iap-programmatic.yaml --project="$PROJECT" --resource-type=cloud-run --region="$REGION" --service="$GRAPH-kg"
```

The file holds the client's id alone. **Pass** when this shows the id:

```bash
gcloud iap settings get --project="$PROJECT" --resource-type=cloud-run --region="$REGION" --service="$GRAPH-kg"
```

## 8. An agent in a sandbox, reading through MCP

This is what the test is for. The folder holds an address and no copy of the graph. The sandbox holds
no login and no token: the sandbox tool signs you in on your computer and passes the requests through.

```bash
oto graphs add "$GRAPH" --server "$URL/mcp" --client-id "$CLIENT_ID" --subject "A team's Kanban board: its cards, columns and limits" --project ~/"$READER"/project
sbx secret set "mcp:$GRAPH-kg:client_secret"
oto sandbox up --name "$READER" --approve-anthropic
sbx mcp auth "$GRAPH-kg"
sbx mcp auth status "$GRAPH-kg"
sbx exec "$READER" -- sh -c 'env | grep -ciE "neo4j|client_secret"'
```

`sbx secret set` asks for the client's secret and keeps it. `sbx mcp auth` opens your browser.

**Pass** when you sign in as yourself, the status says you're authorized, and the last command prints `0`.

Then open a session on `board-reader.sbx`, in the project folder, and ask something the sample
answers:

> Which cards are on the team's board, and where does each stand?

**Pass** when Claude answers from the graph, through OTO's skill and the graph's tools, with its sources and
dates, and says so plainly when the graph doesn't know. A sign-in lasts about an hour. When it stops
answering, run `sbx mcp auth` again, or ask Claude to use the `team-board-kg-authorize` tool.

## 9. A change reaches the reader

In a session on `team-board.sbx`:

> Add a card to the team's board: "Write the release notes", in progress.

Claude uses the curate skill. It says what it understood, checks for contradictions and shows you the
exact change, and applies it only on your yes. Your yes is the approval on this route, so the pull
request merges on its own when the checks pass. Watch it, then the load:

```bash
gh pr list --repo "$ORG/$GRAPH" --state merged --limit 1
gh run watch --repo "$ORG/$GRAPH"
bq ls "$PROJECT:$DATASET"
```

Ask the reader's Claude the same question again.

**Pass** when:

- the pull request merged with no second person
- the load says `as build 2`
- the dataset holds `__b1` and `__b2`
- the reader sees the new card about a minute after the load, with no restart

Note how long it took. A running server looks for a new load at most every 60 seconds.

## 10. Who read what, and taking someone away

```bash
gcloud logging read 'jsonPayload.event="oto.read"' --limit 5 --project "$PROJECT"
gcloud iap web remove-iam-policy-binding --member="user:$ME" --role=roles/iap.httpsResourceAccessor --region="$REGION" --resource-type=cloud-run --service="$GRAPH-kg"
```

**Pass** when the log shows your question under your email, as `principal`, and your next question is
refused while everything else about the sandbox still works. Note how long the refusal took to arrive,
since Google's changes aren't instant. Then let yourself back in with the command from step 6.

## 11. Optional: the store's conformance kit, on the real service

This needs `gcloud auth application-default login`, and it runs in the graph's folder on your computer.

```bash
oto build --project ~/"$GRAPH"/project
OTO_BIGQUERY_PROJECT="$PROJECT" OTO_BIGQUERY_DATASET="$DATASET" oto connectors check bigquery --project ~/"$GRAPH"/project
```

**Pass** when the kit passes. It leaves two scratch datasets, `team_board_kit_a` and `team_board_kit_b`,
for you to remove.

## If it fails

| What you see | What it probably means | What to do |
|---|---|---|
| `google-github-actions/auth` says permission denied, or the token is refused | The provider's condition didn't match, or the grant hasn't reached everything yet | Check the repository's name and that the job ran in `oto-main`. Wait five minutes and rerun |
| The build says the caller can't act as a service account | The deployer can't use the build's identity | Grant `roles/iam.serviceAccountUser` on `$NUMBER-compute@developer.gserviceaccount.com` to `$DEPLOY` |
| The deploy says `Setting IAM permissions failed` | Google's doc says this can happen the first time in a new project | Run the workflow again |
| A warning that the project may need setup through the console | A project with no organisation | Follow the second case in step 6 |
| A load fails with `Not found: Dataset`, naming a location | OTO's client names no location, and BigQuery didn't work it out from the dataset | Keep the message: this needs a fix in the engine |
| `/api/status` says `serving` is false, with a reason | The server can't read the dataset | Check `OTO_GCP_RUNTIME_SERVICE_ACCOUNT` and the `dataViewer` grant. `gcloud run services logs read "$GRAPH-kg" --region "$REGION"` has the rest |
| The browser sign-in works and the sandbox gets `401` or `403` | The client isn't on the proxy's allowlist, or the proxy doesn't accept the token | Check step 7. If `programmatic_clients` is set and it's still refused, try setting it for the whole project: the same command with `--project` alone |
| Google says `redirect_uri_mismatch`, `invalid_target` or `access_denied` | The sandbox tool and Google disagree about the sign-in | See below |

**The sign-in is the step most likely to fail.** It needs the sandbox tool's OAuth flow, Google's
authorization server and the proxy to agree, and nobody has finished it. If they don't, the way around
is a small proxy on the computer, which fetches a token from Google and sits between the sandbox
tool and the server. That proxy is not built. Steps 1 to 6 don't depend on the sign-in, so what you've
proven by then still stands.

## What to record

Note for each step whether it passed and what you had to change. Then add what's true to
[plans/people-and-graphs.md](plans/people-and-graphs.md), and turn each fix into a change here, so the
next person doesn't meet it. Note these numbers, because nothing here has measured them:

- how long the server takes to answer after starting from zero
- how long a change takes to reach a reader
- how long removing someone takes to apply

## Cleaning up

These commands delete things and some can't be undone, so read each one before you run it. The dataset
holds the graph, and `graph.json` in the repository can build it again.

```bash
oto sandbox rm "$READER" "$GRAPH" "$PACK"
gcloud run services delete "$GRAPH-kg" --region "$REGION"
bq rm -r -d "$PROJECT:$DATASET"
gcloud iam workload-identity-pools delete github --project="$PROJECT" --location=global
gcloud iam service-accounts delete "$DEPLOY"
gcloud iam service-accounts delete "$LOAD"
gcloud iam service-accounts delete "$READ"
gh repo delete "$ORG/$GRAPH"
gh repo delete "$ORG/$GRAPH-store"
gh repo delete "$ORG/$PACK"
```

Some things stay until you remove them: the sandbox's folders on your computer, the pack in the registry
at release 1, the OAuth clients in the console, and the build's images and source in Artifact Registry and
Cloud Storage.

## What this does not cover

- A second person: this runs as one, which is why step 1 merges as an administrator. Sections 39 and 40 of
  [E2E-TESTING.md](E2E-TESTING.md) cover two.
- Promotion through dev, test and prod: a merge loads one dataset.
- A very large graph: the server holds a copy in memory, and nobody has measured where that stops
  working.
- `oto repo retire`, which knows Neo4j and has no BigQuery equivalent yet.
- Earlier packs and graphs, which stay on Neo4j or SQLite until someone chooses to move them.
