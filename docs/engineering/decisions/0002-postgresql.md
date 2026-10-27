# ADR 0002: PostgreSQL as the store

Status: accepted. Date: 2026-10-27. Related tasks: P0.

## Context

The site is public and multi-user: concurrent reads from web workers while the collector writes. It needs full-text search over bill titles, vote subjects and speech topics, in Romanian, without diacritics.

## Decision

PostgreSQL 18 (Docker image `postgres:18-alpine`), accessed with psycopg 3 and a connection pool, hand-written SQL, numbered migrations in `src/parlament/migrations/` applied by `parlament init-db` (and at scheduler start). Search uses `tsvector` columns on `unaccent`ed text with the `simple` configuration and prefix queries.

## Alternatives and consequences

DuckDB (as in bvb-research) is single-writer and file-based, awkward for a web server reading while the collector writes. SQLite would work for reads but lacks the search and concurrency we want. PostgreSQL adds a service to run; Docker Compose covers it. Tests need a PostgreSQL server (CI service container, local `docker compose up -d db`).

## Verification

`tests/test_analytics.py` and `tests/test_web.py` run against a fresh temporary database per test.
