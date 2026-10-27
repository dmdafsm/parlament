# ADR 0004: Docker Compose deployment

Status: accepted. Date: 2026-10-27. Related tasks: P0.

## Decision

One image (`Dockerfile`, Python 3.12 slim + uv) runs either the web server (`parlament serve`) or the collector loop (`parlament schedule`). `compose.yaml` defines `db` (PostgreSQL 18), `ingest` and `web`; data and the raw cache live in `./data` on the host, the database in a named volume. Ports are published on `127.0.0.1`; a TLS reverse proxy (for example Caddy, `deploy/Caddyfile`) exposes the site publicly. Secrets (database password) come from `.env`, never from the repository.

## Consequences

A single small VPS is enough. Backups: `pg_dump` of the database (it can also be rebuilt from `data/raw` with `--from-raw`).
