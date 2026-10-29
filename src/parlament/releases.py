"""Weekly data release on GitHub: the open-data CSVs in one archive, with a README and a checksum (ADR 0008)."""

import csv
import datetime as dt
import hashlib
import zipfile
from pathlib import Path

import httpx
import psycopg

from parlament import exports
from parlament.config import settings

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
MONTHS = ("ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie",
          "octombrie", "noiembrie", "decembrie")  # fmt: skip

ABOUT = {
    "parlamentari": "Deputații și senatorii (legislatura curentă și mandatele anterioare ale acelorași persoane)",
    "grupuri": "Grupurile parlamentare",
    "istoric_grupuri": "Apartenența fiecărui parlamentar la grupuri, cu perioade",
    "istoric_partide": "Apartenența fiecărui parlamentar la partide, cu perioade",
    "comisii": "Membrii comisiilor permanente și funcțiile lor",
    "statistici": "Contoarele de activitate publicate pe profilurile oficiale",
    "proiecte": "Proiecte de lege și propuneri legislative, cu stadiul",
    "proiecte_initiatori": "Inițiatorii fiecărui proiect",
    "proiecte_parcurs": "Etapele procedurii fiecărui proiect",
    "voturi": "Voturile din plen (rezultat și totaluri)",
    "voturi_nominale": "Votul fiecărui parlamentar la fiecare vot nominal",
    "intrebari": "Întrebările și interpelările adresate Guvernului",
    "luari_de_cuvant": "Luările de cuvânt în plen",
}

SOURCE = (
    "Sursa: paginile oficiale ale Camerei Deputaților (cdep.ro) și Senatului României (senat.ro); fiecare rând are "
    "o coloană `url` sau un id care trimite la pagina oficială. Textele oficiale nu fac obiectul dreptului de autor "
    "(Legea nr. 8/1996, art. 9). Te rugăm să menționezi sursa: Camera Deputaților / Senatul României, prin "
    "parlament.romdata.ro."
)
NOTES = [
    "Fișierele sunt CSV în UTF-8, separate prin virgulă, cu antet pe primul rând. Datele sunt în format ISO.",
    "O valoare goală înseamnă că sursa nu o publică sau nu a fost preluată; nu înseamnă zero.",
    "În `voturi_nominale.csv`, `choice` este `yes`, `no`, `abstain` sau `present_not_voting` (prezent, dar nu a "
    "votat). Un parlamentar care lipsește din lista unui vot nu figurează ca prezent; asta nu înseamnă că a votat "
    "împotrivă.",
    "Un proiect dezbătut de ambele camere apare o dată pentru fiecare cameră; `senate_key` le leagă.",
    "Metodologia indicatorilor: https://parlament.romdata.ro/metodologie",
]


def date_ro(day: dt.date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def number(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def inventory(directory: Path) -> list[tuple[Path, int, list[str]]]:
    """Each exported table: its file, number of rows (fields may span lines) and columns."""
    files = []
    for name in exports.TABLES:
        path = directory / f"{name}.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            columns = next(reader)
            files.append((path, sum(1 for _ in reader), columns))
    return files


def coverage(conn: psycopg.Connection, day: dt.date) -> str:
    row = conn.execute("SELECT min(voted_at)::date AS first, max(voted_at)::date AS last FROM votes").fetchone()
    text = f"Datele colectate de [parlament.romdata.ro](https://parlament.romdata.ro) la {date_ro(day)}"
    if row["first"]:
        text += f"; voturile din plen sunt de la {date_ro(row['first'])} până la {date_ro(row['last'])}"
    return text + "."


def readme(intro: str, files: list[tuple[Path, int, list[str]]]) -> str:
    lines = ["# Date deschise: Parlamentul României", "", intro, "", SOURCE, "", "## Fișiere", ""]
    lines += ["| Fișier | Rânduri | Conținut |", "|---|---:|---|"]
    lines += [f"| `{path.name}` | {number(rows)} | {ABOUT[path.stem]} |" for path, rows, _ in files]
    lines += ["", "## Coloane", ""]
    lines += [f"- `{path.name}`: " + ", ".join(f"`{c}`" for c in columns) for path, _, columns in files]
    lines += ["", "## De știut", ""] + [f"- {note}" for note in NOTES]
    return "\n".join(lines) + "\n"


def notes(intro: str, files: list[tuple[Path, int, list[str]]]) -> str:
    """The release description: what the archive holds, in short."""
    lines = [intro, "", "| Fișier | Rânduri |", "|---|---:|"]
    lines += [f"| `{path.name}` | {number(rows)} |" for path, rows, _ in files]
    lines += [
        "",
        "Arhiva conține și un `README.md` cu coloanele fiecărui fișier și ce trebuie știut despre valori "
        "(o valoare goală nu înseamnă zero; absența de la un vot nu este vot împotrivă).",
        "",
        SOURCE,
    ]
    return "\n".join(lines) + "\n"


def build(conn: psycopg.Connection, day: dt.date, source: Path, target: Path) -> tuple[list[Path], str]:
    """The archive of the exports in `source` and its checksum, written to `target`; and the release notes."""
    files = inventory(source)
    intro = coverage(conn, day)
    name = f"parlament-date-{day.isoformat()}"
    target.mkdir(parents=True, exist_ok=True)
    archive = target / f"{name}.zip"
    tmp = archive.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        zipped.writestr(f"{name}/README.md", readme(intro, files))
        for path, _, _ in files:
            zipped.write(path, f"{name}/{path.name}")
    tmp.replace(archive)
    sums = target / "SHA256SUMS"
    sums.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    return [archive, sums], notes(intro, files)


def publish(
    paths: list[Path], tag: str, title: str, body: str, repo: str, token: str, client: httpx.Client | None = None
) -> str | None:
    """Create the release `tag` on GitHub with `paths` attached; None if it exists (already published).

    A release whose files could not all be uploaded is deleted, so a later run can publish it whole.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with client or httpx.Client(timeout=300) as http:
        if http.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=headers).status_code == 200:
            return None
        created = http.post(
            f"{API}/repos/{repo}/releases",
            headers=headers,
            json={"tag_name": tag, "target_commitish": "main", "name": title, "body": body},
        )
        created.raise_for_status()
        release = created.json()
        try:
            for path in paths:
                kind = "application/zip" if path.suffix == ".zip" else "text/plain"
                http.post(
                    f"{UPLOADS}/repos/{repo}/releases/{release['id']}/assets",
                    params={"name": path.name},
                    headers={**headers, "Content-Type": kind},
                    content=path.read_bytes(),
                ).raise_for_status()
        except httpx.HTTPError:
            http.delete(f"{API}/repos/{repo}/releases/{release['id']}", headers=headers)
            raise
        return release["html_url"]


def release(conn: psycopg.Connection, day: dt.date, client: httpx.Client | None = None) -> str | None:
    """Archive the current exports and publish them as `data-<day>`; needs PARLAMENT_GITHUB_TOKEN."""
    conf = settings()
    paths, body = build(conn, day, exports.export_dir(), conf.data_dir / "release")
    title = f"Date deschise – {date_ro(day)}"
    return publish(paths, f"data-{day.isoformat()}", title, body, conf.github_repo, conf.github_token, client)
