# ADR 0008: Weekly data release on GitHub

Status: accepted. Date: 2026-10-29. Related tasks: P5.

## Context

The open-data CSVs are regenerated weekly and served at `/date-deschise`, which shows only the latest export. People who want an earlier week, or a download that does not depend on the site, have no copy. The data must not go into the repository: it is about 50 MB and changes every week.

## Decision

`releases.py` packs the weekly export into one archive, `parlament-date-<date>.zip`. The archive holds every CSV plus a `README.md` that gives the source, the row counts and columns, and how to read the values (a blank is not zero; missing from a vote is not a vote against). Next to it, `SHA256SUMS` lets anyone check the download.

After the weekly export, the scheduler publishes the archive as the GitHub release `data-<date>` through the GitHub REST API. `parlament release-data` does the same by hand, or only builds the archive when there is no token.

- The token comes from `PARLAMENT_GITHUB_TOKEN` (`.env`, passed to the `ingest` container). It is a fine-grained token for this repository only, with Contents: read and write. It is never logged or printed.
- If the tag already exists, the run leaves it alone.
- If an upload fails, the half-made release is deleted, so a later run can publish it whole.
- Without a token, the release is skipped and the site keeps serving the CSVs.

The archive contains only the tables listed in `exports.TABLES`. It does not contain the generated summaries (CC BY-NC 4.0) or the raw pages under `data/raw/`.

## Alternatives and consequences

- **A GitHub Actions workflow:** the data lives in the local database, so CI has nothing to publish.
- **The `gh` command line:** it is not in the container, and its sign-in belongs to a person, not to the service.
- **Committing the CSVs:** the history would grow by about 5 MB compressed each week.

The repository's release list grows by one entry each week, about 5 MB each. Older releases can be deleted by hand; the site does not link to them. Revoking the token or removing it from `.env` stops publishing without any other change.

## Verification

- `tests/test_releases.py` checks the archive contents, the README and checksum, and creating the release and uploading its files. It also checks that an existing release is left alone and that a failed upload deletes the release. These tests run against a mocked GitHub API.
- The first release, `data-2026-10-29`, was published by hand with the same layout.
