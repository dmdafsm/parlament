"""Command line: database setup, collection from the official sites, scheduler and web server."""

import datetime as dt

import typer

from parlament import db
from parlament.config import settings
from parlament.fetch import Fetcher
from parlament.ingest import cdep_activity, cdep_agenda, cdep_bills, cdep_members, cdep_votes, senat_members

app = typer.Typer(help="Parlamentul României pe înțelesul tuturor: colectare date și site.", no_args_is_help=True)
ingest_app = typer.Typer(help="Colectează date de pe cdep.ro și senat.ro.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")

CacheOption = typer.Option(False, "--from-raw", help="Refoloseste paginile salvate in data/raw (fara descarcare).")


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


@app.command("init-db")
def init_db() -> None:
    """Creează sau actualizează schema bazei de date."""
    with db.connect() as conn:
        applied = db.migrate(conn)
    typer.echo(f"Migrari aplicate: {', '.join(applied) or 'niciuna (schema la zi)'}")


@ingest_app.command("members")
def ingest_members(
    chamber: str = typer.Option("all", help="cd, senat sau all"),
    legislature: int = typer.Option(None, help="Legislatura (implicit cea curenta)"),
    limit: int = typer.Option(None, help="Doar primii N (pentru teste)"),
    from_raw: bool = CacheOption,
) -> None:
    """Parlamentari: profil, grup, partid, comisii, contoare de activitate."""
    leg = legislature or settings().legislature
    with db.connect() as conn, Fetcher(use_cache=from_raw) as fetcher:
        if chamber in ("cd", "all"):
            typer.echo(f"Deputati: {cdep_members.ingest(conn, fetcher, leg, limit)}")
        if chamber in ("senat", "all"):
            typer.echo(f"Senatori: {senat_members.ingest(conn, fetcher, leg, limit)}")


@ingest_app.command("activity")
def ingest_activity(
    legislature: int = typer.Option(None),
    limit: int = typer.Option(None),
    with_bills: bool = typer.Option(True, help="Descarca si proiectele initiate"),
    from_raw: bool = CacheOption,
) -> None:
    """Deputati: initiative, intrebari, motiuni, luari de cuvant."""
    leg = legislature or settings().legislature
    with db.connect() as conn, Fetcher(use_cache=from_raw) as fetcher:
        count, idps = cdep_activity.ingest(conn, fetcher, leg, limit)
        typer.echo(f"Activitate: {count} deputati, {len(set(idps))} proiecte gasite")
        if with_bills and idps:
            typer.echo(f"Proiecte: {cdep_bills.ingest(conn, fetcher, sorted(set(idps)), refresh_days=30)}")
        cdep_bills.relink(conn)


@ingest_app.command("bills")
def ingest_bills(
    idp: list[str] = typer.Option(None, help="Id-uri cdep.ro (idp) de descarcat"),
    refresh: bool = typer.Option(False, help="Reimprospateaza proiectele deja salvate care inca se dezbat"),
    from_raw: bool = CacheOption,
) -> None:
    """Proiecte legislative: detalii, initiatori, documente, parcurs."""
    with db.connect() as conn, Fetcher(use_cache=from_raw) as fetcher:
        ids = list(idp or [])
        if refresh:
            ids += [
                row["source_id"]
                for row in conn.execute(
                    "SELECT source_id FROM bills WHERE law IS NULL ORDER BY last_event_on DESC NULLS LAST"
                )
            ]
        typer.echo(f"Proiecte: {cdep_bills.ingest(conn, fetcher, ids)}")
        typer.echo(f"Voturi/puncte legate de proiecte: {cdep_bills.relink(conn)}")


@ingest_app.command("votes")
def ingest_votes(
    start: str = typer.Option(None, "--from", help="Data de inceput (AAAA-LL-ZZ)"),
    end: str = typer.Option(None, "--to", help="Data de sfarsit (implicit azi)"),
    days: int = typer.Option(14, help="Ultimele N zile, daca lipseste --from"),
    nominal: bool = typer.Option(True, help="Descarca si votul nominal"),
    latest: bool = typer.Option(False, help="Doar ultima sedinta cu vot electronic"),
    from_raw: bool = CacheOption,
) -> None:
    """Voturile electronice ale Camerei Deputatilor (nominal)."""
    last = _date(end) if end else dt.date.today()
    first = _date(start) if start else last - dt.timedelta(days=days)
    selected = [None] if latest else cdep_votes.sitting_days(first, last)
    with db.connect() as conn, Fetcher(use_cache=from_raw) as fetcher:
        count = cdep_votes.ingest_days(conn, fetcher, selected, nominal)
        typer.echo(f"Voturi: {count} ({'ultima sedinta' if latest else f'{first} - {last}'})")
        cdep_bills.relink(conn)


@ingest_app.command("agenda")
def ingest_agenda(
    date: list[str] = typer.Option(None, help="Zile (AAAA-LL-ZZ); implicit ordinea de zi curenta"),
    from_raw: bool = CacheOption,
) -> None:
    """Ordinea de zi a plenului Camerei Deputatilor (si proiectele de pe ea)."""
    days = [_date(day) for day in date] if date else [None]
    with db.connect() as conn, Fetcher(use_cache=from_raw) as fetcher:
        count, idps = cdep_agenda.ingest(conn, fetcher, days)
        typer.echo(f"Ordini de zi: {count}")
        if idps:
            typer.echo(f"Proiecte: {cdep_bills.ingest(conn, fetcher, sorted(set(idps)), refresh_days=7)}")
        cdep_bills.relink(conn)


@ingest_app.command("photos")
def ingest_photos(refresh: bool = typer.Option(False, help="Descarca din nou toate fotografiile")) -> None:
    """Fotografiile oficiale, redimensionate (128px si 480px)."""
    from parlament.ingest import photos

    with db.connect() as conn, Fetcher() as fetcher:
        typer.echo(f"Fotografii: {photos.ingest(conn, fetcher, refresh)}")


@ingest_app.command("all")
def ingest_all(
    vote_days: int = typer.Option(14, help="Cate zile de voturi in urma"),
    limit: int = typer.Option(None),
) -> None:
    """Toata colectarea, in ordine: parlamentari, activitate, ordinea de zi, voturi."""
    ingest_members(chamber="all", legislature=None, limit=limit, from_raw=False)
    ingest_activity(legislature=None, limit=limit, with_bills=True, from_raw=False)
    ingest_agenda(date=None, from_raw=False)
    ingest_votes(start=None, end=None, days=vote_days, nominal=True, latest=False, from_raw=False)
    ingest_photos(refresh=False)


@app.command()
def relink() -> None:
    """Leaga voturile si punctele de pe ordinea de zi de proiectele salvate."""
    with db.connect() as conn:
        typer.echo(f"Legaturi noi: {cdep_bills.relink(conn)}")


@app.command()
def status() -> None:
    """Ce este in baza de date si ultimele rulari."""
    with db.connect() as conn:
        for table in ("members", "bills", "bill_events", "votes", "vote_records", "questions", "speeches", "agendas"):
            count = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
            typer.echo(f"{table:15} {count}")
        for row in conn.execute("SELECT * FROM ingest_log ORDER BY id DESC LIMIT 10"):
            typer.echo(f"{row['started_at']:%Y-%m-%d %H:%M} {row['command']:30} {row['status']:8} {row['rows']}")


@app.command()
def schedule(once: bool = typer.Option(False, help="O singura rulare, apoi iesire")) -> None:
    """Colectare periodica (in containerul ingest)."""
    from parlament import scheduler

    scheduler.run(once=once)


@app.command()
def export(directory: str = typer.Option(None, help="Director (implicit data/export)")) -> None:
    """Exporta datele deschise (CSV) servite la /date-deschise."""
    from parlament import exports

    with db.connect() as conn:
        for path in exports.write_all(conn, directory):
            typer.echo(str(path))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    reload: bool = typer.Option(False),
) -> None:
    """Porneste site-ul."""
    import uvicorn

    uvicorn.run(
        "parlament.web.app:app", host=host, port=port, reload=reload, proxy_headers=True, forwarded_allow_ips="*"
    )
