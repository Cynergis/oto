-- schedule: nightly at 02:00
-- tool: settlement-job
-- Loads the night's settlements from the custodian file into the postings.
COPY staging_settlements FROM 's3://custodian/settlements/2026-10-26.csv' WITH (FORMAT csv);

INSERT INTO postings (posting_id, account_id, amount_cents, posted_at)
SELECT s.id, a.account_id, s.amount_cents, s.settled_at
FROM staging_settlements s
JOIN accounts a ON a.account_id = s.account_id  -- a comment: FROM nowhere
WHERE s.note <> 'copied from elsewhere';
