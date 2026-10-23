# On-call handbook

## Severity levels

A SEV-1 is a full outage of a customer-facing service. A SEV-2 is a degradation that breaches an SLO.
Incident Commanders run every SEV-1 and SEV-2 incident.

## Roles

The on-call engineer acknowledges a page within five minutes and escalates to the Incident Commander
when the incident is SEV-1 or SEV-2. The Incident Commander assigns a Communications Lead, who keeps
the Status Page current. The Release Manager approves every rollback during an incident.

## Measures

Mean Time To Recovery (MTTR) is measured from the page to recovery. Each service has an error budget
derived from its SLO; when the error budget is spent, feature deploys stop until it recovers.

## Runbooks

Each service keeps a runbook with a rollback plan. The Checkout Service and the Search Service
runbooks are reviewed every quarter by the Release Manager.
