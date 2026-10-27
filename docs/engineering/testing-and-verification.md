# Testing and verification

## Entry points

Run `python3 scripts/verify.py` from the repository root. It runs, in order:

1. `scripts/check_repository.py`: required files, text hygiene (LF, final newline, no trailing whitespace), local Markdown links, valid JSON, pinned workflow actions, no credential files, no data files (`data/`, database dumps) or oversized files committed.
2. The repository-guard tests in `scripts/tests/` (standard library `unittest`).
3. `uv sync --locked`, `uv run ruff format --check`, `uv run ruff check`, `uv run pytest`. Database tests need PostgreSQL (`docker compose up -d db`, or `PARLAMENT_TEST_DATABASE_URL`); outside CI they are skipped with a message when it is unavailable, in CI they fail.

`python3 scripts/verify.py --repository-only` runs only steps 1–2, for documentation and tooling work; it does not verify the application. It stops on the first failed command and reports a missing `uv` as a failure, not a pass.

## Select checks by changed behavior

| Change | Evidence needed |
| --- | --- |
| Documentation | Repository checks; accurate claims about what is implemented. |
| Parser for a page | Fixture test with a minimal synthetic sample (`tests/fixtures/`): the real page's structure and quirks with invented people and values, plus a changed-shape failure case; then one real run and a spot check against the page. |
| Indicators (attendance, party line, stages) | Small seeded data with hand-derived results (`tests/seed.py`, `tests/test_analytics.py`), including edge cases: member validated after a vote, unaffiliated members, ties. |
| SQL / schema | Tests against a fresh temporary PostgreSQL database (`database_url` fixture); new migrations applied on top of existing ones. |
| Collector behavior | Fetching is not unit-tested against live sites. Test parsing and storage; run the collector once for real and report the counts and `ingest_log` errors. |
| Web pages, API, RSS | FastAPI test client over seeded data (`tests/test_web.py`); browser check of changed pages at desktop and phone width (`uv run parlament serve`). |

Use the minimum useful suite for the change; protect invariants and regressions rather than a coverage number. Do not mock the database to claim SQL correctness.

## Fixtures and isolation

- Tests never touch `data/` or the network. Use temporary databases, `tmp_path` and fixtures.
- Fixtures are minimal and synthetic: copy the structure of one page (ids, nesting, number and date formats, encodings, empty and extra cells), then replace every name and value.
- Use deterministic dates; avoid `today()` in assertions unless the test controls the relationship.

## Honest results

Record commands and outcomes. Separate passed, failed, not run and not applicable. A failing or skipped check is reported as such; never weaken a rule to get a pass. A narrow suppression (`# noqa: XXX`) needs a reason in the same line or the PR.
