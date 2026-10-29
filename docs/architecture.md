# Architecture

```
cdep.ro, senat.ro ──► parlament ingest … (httpx, selectolax) ──► PostgreSQL ──► FastAPI + Jinja2 + HTMX ──► browser
        ▲                     │ raw HTML cache: data/raw/<site>/                  │            (Beer CSS, local assets)
        │                     ▼                                                    ├──► /api/v1 (JSON), /feed (RSS)
   polite, sequential     parlament schedule (ingest container)                    └──► /date-deschise (CSV, weekly)
```

- **One package** `src/parlament`: `ingest/` (one module per source and page family), `analytics.py` (all indicators), `web/` (routes, templates, static), `feeds.py`, `exports.py`, `summaries.py`, `cli.py`, `scheduler.py`, `db.py` + `migrations/`.
- **Data flow is one-way**: collectors write; the website, API, RSS and CSV only read. A page request never calls cdep.ro or senat.ro.
- **Parsing is pure**: `parse_*(html) -> data` functions are separate from fetching and storing, tested against synthetic fixtures.
- **Raw cache**: every downloaded page is saved under `data/raw/<site>/<sha256 of url>.html`; `--from-raw` re-parses without downloading.
- **Scheduler**: a plain loop in the ingest container (`parlament schedule`): weekday evenings votes, agenda and bills in debate; Sundays profiles, activity lists, photos and the CSV export.

## Table ownership

| Module | Tables written |
| --- | --- |
| `ingest/cdep_members.py`, `ingest/senat_members.py` | `members` (incl. `cv`), `parl_groups`, `group_memberships`, `party_memberships`, `group_roles`, `committees`, `committee_memberships`, `member_stats` |
| `ingest/cdep_activity.py`, `ingest/senat_activity.py` (through `cdep_activity.store`) | `questions`, `speeches`, `motions`, `motion_signatures` |
| `ingest/cdep_steno.py`, `ingest/senat_steno.py` (through `cdep_steno.store`) | `stenograms`, `speech_texts` |
| `ingest/cdep_bills.py` | `bills`, `bill_initiators`, `bill_events`, `bill_documents`; links `votes.bill_id`, `agenda_items.bill_id` (`relink`) |
| `ingest/cdep_votes.py`, `ingest/senat_votes.py` | `votes`, `vote_records` (rows of their own chamber) |
| `ingest/cdep_agenda.py`, `ingest/senat_agenda.py` | `agendas`, `agenda_items` (rows of their own chamber) |
| `ingest/senat_bills.py` | Senate rows of `bills` and their children (through `cdep_bills.store_bill`); links Senate `votes.bill_id`, `agenda_items.bill_id` and Senate bill initiators (`link`) |
| `ingest/bill_texts.py` | `bill_texts` |
| `summaries.py` (run by hand with a local model, [ADR 0006](engineering/decisions/0006-local-llm-summaries.md)) | `bill_summaries` |
| `ingest/photos.py` | files under `data/photos/` |
| `analytics.py` (`refresh`, after each collection, [ADR 0007](engineering/decisions/0007-stored-member-indicators.md)) | materialized view `member_overview` |
| `db.py` | `schema_migrations`, `ingest_log` |

## Identifiers

- Members: `cd-<legislature>-<cdep idm>` and `senat-<legislature>-<senat.ro GUID>`. Bill initiators and nominal votes keep the cdep.ro reference as published (`member_ref`), which may point to a previous legislature. MPs of earlier legislatures (`ingest members --legislature 2020`) are stored the same way but used only to list a current MP's other mandates; lists, search and medians use the current legislature.
- Bills `cd-<idp>`, votes `cd-<idv>`, agendas `cd-<oid>`, questions `cd-<idi>`.
- Senate: bills `senat-<cod>`, votes `senat-<AppID GUID>`, agendas `senat-<YYYY-MM-DD>`. A bill in both chambers is matched by its Senate number (`bills.senate_key`, e.g. `L511/2026`); the site shows the cdep.ro page with the Senate procedure and votes attached.

## Indicators

Defined in `analytics.py` (`MEMBER_OVERVIEW`, stored as `member_overview` when data is collected) and explained on `/metodologie`: vote attendance (deputies: per nominal vote within the mandate; senators: sessions as published), party-line voting (strict majority of the group present), activity counters as published, group/party changes.

## Search

PostgreSQL full text with the `simple` configuration on unaccented text, queried with prefixes (`analytics.ts_query`), because people search without diacritics and the Romanian stemmer does not handle unaccented input.
