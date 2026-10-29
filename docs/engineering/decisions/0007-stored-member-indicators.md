# ADR 0007: Member indicators stored after each collection

Status: accepted. Date: 2026-10-29. Related tasks: P1, P5.

## Context

The member list, profiles, county pages and the group-switching page all read `MEMBER_OVERVIEW` (attendance, party-line voting, activity counters). The query reads every nominal vote record (about 450,000 rows) for all 1,433 members. It took about 1.1 s in PostgreSQL on every request, whatever the filter, so these pages took 1.2–1.9 s. The indicators change only when data is collected.

## Decision

`analytics.refresh` stores the query's result as the materialized view `member_overview`. It drops and recreates the view each time, so the stored definition is always the query in `analytics.py`. The view is refreshed:

- when every `parlament ingest ...` command ends, including one stopped by a bot check;
- by `init-db`;
- after each scheduler job, and before the weekly exports.

Pages, the API and the exports read the view. The web app only creates it when it is missing (`ensure_overview`), for a database that existed before the view did.

## Alternatives and consequences

- **Optimizing the query in place:** the party-line join over all records is the main cost; it would still be hundreds of milliseconds.
- **A cache in the web process:** it would have to know when the data changes, and the API and exports would not share it.
- **An ordinary table:** it would repeat the column list in a migration.

Data written outside the CLI or the scheduler (for example by hand in `psql`) shows up only after `parlament init-db` or the next collection. Recreating the view takes about a second and blocks readers of the view for that time. To drop the view, remove `refresh` and read `MEMBER_OVERVIEW` inline again.

## Verification

- `/parlamentari` went from 1.87 s to 0.03 s; with a county filter, 1.85 s to 0.009 s.
- `/traseism` went from 1.85 s to 0.009 s, and a profile from 1.23 s to 0.03 s.
- The member votes on a profile now compute the group line only for the votes on the page.
- `tests/test_analytics.py::test_overview_is_stored_and_recreated` covers creation when the view is missing and the refresh.
