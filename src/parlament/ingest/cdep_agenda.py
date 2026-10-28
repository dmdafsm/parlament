"""Plenary agenda (ordinea de zi) of the Chamber of Deputies from cdep.ro."""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_bills import find_bill_ref
from parlament.ingest.cdep_members import SITE, absolute
from parlament.parsing import MONTHS, ParseError, clean, html, node_text, parse_dotted_date, query_param

SOURCE = "cdep.ro"


def agenda_url(day: dt.date | None = None) -> str:
    suffix = f"?dat={day:%Y%m%d}" if day else ""
    return f"{SITE}/pls/caseta/eCaseta2015.OrdineZi{suffix}"


def first_day(title: str) -> dt.date | None:
    """'... din zilele de 17 si 19 mai 2021' -> 2021-05-17; '... din 25 iunie 2024' -> 2024-06-25."""
    match = re.search(
        r"din\s+(?:ziua|zilele)?\s*(?:de\s+)?(\d{1,2})\D.*?([a-zăâî]{3})[a-zăâî]*\s+(\d{4})", title.lower()
    )
    if not match or match.group(2) not in MONTHS:
        return None
    return dt.date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))


def parse_agenda(page: str) -> dict:
    tree = html(page)
    heading = tree.css_first("div.boxTitle h1")
    if heading is None:
        raise ParseError("cdep agenda: missing heading")
    title = node_text(heading)
    oid = None
    for link in tree.css("div.page-actions a, a"):
        oid = query_param(link.attributes.get("href", ""), "oid")
        if oid:
            break
    approved = next((node_text(div) for div in tree.css("div") if node_text(div).startswith("Aprobat")), "")
    pdf = next((a for a in tree.css("a") if "p_file=" in a.attributes.get("href", "")), None)
    items = []
    for row in tree.css("div.grup-parlamentar-list table tbody tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) != 4:
            continue
        link = cells[1].css_first("a")
        href = link.attributes.get("href", "") if link else ""
        text = node_text(cells[2])
        if not text:
            continue
        items.append(
            {
                "position": clean(node_text(cells[0])).rstrip(".") or None,
                "bill_ref": node_text(link) if link else find_bill_ref(text),
                # Laws are in upl_pck2015; chamber resolutions (PHCD) in uph_pck2015 have their own ids.
                "bill_idp": query_param(href, "idp") if link and "upl_pck2015" in href else None,
                "text": text,
            }
        )
    if oid is None:
        raise ParseError("cdep agenda: no agenda id")
    return {
        "oid": oid,
        "title": title,
        "approved_on": parse_dotted_date(approved),
        "first_day": first_day(title),
        "pdf_url": absolute(pdf.attributes["href"]) if pdf else None,
        "items": [item for item in items if item["position"] != "-" or item["bill_ref"]] or items,
    }


def store_agenda(conn: psycopg.Connection, agenda: dict, url: str) -> str:
    aid = f"cd-{agenda['oid']}"
    conn.execute(
        """INSERT INTO agendas (id, chamber, title, approved_on, first_day, pdf_url, url) VALUES (%s, 'cd', %s, %s,
               %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, approved_on = EXCLUDED.approved_on,
               first_day = EXCLUDED.first_day, pdf_url = EXCLUDED.pdf_url""",
        (aid, agenda["title"], agenda["approved_on"], agenda["first_day"], agenda["pdf_url"], url),
    )
    conn.execute("DELETE FROM agenda_items WHERE agenda_id = %s", (aid,))
    for seq, item in enumerate(agenda["items"]):
        bill_id = f"cd-{item['bill_idp']}" if item["bill_idp"] else None
        if bill_id and not conn.execute("SELECT 1 FROM bills WHERE id = %s", (bill_id,)).fetchone():
            bill_id = None
        conn.execute(
            "INSERT INTO agenda_items VALUES (%s, %s, %s, %s, %s, %s)",
            (aid, seq, item["position"], item["bill_ref"], bill_id, item["text"]),
        )
    return aid


def ingest(conn: psycopg.Connection, fetcher: Fetcher, days: list[dt.date | None]) -> tuple[int, list[str]]:
    """Store the agenda for each day (None = the current agenda). Returns (count, bill idps found)."""
    log = db.log_start(conn, SOURCE, "agenda")
    count, idps, errors = 0, [], []
    for day in days:
        url = agenda_url(day)
        try:
            agenda = parse_agenda(fetcher.get("cdep", url))
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        with conn.transaction():
            store_agenda(conn, agenda, url)
        idps.extend(item["bill_idp"] for item in agenda["items"] if item["bill_idp"])
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count, idps
