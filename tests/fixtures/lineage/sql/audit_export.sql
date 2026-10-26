INSERT INTO audit_export
SELECT posting_id, amount_cents FROM postings WHERE posted_at >= '2026-01-01';
