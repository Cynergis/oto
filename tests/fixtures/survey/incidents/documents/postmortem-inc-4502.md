# Postmortem: INC-4502 search latency

> **Source:** `inbox/Postmortem INC-4502.docx` · **Type:** Word document · Converted to Markdown by the OTO extraction pipeline.

## Summary

On 2026-04-11 the Search Service breached its SLO (service level objective) for p99 latency for two
hours. It was declared SEV-2. No data was lost.

## Timeline

- 09:15 Alerts fired for the Search Service; the on-call engineer acknowledged them.
- 09:40 The on-call engineer escalated to the Incident Commander.
- 10:05 The Incident Commanders for search and storage agreed the index rebuild was the cause.
- 11:20 The rebuild was paused and latency recovered.

## Impact

The Search Service used 25% of its error budget. MTTR was 125 minutes, well above the target.

## Follow-up actions

- The Release Manager schedules index rebuilds outside peak hours.
- Each postmortem names an owner for every follow-up action.
- Add a rollback plan for index rebuilds to the Search Service runbook.
