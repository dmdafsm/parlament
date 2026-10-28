# ADR 0005: archived copies for development

Status: accepted. Date: 2026-10-27. Related tasks: P0.

## Context

On 2026-10-27 cdep.ro refused TCP connections from the development network (DNS resolved; ports 80/443 timed out from a Romanian IP), while senat.ro worked. Collectors and the site still had to be built and checked on real page structures.

## Decision

`PARLAMENT_FETCH_MODE=wayback` makes the fetcher request `https://web.archive.org/web/2030id_/<url>` (the latest archived copy, original bytes). Missing copies are reported as fetch errors. This mode is for development and verification only; production collects live. Parsers were written against archived cdep.ro pages from 2024–2025 and live senat.ro pages; fixtures are synthetic.

## Outcome

Later on 2026-10-27 cdep.ro became reachable again. The live site had moved its applications under `/ords/` and redesigned deputy profiles in 2025, so URLs built from the archived copies returned 404; collectors were updated and verified live. Wayback mode remains useful only for pages the archive has under current URLs.

## Consequences

Archived data is sparse and dated (for example, most nominal vote pages of the 2024 legislature are not archived). The first production run must be checked against live cdep.ro pages; a structural change would surface as `ParseError`s in `ingest_log`.
