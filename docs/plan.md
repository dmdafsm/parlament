# Plan

Public, open-source portal that makes the activity of Romanian MPs (Senate and Chamber of Deputies) easy to follow. UI in Romanian; code and engineering docs in English. Engineering setup mirrors `bvb-research` (uv, ruff, pytest, `scripts/verify.py`, branch guards, ADRs, AGENTS.md, Docker Compose, GitHub Actions). Status as of 2026-10-28.

## Scope from the brief

| Area | Status |
| --- | --- |
| MP list: grouping by parliamentary group, constituency (41 counties, București, Diaspora), chamber | Done |
| Sorting by activity: speeches, bills initiated, questions, motions, attendance/absences, votes against group, group/party changes | Done |
| Profile: photo, affiliation, group/party history, committees, activity, contact and offices, CV | Done |
| Current activity: bills, initiatives, plenary agenda | Done (both chambers) |
| Bill details: summary, full history, documents, votes | Done |
| Learning pages | Done (5 pages) |
| Web app, Docker, engineering setup, Material Design | Done (FastAPI + HTMX + Beer CSS, Compose, CI) |
| Public repository | Done |

## Phases

- **P0 — Repo and sources** (done): scaffold and guardrails from bvb-research, ADRs 0001–0005, source research ([surse-date.md](surse-date.md)). Collectors verified on the live sites (cdep.ro under `/ords/`, 2025 profile layout).
- **P1 — MPs** (done): deputies (cdep.ro) and senators (senat.ro): profile, photo cache, group/party history, roles, committees, counters; list with grouping, filters, sorting; profile page.
- **P2 — Bills and agenda** (done): bill details, initiators, documents, procedure timeline; Chamber agenda; links between bills, votes and agenda items.
- **P3 — Votes and attendance** (done): daily and nominal votes of both chambers, attendance within the mandate, party-line voting, votes against the group, absent list per vote.
- **P4 — Speeches and questions** (done): speeches index per deputy, questions and interpellations, motions; search without diacritics across members, bills, votes and speeches.
- **P5 — Learning, methodology, open data** (done): learning pages, methodology with indicator definitions and last runs, CSV exports, JSON API with OpenAPI docs, RSS feeds.
- **P6 — Extras** (partly done): party-switching page with group flows, ordinances tracker (OUG/OG approval bills, time to law), Constitutional Court mentions, tacit adoptions, declarations linked, RSS alerts per MP/bill. Not done: email alerts, plain-language summaries, historical legislatures.

## Next

1. Speeches: index stenogram text for full-text search.
2. Use the official XML vote export (`evot2015.xml`) instead of HTML where it is complete.
3. Senate activity lists (questions, speeches, motions) through the profile's postback links, like the biography.
4. Email alerts (needs an outbound mail service and consent records), plain-language bill summaries (LLM-generated, labelled, with source links), previous legislatures (2016, 2020) for comparison.
5. Asset declarations from ANI (integritate.eu) with year-over-year comparison, respecting [ADR 0001](engineering/decisions/0001-public-data-and-personal-data.md).

Done since the first release: votes for the whole legislature (both chambers), Senate nominal votes, Senate bills and agenda, CVs of deputies and senators.

## More ideas

"Who represents me" by locality, MP comparison side by side, election results per MP (AEP), committee attendance, budget of MP lump sums, correction requests linked to the source, accessibility audit, English summary pages.
