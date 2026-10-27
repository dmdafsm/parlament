# ADR 0001: publishing parliamentary data and personal data

Status: accepted. Date: 2026-10-27. Related tasks: P0.

## Context

The project republishes data from cdep.ro and senat.ro on a public website and as open data. Unlike market data, official parliamentary records are published by public institutions to inform citizens. The records concern identified people (MPs), so GDPR applies.

## Decision

- Publish the data and link every record to its official page. Official texts of a legislative, administrative or political nature are excluded from copyright (Legea nr. 8/1996, art. 9); lists, votes and procedure records are factual public information.
- Personal data is limited to what the chambers publish about the **public role**: name, photo, birth date, constituency, party and group, committees, votes, speeches, initiatives, questions, official contact and constituency office addresses. The legal basis is the public interest in the transparency of Parliament (GDPR art. 6(1)(e)/(f) and art. 85, journalism and freedom of information).
- Asset and interest declarations are linked, not transcribed: they contain third-party data (relatives, addresses) that the chambers redact inconsistently.
- No data about visitors: no analytics, cookies or third-party requests (assets are served locally).
- Factual errors are corrected by re-collecting from the source; a correction request that the source does not support is redirected to the chamber.

## Alternatives and consequences

Mirroring declarations' content (rejected for now: personal data of third parties and OCR errors). The site must keep source links and attribution; tests use synthetic fixtures so the repository does not hold copies of real pages.

## Verification

Legal reading by the maintainer; to be reviewed by a lawyer before a public launch with wide reach.
