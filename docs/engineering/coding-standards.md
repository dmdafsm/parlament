# Coding standards

## Organization

One package, `src/parlament`. Collectors live in `parlament/ingest/` (one module per source and page family); indicators in `analytics.py`; the website in `web/`; `cli.py` wires commands. See the [architecture](../architecture.md) for table ownership.

- Keep a source's download, parsing and storage together in its module, with parsing in **pure functions** (`parse_*(html) -> dict | list`) separate from fetching, tested against fixtures.
- Each indicator is defined once in `analytics.py`; pages, API and exports call it. Templates only format.
- Route handlers are thin: validate parameters (FastAPI `Query` constraints), call `analytics`/SQL, render.
- Plain functions and small dataclasses. No ORM, repository layer or class hierarchy without a demonstrated need.

## Python

- Python 3.12, type hints on public functions, `X | None`. Ruff formats and lints (line length 120).
- English identifiers and comments; Romanian user-facing text (templates, CLI output; CLI output may be ASCII without diacritics).
- Validate at the boundary and fail loudly when a page changed shape (`ParseError`). A collector may skip one member or bill and continue, but it records the error in `ingest_log`.
- Comments explain reasons and source quirks, not narration.
- Dates are `datetime.date`; vote times are naive Bucharest time as published. Month-precision dates (group/party changes) are the first day of the month with `precision = 'month'`.

## SQL

- Parameterize values (`%s` / `%(name)s`). Dynamic fragments (ORDER BY, table names) come from code constants, never from input.
- Schema changes are new numbered migration files; existing deployed migrations are never edited.
- Upserts use `ON CONFLICT`; per-entity lists use delete-and-replace inside one transaction.
- Push filtering and aggregation into SQL.

## Collectors

- Polite by default: one `Fetcher` per run, `PARLAMENT_REQUEST_DELAY` between requests, no parallel requests to a site, HTTP 429 stops the run.
- Use pages as a visitor would; do not bypass protections ([security and data](security-and-data.md)).
- Raw pages are cached under `data/raw/<site>/`; `--from-raw` re-parses after a parser fix.
- Keep provenance: every stored entity has its official `url`; every run writes `ingest_log`.

## Web

- Server-rendered HTML that works without JavaScript; HTMX only enhances (partial templates `_*.html`).
- Material Design 3 via Beer CSS classes; custom CSS in `static/app.css` only. No inline scripts (CSP `script-src 'self'`).
- Check every changed page at phone width.

## Dependencies

Add with `uv add`, commit `uv.lock`. Prefer the standard library and the existing stack. Frontend assets only through `scripts/vendor_assets.py`.
