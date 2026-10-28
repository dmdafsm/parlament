# Data sources

Verified live on 2026-10-27 (cdep.ro was unreachable from the development network earlier that day; parsers were first written against Internet Archive copies, then checked on the live site).

Since 2025 cdep.ro serves its Oracle applications under **`/ords/`** (`https://www.cdep.ro/ords/pls/...`; the old `/pls/...` URLs return 404) and in **UTF-8** (earlier ISO-8859-2). Deputy profiles got a new layout in 2025 (`mp-profile-*2025`, `mp-info-box2025`, counters as text lines); parsers accept both layouts. All paths below are relative to `https://www.cdep.ro/ords`.

| Data | Source (URL pattern) | Method | Notes |
| --- | --- | --- | --- |
| Deputies list | `/pls/parlam/structura2015.de?idl=1` (current) / `?leg=YYYY` | HTML | Constituency shown as `35 / SUCEAVA`; the `cir` link parameter is offset by one, use the shown number. |
| Deputy profile | `/pls/parlam/structura2015.mp?idm=N&cam=2&leg=YYYY` | HTML | Photo, birth date, constituency, validation and end of mandate, party and group history with month precision, leadership roles, committees, activity counters (incl. laws promulgated), constituency offices. 2025 layout shows the party by full name only. |
| Deputy activity lists | same URL with `&pag=2` (bills initiated), `3` (questions/interpellations), `6` (interest declarations, scanned PDF), `11` (motions) | HTML | Opened only when the profile counter is non-zero. |
| Speeches | `/pls/steno/steno2015.lista?idv=N&leg=YYYY` (linked from the profile) | HTML | One row per agenda point spoken on, grouped by sitting. Result pages are followed (`pags` = first row index, at most 30 pages). |
| Votes (Chamber) | `/pls/steno/evot2015.data?dat=YYYYMMDD&cam=2` (day), `evot2015.data` (latest sitting), `evot2015.nominal?idv=N` | HTML | Nominal list includes only deputies present. The daily list may omit the 'not voted' column (stored as unknown). An XML export exists (`evot2015.xml?par1=1&par2=YYYYMMDD`, summary; `par1=2&par2=idv`, nominal) — not used yet. |
| Bills | `/pls/proiecte/upl_pck2015.proiect?idp=N` | HTML | Chamber resolutions (PHCD) live in a separate application, `uph_pck2015.proiect`, with their own ids: not collected as bills. Numbers (BPI, Chamber, Senate), type, decisional chamber, urgency, status, law, initiators (linked to profiles, both chambers), documents, full procedure. |
| Plenary agenda | `/pls/caseta/eCaseta2015.OrdineZi` (current), `?dat=YYYYMMDD` | HTML | Items link to bills (`upl_pck2015`, `idp`) or resolutions (`uph_pck2015`). |
| Senators | `senat.ro/FisaSenatori.aspx`, `FisaSenator.aspx?ParlamentarID={GUID}` | HTML, UTF-8 | List repeats each senator twice (dedupe). Profile: current party and group only (no history), committees with role and start date, counters (bills, laws, questions, interpellations, speeches, motions, vote sessions attended / total). |
| Senate nominal votes | `senat.ro/Voturiplen.aspx` | ASP.NET postbacks | **Not collected yet.** Needs replaying the page's own form posts (calendar → day → vote); allowed in principle (no protection is bypassed) but not implemented. |
| Asset/interest declarations | profile sub-pages, scanned PDF/GIF | Links only | No OCR. ANI (integritate.eu) is a possible future source. |

## Legal basis and attribution

Official texts of a legislative and administrative nature are not protected by copyright (Legea nr. 8/1996, art. 9). The site attributes the Chamber of Deputies and the Senate and links every record to its official page. See [ADR 0001](engineering/decisions/0001-public-data-and-personal-data.md) for personal data.

## Access rules

One process per site, a fixed delay between requests (`PARLAMENT_REQUEST_DELAY`, default 3 s), an identifying User-Agent, raw cache to avoid re-downloading, HTTP 429 stops the run. `PARLAMENT_FETCH_MODE=wayback` reads archived copies from the Internet Archive; it is for development only ([ADR 0005](engineering/decisions/0005-archived-copies-for-development.md)). `PARLAMENT_FETCH_MODE=offline` with `--from-raw` re-parses the raw cache and never calls a site; pages that are not cached are reported as missing.
