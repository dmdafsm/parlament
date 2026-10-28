"""Plenary agenda (ordinea de zi) of the Senate from senat.ro ProgramLucruZi.aspx, one page per sitting day."""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.senat_bills import senate_key
from parlament.ingest.senat_members import BASE
from parlament.parsing import ParseError, html, node_text, parse_long_date, query_param

SOURCE = "senat.ro"
# The plenary's id in the Senate's work programme (committees have their own).
PLENARY = "D217F4D2-2F5E-4F1B-BCD3-F520A1654A77"


def agenda_url(day: dt.date) -> str:
    return f"{BASE}/ProgramLucruZi.aspx?Zi={day:%Y-%m-%d}&ComisieID={PLENARY}"


def parse_agenda(page: str, day: dt.date) -> dict | None:
    """The day's agenda, or None when the Senate published none for that day."""
    tree = html(page)
    heading = next((node_text(n) for n in tree.css("h1, h2, h3, h4") if "Ordinea de zi" in node_text(n)), None)
    items = []
    for table in tree.css("table"):
        if [node_text(cell) for cell in table.css("th")][:2] != ["#", "P.L."]:
            continue
        for row in table.css("tr"):
            cells = [cell for cell in row.iter() if cell.tag == "td"]
            if len(cells) != 4:
                continue
            link = cells[1].css_first("a")
            first_line = re.split(r"<br\s*/?>", cells[2].html or "", maxsplit=1)[0]
            text = node_text(html(f"<p>{first_line}</p>").css_first("p")) or node_text(cells[2])
            if not text:
                continue
            outcome = node_text(cells[3])
            items.append(
                {
                    "position": node_text(cells[0]) or None,
                    "bill_ref": senate_key(node_text(cells[1])),
                    "bill_cod": query_param(link.attributes.get("href", ""), "cod") if link else None,
                    "text": f"{text} — {outcome}" if outcome else text,
                }
            )
    if heading is None and not items:
        return None
    if heading is None:
        raise ParseError("senat agenda: items without a heading")
    return {"title": heading, "day": parse_long_date(heading) or day, "items": items}


def store_agenda(conn: psycopg.Connection, agenda: dict, url: str) -> str:
    aid = f"senat-{agenda['day']:%Y-%m-%d}"
    conn.execute(
        """INSERT INTO agendas (id, chamber, title, first_day, url) VALUES (%s, 'senat', %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, first_day = EXCLUDED.first_day""",
        (aid, agenda["title"], agenda["day"], url),
    )
    conn.execute("DELETE FROM agenda_items WHERE agenda_id = %s", (aid,))
    for seq, item in enumerate(agenda["items"]):
        bill_id = f"senat-{item['bill_cod']}" if item["bill_cod"] else None
        if bill_id and not conn.execute("SELECT 1 FROM bills WHERE id = %s", (bill_id,)).fetchone():
            bill_id = None
        conn.execute(
            "INSERT INTO agenda_items VALUES (%s, %s, %s, %s, %s, %s)",
            (aid, seq, item["position"], item["bill_ref"], bill_id, item["text"]),
        )
    return aid


def ingest(conn: psycopg.Connection, fetcher: Fetcher, days: list[dt.date]) -> tuple[int, list[str]]:
    """Store the agenda of each day that has one. Returns (agendas stored, Senate bill codes found)."""
    log = db.log_start(conn, SOURCE, "agenda senat")
    count, codes, errors = 0, [], []
    today = dt.date.today()
    for day in sorted(set(days)):
        url = agenda_url(day)
        try:
            # Agendas of recent and coming days still change; older ones are final.
            agenda = parse_agenda(fetcher.get("senat", url, fresh=(day - today).days > -7), day)
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        if agenda is None:
            continue
        with conn.transaction():
            store_agenda(conn, agenda, url)
        codes.extend(item["bill_cod"] for item in agenda["items"] if item["bill_cod"])
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count, codes
