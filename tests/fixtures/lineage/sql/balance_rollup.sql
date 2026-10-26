-- schedule: nightly at 03:00
/* Rolls the postings up into the daily balances.
   FROM here on, only SQL. */
CREATE OR REPLACE VIEW daily_balances AS
WITH by_day AS (
  SELECT account_id, date(posted_at) AS day, sum(amount_cents) AS balance_cents
  FROM postings
  GROUP BY 1, 2
)
SELECT * FROM by_day;
