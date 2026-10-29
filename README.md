# Parlamentul pe înțelesul tuturor

Site public și date deschise despre activitatea Parlamentului României: cine sunt deputații și senatorii, ce legi propun, cum votează, cât de des sunt prezenți, cine și-a schimbat partidul și pe unde trece fiecare lege. Datele sunt preluate automat de pe [cdep.ro](https://www.cdep.ro) și [senat.ro](https://www.senat.ro); fiecare pagină trimite la sursa oficială.

> Proiect independent, fără legătură cu Parlamentul României. Cod sub licența [MIT](LICENSE).

## Ce găsești pe site

| Pagină | Conținut |
| --- | --- |
| `/parlamentari` | Lista deputaților și senatorilor, grupată după grup parlamentar, circumscripție (județ / Diaspora) sau cameră; sortare după prezență, absențe, luări de cuvânt, inițiative, întrebări, moțiuni, vot diferit de grup, schimbări de partid |
| `/parlamentar/{id}` | Fotografie, afiliere, istoric de grupuri și partide, comisii, prezență și vot față de grup (cu mediana camerei), voturi recente, inițiative, luări de cuvânt, întrebări, moțiuni, declarații, birou parlamentar, contact, RSS |
| `/legi`, `/lege/{id}` | Proiecte și propuneri legislative: stadiu, inițiatori, documente, tot parcursul, voturile și ordinea de zi pe care au apărut |
| `/voturi`, `/vot/{id}` | Voturile electronice, pe grupuri și nominal, inclusiv cine nu a fost prezent |
| `/ordinea-de-zi` | Ordinea de zi a plenului, legată de proiecte |
| `/traseism` | Schimbările de grup și partid din legislatură, grupurile parlamentare comparate |
| `/ordonante` | Ordonanțele Guvernului aprobate/respinse prin lege, sesizări la CCR, adoptări tacite |
| `/invata` | Ce face Parlamentul, ce fac deputații și senatorii, cum se face o lege, ordonanțele, glosar |
| `/cauta` | Căutare fără diacritice în parlamentari, proiecte, voturi și luări de cuvânt |
| `/date-deschise`, `/api/docs`, `/feed/…` | CSV, API JSON, fluxuri RSS pentru un parlamentar, o lege, proiecte noi, voturi noi |
| `/metodologie` | Cum calculăm indicatorii, limitările și ultimele colectări |

## Pornire rapidă (Docker)

```bash
cp .env.example .env            # schimbă parola
docker compose up -d --build
docker compose run --rm ingest parlament init-db
docker compose run --rm ingest parlament ingest all --vote-days 30
```

Site-ul: <http://127.0.0.1:8000>. Containerul `ingest` actualizează datele zilnic (voturi, ordinea de zi, proiecte în dezbatere) și săptămânal (profiluri, activitate, fotografii, export CSV și, cu `PARLAMENT_GITHUB_TOKEN`, un [release de date](https://github.com/dmdafsm/parlament/releases) pe GitHub). Pentru producție pune un proxy HTTPS în față ([deploy/Caddyfile](deploy/Caddyfile)).

## Dezvoltare

Python 3.12 cu [uv](https://docs.astral.sh/uv/), PostgreSQL 18.

```bash
uv sync
docker compose up -d db
uv run parlament init-db
uv run parlament ingest members            # deputați (cdep.ro) și senatori (senat.ro)
uv run parlament ingest activity           # inițiative, întrebări, moțiuni, luări de cuvânt + proiectele inițiate
uv run parlament ingest agenda             # ordinea de zi curentă + proiectele de pe ea
uv run parlament ingest votes --days 30    # voturi nominale (Camera Deputaților)
uv run parlament ingest photos             # fotografii redimensionate
uv run parlament export                    # CSV pentru /date-deschise
uv run parlament release-data              # arhiva datelor; cu token, release pe GitHub
uv run parlament serve --reload
python3 scripts/verify.py                  # format, lint, teste
```

- `--from-raw` refolosește paginile salvate în `data/raw/` (fără descărcare), util după o corectură de parser.
- `PARLAMENT_FETCH_MODE=wayback` citește copii arhivate de Internet Archive, doar pentru dezvoltare când un site nu e accesibil ([ADR 0005](docs/engineering/decisions/0005-archived-copies-for-development.md)).
- Cererile către site-urile oficiale sunt secvențiale, cu pauză între ele (`PARLAMENT_REQUEST_DELAY`).

## Documentație

- [Arhitectura](docs/architecture.md), [sursele de date](docs/surse-date.md)
- [AGENTS.md](AGENTS.md) și [CONTRIBUTING.md](CONTRIBUTING.md) pentru contribuții, [SECURITY.md](SECURITY.md) pentru vulnerabilități
- Decizii: [date publice și date personale](docs/engineering/decisions/0001-public-data-and-personal-data.md), [PostgreSQL](docs/engineering/decisions/0002-postgresql.md), [stack web](docs/engineering/decisions/0003-web-stack.md), [Docker Compose](docs/engineering/decisions/0004-docker-compose.md)

## Limitări cunoscute

- Votul nominal al Senatului nu este încă preluat (senat.ro îl publică prin formulare ASP.NET); pentru senatori afișăm prezența pe ședințe publicată pe profil.
- senat.ro nu publică istoricul de partid/grup al senatorilor.
- Declarațiile de avere și interese sunt scanate: le legăm, nu le extragem.
- Luările de cuvânt sunt indexate după tema punctului din sumar, nu după textul integral al stenogramei.
