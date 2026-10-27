# Data sources

Verified 2026-10-27. Page structures were checked on live pages (senat.ro) and on archived copies in the Internet Archive (cdep.ro, which refused connections from the development network that day). Re-check cdep.ro live on the first production run.

| Data | Source (URL pattern) | Method | Notes |
| --- | --- | --- | --- |
| Deputies list | `cdep.ro/pls/parlam/structura2015.de?idl=1` (current) / `?leg=YYYY` | HTML, ISO-8859-2 | Constituency shown as `35 / SUCEAVA`; the `cir` link parameter is offset by one, use the shown number. |
| Deputy profile | `structura2015.mp?idm=N&cam=2&leg=YYYY` | HTML | Photo, birth date, constituency, validation and end of mandate, party and group history with month precision, leadership roles, committees, activity counters, constituency offices. |
| Deputy activity lists | same URL with `&pag=2` (bills initiated), `3` (questions/interpellations), `6` (interest declarations, scanned PDF), `11` (motions) | HTML | Opened only when the profile counter is non-zero. |
| Speeches | `steno/steno2015.lista?idv=N&leg=YYYY` (linked from the profile) | HTML | One row per agenda point spoken on, grouped by sitting. Result pages are followed (`pags` = first row index, at most 30 pages). |
| Votes (Chamber) | `steno/evot2015.data?dat=YYYYMMDD&cam=2` (day), `evot2015.data` (latest sitting), `evot2015.nominal?idv=N` | HTML | Nominal list includes only deputies present. An XML export exists (`evot2015.xml?par1=1&par2=YYYYMMDD`, summary; `par1=2&par2=idv`, nominal) — not used yet. |
| Bills | `proiecte/upl_pck2015.proiect?idp=N` | HTML | Numbers (BPI, Chamber, Senate), type, decisional chamber, urgency, status, law, initiators (linked to profiles, both chambers), documents, full procedure. |
| Plenary agenda | `caseta/eCaseta2015.OrdineZi` (current), `?dat=YYYYMMDD` | HTML | Items link to bills (`idp`). |
| Senators | `senat.ro/FisaSenatori.aspx`, `FisaSenator.aspx?ParlamentarID={GUID}` | HTML, UTF-8 | List repeats each senator twice (dedupe). Profile: current party and group only (no history), committees with role and start date, counters (bills, laws, questions, interpellations, speeches, motions, vote sessions attended / total). |
| Senate nominal votes | `senat.ro/Voturiplen.aspx` | ASP.NET postbacks | **Not collected yet.** Needs replaying the page's own form posts (calendar → day → vote); allowed in principle (no protection is bypassed) but not implemented. |
| Asset/interest declarations | profile sub-pages, scanned PDF/GIF | Links only | No OCR. ANI (integritate.eu) is a possible future source. |

## Legal basis and attribution

Official texts of a legislative and administrative nature are not protected by copyright (Legea nr. 8/1996, art. 9). The site attributes the Chamber of Deputies and the Senate and links every record to its official page. See [ADR 0001](engineering/decisions/0001-public-data-and-personal-data.md) for personal data.

## Access rules

One process per site, a fixed delay between requests (`PARLAMENT_REQUEST_DELAY`, default 1.5 s), an identifying User-Agent, raw cache to avoid re-downloading, HTTP 429 stops the run. `PARLAMENT_FETCH_MODE=wayback` reads archived copies from the Internet Archive; it is for development only ([ADR 0005](engineering/decisions/0005-archived-copies-for-development.md)).
