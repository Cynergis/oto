# Platform binding: where the product runs, and who decides

Sits on `software-architecture` and so on `product`. The design (the architecture and its patterns)
says what the product does; the binding says how it runs on a given platform, with every detail an
implementing agent needs to build, deploy and test it end to end. It is what the original studio's
architecture asked for (decision records for the platform, the tech stack with versions, resources,
infrastructure per environment, links to code and pipelines), as facts.

- **Where it runs:** the `Platform`, its `Account`s (an AWS account, a GCP project, an Azure
  subscription), and each environment's purpose, region, console and logs, and the repository that
  provisions it.
- **What it runs on and is built with:** the `PlatformService` under each component or store, and
  the `Technology` each component is built with, at a version.
- **Secrets** (`SecretRef`) by name and where they are kept, never their value; the `Pipeline`s that
  deploy each part, and to which environments.
- **Who decides:** each `Choice` the design needs (the cloud, a region, a service, a framework) is
  either decided by a named person, or left to the builder within limits: the options `allowed`, and
  the constraints, decisions or policies it is `bounded_by`. The builder's pick is a `Decision` it
  proposes and a person accepts (`decided_by`). Decisions carry their option, alternatives and
  consequences.

The rules refuse a builder's pick outside its allowed options, a choice left to the builder with no
limits, and a decision accepted with nobody named. Three briefs stop an implementing agent by name
when a detail is missing: `implement-component`, `deploy-component` and `test-end-to-end`.

The sample binds the payments platform the other samples describe to Google Cloud: one production
project in europe-west1, Cloud Run and Cloud SQL, the stack with versions, two secrets in Secret
Manager, two pipelines, and three choices (the cloud and the region decided, the API's framework left
to the builder and confirmed).
