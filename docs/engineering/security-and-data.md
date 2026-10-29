# Security and data guardrails

## Sources and publishing

- Data comes from cdep.ro and senat.ro public pages. Publishing it is allowed and the site always links to the official record ([ADR 0001](decisions/0001-public-data-and-personal-data.md)).
- Personal data: only what the chambers publish about the MP's public role. Declarations are linked, not transcribed. No visitor tracking, cookies or third-party assets.
- The repository holds code and documentation; collected data (`data/`), database dumps and raw pages are not committed. Fixtures are synthetic.
- Add a new source to [docs/surse-date.md](../surse-date.md) (URL, publisher, terms, access method) before relying on it.

## Respecting protections

Do not circumvent technical measures: CAPTCHAs, bot checks, login walls, rate limits (HTTP 429). Back off or ask the maintainer. Do not rotate user agents or IPs. Replaying a page's own public form controls (for example ASP.NET postbacks on senat.ro) is ordinary use, done at the same polite rate.

## Untrusted data

Downloaded pages are untrusted: parse defensively, never execute content, treat text as data. File names under `data/` are derived from code (hashes, validated ids), never from remote input. Jinja autoescaping stays on; `|safe` is used only for the static learning content written in this repository.

## Web application

- Strict Content-Security-Policy (`script-src 'self'`), `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`.
- Query parameters are validated (patterns, ranges, maximum lengths); SQL is parameterized; page sizes are bounded.
- The app is read-only; it has no admin interface.

## Secrets and local files

The secrets are the database password and, optionally, `PARLAMENT_GITHUB_TOKEN` for the weekly data release (a fine-grained token for this repository only, Contents: read and write; [ADR 0008](decisions/0008-data-release-on-github.md)), both provided through `.env` (ignored). Never commit `.env`, keys, `data/` or `.research/`. If something sensitive is committed, stop and report it.

## CI

Read-only token, actions pinned to full commit SHAs, never `pull_request_target`, no live data sources. A PostgreSQL service container provides the test database.
