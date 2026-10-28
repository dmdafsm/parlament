"""Bills from cdep.ro's legislative tracker (upl_pck2015.proiect): details, initiators, documents, procedure."""

import datetime as dt
import json
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_members import SITE, absolute, member_ref_from_url
from parlament.parsing import ParseError, clean, fold, html, node_text, parse_dotted_date, query_param

SOURCE = "cdep.ro"


def bill_url(idp: str) -> str:
    return f"{SITE}/pls/proiecte/upl_pck2015.proiect?idp={idp}"


def bill_key(reference: str) -> str | None:
    """Registry number key for matching: 'PL-x nr. 164/2024', 'PL 164/2024', 'Pl-x164 /2024' -> 'pl:164/2024'."""
    match = re.search(r"\b(P\s*[LH]|BP|B\s*P)[\w\s.-]*?(\d+)\s*/\s*(\d{4})", reference or "", re.IGNORECASE)
    if not match:
        return None
    family = re.sub(r"\s", "", match.group(1)).lower()
    return f"{family}:{int(match.group(2))}/{match.group(3)}"


def find_bill_ref(text: str) -> str | None:
    match = re.search(r"\b(P[LH][\s-]*x?|PH\s*CD|BP)\s*(?:nr\.\s*)?\d+\s*/\s*\d{4}", text or "", re.IGNORECASE)
    return clean(match.group(0)) if match else None


# The approved/rejected ordinance follows "aprobarea"/"respingerea"; later mentions are ordinances it amends.
# Titles on cdep.ro sometimes spell "urgenţã" with ã.
ORDINANCE = re.compile(
    r"\b(?:aprobarea|respingerea)\s+Ordonan[țţ]ei(?P<urgent>\s+de\s+urgen[țţ][ăaã])?(?:\s+a)?\s+Guvernului"
    r"\s+(?:nr\.?\s*)?(?P<nr>\d+)\s*/\s*(?P<year>\d{4})",
    re.IGNORECASE,
)


def ordinance_of(title: str) -> str | None:
    """Bills that approve or reject a Government ordinance name it in the title."""
    match = ORDINANCE.search(title or "")
    if not match:
        return None
    return f"{'OUG' if match.group('urgent') else 'OG'} {match.group('nr')}/{match.group('year')}"


def parse_bill(page: str) -> dict:
    tree = html(page)
    heading = tree.css_first("div.boxTitle h1")
    details = tree.css_first("div.detalii-initiativa")
    if heading is None or details is None:
        raise ParseError("cdep bill: missing heading or details")
    number = re.sub(r"\s*nr\.\s*", " ", node_text(heading))
    title = node_text(details.css_first("h4"))
    bill = {
        "number": number,
        "title": title,
        "initiators": [],
        "documents": [],
        "events": [],
        "ordinance": ordinance_of(title),
    }
    for row in details.css("tr"):
        cells = row.css("td")
        if len(cells) < 2 or "fff0d8" not in (cells[0].attributes.get("bgcolor") or ""):
            continue
        label = node_text(cells[0]).lstrip("- ").rstrip(":").strip().lower()
        value = cells[1]
        text = node_text(value)
        if label == "b.p.i.":
            bill["bpi_number"] = clean(value.text(separator=", "))
        elif label.startswith("camera deputa"):
            bill["cd_number"] = text
            bill["registered_on"] = parse_dotted_date(text)
        elif label == "senat":
            link = value.css_first("a")
            bill["senate_number"] = text or None
            bill["senate_url"] = link.attributes.get("href") if link else None
        elif label.startswith("procedura legislativa"):
            bill["procedure"] = text
        elif label.startswith("camera decizionala"):
            bill["decisional_chamber"] = text
        elif label.startswith("tip initiativa"):
            bill["kind"] = clean(value.text(separator=" ").split("\n")[0]) if value.text() else text
            bill["kind"] = re.split(r"\s+pentru\s+|\s+privind\s+", bill["kind"])[0]
        elif label == "caracter":
            bill["character"] = text
        elif label.startswith("procedura de urgenta"):
            bill["urgent"] = text.lower().startswith("da")
        elif label == "stadiu":
            link = value.css_first("a")
            bill["status"] = text
            if link is not None and re.match(r"Lege\s+\d+", node_text(link)):
                bill["law"] = node_text(link)
                bill["law_url"] = absolute(link.attributes["href"])
        elif label.startswith("initiator"):
            bill["initiator_summary"] = re.split(r",?\s*din care", text)[0]
            for inner in value.css("tr"):
                parts = inner.css("td")
                if len(parts) < 2:
                    continue
                group_label = node_text(parts[0]).rstrip(":")
                for link in parts[1].css("a"):
                    bill["initiators"].append(
                        {
                            "name": node_text(link),
                            "label": group_label,
                            "member_ref": member_ref_from_url(link.attributes.get("href", "")),
                        }
                    )
            if not bill["initiators"]:
                bill["initiators"].append({"name": bill["initiator_summary"], "label": None, "member_ref": None})
        elif label.startswith("consulta"):
            for inner in value.css("tr"):
                link = inner.css_first("a")
                cells_inner = inner.css("td")
                if link is not None and len(cells_inner) >= 2:
                    bill["documents"].append(
                        {"title": node_text(cells_inner[-1]), "url": absolute(link.attributes["href"])}
                    )
    bill["events"] = parse_events(page)
    dates = [event["date"] for event in bill["events"] if event["date"]]
    bill["last_event_on"] = max(dates) if dates else bill.get("registered_on")
    return bill


def parse_events(page: str) -> list[dict]:
    """The procedure table: a date cell (blank = same date as above), the action, documents and notes."""
    marker = page.find("Derularea procedurii legislative")
    if marker < 0:
        return []
    table = html(page[marker:]).css_first("table")
    if table is None:
        return []
    events, current_date, chamber = [], None, "CD"
    for row in table.css("tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]  # direct cells, not nested tables
        for cell in cells:
            if node_text(cell) in ("CD", "Senat", "SEN", "Guvern", "Promulgare", "CCR"):
                chamber = node_text(cell)
        if len(cells) < 3 or row.attributes.get("valign") != "top":
            continue
        date_cell, action_cell = cells[0], cells[-1]
        if "fff0d8" not in (date_cell.attributes.get("bgcolor") or ""):
            continue
        date = parse_dotted_date(node_text(date_cell))
        if date:
            current_date = date
        # The action is the cell's own text, before nested tables (bodies, documents) and notes.
        head = re.split(r"<dd|<table|<div", action_cell.html or "", maxsplit=1)[0]
        action = clean(re.sub(r"<[^>]+>", " ", head))
        if not action:
            continue
        bodies = [node_text(a) for a in action_cell.css("a") if "structura2015.co" in a.attributes.get("href", "")]
        if bodies:
            action = f"{action} {', '.join(bodies)}"
        documents = []
        for link in action_cell.css("a"):
            href = link.attributes.get("href", "")
            if href.lower().endswith(".pdf"):
                cell = link.parent
                label = node_text(cell.next) if cell is not None and cell.next is not None else ""
                documents.append({"url": absolute(href), "title": label or "PDF"})
        notes = [node_text(note) for note in action_cell.css("div") if note.attributes.get("id") == "obs"]
        events.append(
            {
                "date": current_date,
                "chamber": chamber,
                "action": action,
                "notes": "; ".join(notes) or None,
                "documents": documents,
            }
        )
    return events


def store_bill(conn: psycopg.Connection, idp: str, bill: dict, chamber: str = "cd", url: str | None = None) -> str:
    """Store a bill page of either chamber (senat_bills reuses this); ids are '<chamber>-<source id>'."""
    bid = f"{chamber}-{idp}"
    conn.execute(
        """INSERT INTO bills (id, chamber, source_id, number, cd_number, senate_number, senate_url, bpi_number, title,
               kind, procedure, decisional_chamber, character, urgent, status, law, law_url, initiator_summary,
               registered_on, last_event_on, ordinance, url, updated_at)
           VALUES (%(id)s, %(chamber)s, %(idp)s, %(number)s, %(cd_number)s, %(senate_number)s, %(senate_url)s,
               %(bpi_number)s, %(title)s, %(kind)s, %(procedure)s, %(decisional_chamber)s, %(character)s, %(urgent)s,
               %(status)s,
               %(law)s, %(law_url)s, %(initiator_summary)s, %(registered_on)s, %(last_event_on)s, %(ordinance)s,
               %(url)s, now())
           ON CONFLICT (id) DO UPDATE SET number = EXCLUDED.number, cd_number = EXCLUDED.cd_number,
               senate_number = EXCLUDED.senate_number, senate_url = EXCLUDED.senate_url,
                   bpi_number = EXCLUDED.bpi_number,
               title = EXCLUDED.title, kind = EXCLUDED.kind, procedure = EXCLUDED.procedure,
               decisional_chamber = EXCLUDED.decisional_chamber, character = EXCLUDED.character,
               urgent = EXCLUDED.urgent, status = EXCLUDED.status, law = EXCLUDED.law, law_url = EXCLUDED.law_url,
               initiator_summary = EXCLUDED.initiator_summary, registered_on = EXCLUDED.registered_on,
               last_event_on = EXCLUDED.last_event_on, ordinance = EXCLUDED.ordinance, url = EXCLUDED.url,
               updated_at = now()""",
        {
            "id": bid,
            "chamber": chamber,
            "idp": idp,
            "url": url or bill_url(idp),
            **{
                key: bill.get(key)
                for key in (
                    "number",
                    "cd_number",
                    "senate_number",
                    "senate_url",
                    "bpi_number",
                    "title",
                    "kind",
                    "procedure",
                    "decisional_chamber",
                    "character",
                    "urgent",
                    "status",
                    "law",
                    "law_url",
                    "initiator_summary",
                    "registered_on",
                    "last_event_on",
                    "ordinance",
                )
            },
        },
    )
    for table in ("bill_initiators", "bill_events", "bill_documents"):
        conn.execute(f"DELETE FROM {table} WHERE bill_id = %s", (bid,))
    for seq, person in enumerate(bill["initiators"]):
        conn.execute(
            "INSERT INTO bill_initiators VALUES (%s, %s, %s, %s, %s)",
            (bid, seq, person["member_ref"], person["name"], person["label"]),
        )
    for seq, event in enumerate(bill["events"]):
        conn.execute(
            "INSERT INTO bill_events VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                bid,
                seq,
                event["date"],
                event["chamber"],
                event["action"],
                event["notes"],
                json.dumps(event["documents"]),
            ),
        )
    for seq, document in enumerate(bill["documents"]):
        conn.execute(
            "INSERT INTO bill_documents VALUES (%s, %s, %s, %s)", (bid, seq, document["title"], document["url"])
        )
    if chamber == "cd":
        link_votes_and_agenda(conn, bid, bill["number"])
    return bid


def link_votes_and_agenda(conn: psycopg.Connection, bid: str, number: str) -> None:
    key = bill_key(number)
    if not key:
        return
    for table in ("votes", "agenda_items"):
        rows = conn.execute(f"SELECT DISTINCT bill_ref FROM {table} WHERE bill_id IS NULL AND bill_ref IS NOT NULL")
        refs = [row["bill_ref"] for row in rows if bill_key(row["bill_ref"]) == key]
        if refs:
            conn.execute(f"UPDATE {table} SET bill_id = %s WHERE bill_ref = ANY(%s)", (bid, refs))


def relink(conn: psycopg.Connection) -> int:
    """Attach votes and agenda items to stored bills by registry number."""
    bills = {}
    for row in conn.execute("SELECT id, number FROM bills WHERE number IS NOT NULL"):
        key = bill_key(row["number"])
        if key:
            bills.setdefault(key, row["id"])
    linked = 0
    for table in ("votes", "agenda_items"):
        rows = conn.execute(f"SELECT DISTINCT bill_ref FROM {table} WHERE bill_id IS NULL AND bill_ref IS NOT NULL")
        for row in rows.fetchall():
            bid = bills.get(bill_key(row["bill_ref"]))
            if bid:
                result = conn.execute(
                    f"UPDATE {table} SET bill_id = %s WHERE bill_ref = %s AND bill_id IS NULL", (bid, row["bill_ref"])
                )
                linked += result.rowcount
    linked += link_senators(conn)
    conn.commit()
    return linked


def link_senators(conn: psycopg.Connection) -> int:
    """Bill initiators link senators by their cdep.ro id; our senators come from senat.ro (GUIDs). Match by name
    within the legislature, and only when the name is unique among that legislature's senators."""
    senators: dict[tuple[int, str], list[str]] = {}
    for row in conn.execute("SELECT id, legislature, sort_name FROM members WHERE chamber = 'senat'"):
        senators.setdefault((row["legislature"], fold(row["sort_name"])), []).append(row["id"])
    rows = conn.execute(
        """SELECT DISTINCT member_ref, name FROM bill_initiators
           WHERE member_ref LIKE 'senat-%%' AND member_ref NOT IN (SELECT id FROM members)"""
    ).fetchall()
    linked = 0
    for row in rows:
        legislature = int(row["member_ref"].split("-")[1])
        match = senators.get((legislature, fold(row["name"])), [])
        if len(match) == 1:
            result = conn.execute(
                "UPDATE bill_initiators SET member_ref = %s WHERE member_ref = %s AND name = %s",
                (match[0], row["member_ref"], row["name"]),
            )
            linked += result.rowcount
    return linked


def known_bill_ids(conn: psycopg.Connection) -> set[str]:
    return {row["source_id"] for row in conn.execute("SELECT source_id FROM bills")}


def ingest(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    idps: list[str],
    refresh_days: int | None = None,
) -> int:
    """Fetch the given bills. With refresh_days, skip bills already stored whose last event is older than that."""
    log = db.log_start(conn, SOURCE, f"bills ({len(idps)})")
    stale_before = dt.date.today() - dt.timedelta(days=refresh_days) if refresh_days else None
    stored = {
        row["source_id"]: row["last_event_on"]
        for row in conn.execute(
            "SELECT source_id, last_event_on, law FROM bills WHERE law IS NOT NULL OR last_event_on IS NOT NULL"
        )
    }
    count, errors = 0, []
    for idp in dict.fromkeys(idps):
        last = stored.get(idp)
        if stale_before and last and last < stale_before:
            continue
        try:
            bill = parse_bill(fetcher.get("cdep", bill_url(idp)))
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        with conn.transaction():
            store_bill(conn, idp, bill)
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count


def idp_from_url(url: str) -> str | None:
    return query_param(url, "idp")
