# Postmortem: INC-4471 checkout outage

> **Source:** `inbox/Postmortem INC-4471.docx` · **Type:** Word document · Converted to Markdown by the OTO extraction pipeline.

## Summary

On 2026-03-04 the Checkout Service returned errors for 41 minutes. The incident was declared SEV-1
by the on-call engineer at 14:02 and resolved at 14:43. Mean Time To Recovery (MTTR) for the quarter
rose to 38 minutes as a result.

## Timeline

- 14:02 The on-call engineer paged the Incident Commander after the error rate crossed the SLO.
- 14:10 The Incident Commander opened a bridge and assigned a Communications Lead.
- 14:25 The deploy of build 7.14.2 was identified as the cause; the Release Manager approved a rollback.
- 14:43 Rollback completed; the Checkout Service recovered.

## Impact

The Checkout Service burned 60% of its monthly error budget. The Payments API was unaffected, but
the Status Page showed a partial outage for checkout.

## Follow-up actions

- Add a canary stage to the deploy pipeline (owner: Release Manager).
- Every runbook for the Checkout Service gets a rollback plan.
- The on-call engineer rotation adds a second responder for SEV-1 incidents.
