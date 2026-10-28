"""Bill pages of the Senate (senat.ro Legis/Lista.aspx?cod=N): details, initiators, documents, procedure.

Most bills pass through both chambers. A bill also on cdep.ro (same Senate number) keeps one page on the site,
the cdep.ro one; the Senate record holds the Senate's own procedure and is linked from it. Bills that never
reach the Chamber are only on senat.ro.
"""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_bills import ordinance_of, store_bill
from parlament.ingest.senat_members import BASE
from parlament.parsing import ParseError, clean, fold, html, node_text

SOURCE = "senat.ro"
SENATE_NUMBER = re.compile(r"\b([LB])\s*(\d+)\s*/\s*(?:\d{1,2}\.\d{1,2}\.)?(\d{4})")
CHAMBERS = {"SE": "Senat", "CD": "CD"}
# 'A devenit Legea nr.8/10.02.2025 publicatã în M.O. ...' -> law number as cdep.ro prints it ('Lege 8/2025').
LAW = re.compile(r"Legea\s+nr\.?\s*(\d+)\s*/\s*(?:\d{1,2}\.\d{1,2}\.)?(\d{4})")


def bill_url(cod: str) -> str:
    return f"{BASE}/Legis/Lista.aspx?cod={cod}"


def senate_key(text: str | None) -> str | None:
    """'L511/2026', 'L 511 / 2026', 'L511/02.09.2026' (date instead of year) -> 'L511/2026'."""
    match = SENATE_NUMBER.search(text or "")
    return f"{match.group(1)}{int(match.group(2))}/{match.group(3)}" if match else None


def absolute(href: str) -> str:
    href = href.replace("\\", "/")
    if href.startswith("http"):
        return href
    return f"{BASE}{href}" if href.startswith("/") else f"{BASE}/legis/{href}"


def parse_initiators(text: str) -> list[dict]:
    """'Chertif Costache  - senator AUR; Popescu Ion - deputat PSD' -> name and label."""
    people = []
    for part in text.split(";"):
        name, _, label = clean(part).partition(" - ")
        if name:
            people.append({"name": clean(name), "label": clean(label) or None, "member_ref": None})
    return people


def parse_bill(page: str) -> dict:
    tree = html(page)
    grid = next((t for t in tree.css("table") if [node_text(c) for c in t.css("th")][1:3] == ["Numar", "Titlu"]), None)
    row = next((r for r in grid.css("tr") if r.css("td")), None) if grid is not None else None
    if row is None:
        raise ParseError("senat bill: no bill on the page")
    cells = [cell for cell in row.iter() if cell.tag == "td"]
    title = node_text(cells[2].css_first("p"))
    details = {}
    for table in tree.css("table"):
        for line in table.css("tr"):
            pair = [cell for cell in line.iter() if cell.tag == "td"]
            if len(pair) == 2 and node_text(pair[0]).endswith(":"):
                details[fold(node_text(pair[0]).rstrip(":"))] = node_text(pair[1])
    number = senate_key(details.get("numar de inregistrare senat") or node_text(cells[1]))
    if not number or not title:
        raise ParseError("senat bill: missing number or title")
    events = parse_events(tree)
    dates = [event["date"] for event in events if event["date"]]
    documents, seen = [], set()
    for link in tree.css("div.not_k a"):
        url = absolute(link.attributes.get("href", "").split("?")[0])
        if url.lower().endswith(".pdf") and url.lower() not in seen:
            seen.add(url.lower())
            documents.append({"title": node_text(link).lstrip("- ") or "PDF", "url": url})
    initiators = parse_initiators(details.get("initiatori", ""))
    status = details.get("stadiu") or node_text(cells[3]) or None
    law = LAW.search(status or "")
    return {
        "number": number,
        "senate_number": number,
        "cd_number": details.get("numar de inregistrare camera deputatilor") or None,
        "title": title,
        "kind": details.get("tip initiativa") or None,
        "procedure": f"Prima cameră: {details['prima camera']}" if details.get("prima camera") else None,
        "character": details.get("caracterul legii") or None,
        "urgent": details["procedura de urgenta"].lower().startswith("da")
        if details.get("procedura de urgenta")
        else None,
        "status": status,
        "law": f"Lege {law.group(1)}/{law.group(2)}" if law else None,
        "initiator_summary": "; ".join(sorted({p["label"] for p in initiators if p["label"]})) or None,
        "initiators": initiators,
        "documents": documents,
        "events": events,
        "registered_on": min(dates) if dates else None,
        "last_event_on": max(dates) if dates else None,
        "ordinance": ordinance_of(title),
    }


def parse_events(tree) -> list[dict]:
    table = tree.css_first("table.legislative-procedure-table")
    events = []
    for row in table.css("tbody tr") if table is not None else []:
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) < 2:
            continue
        match = re.match(r"(\d{2})-(\d{2})-(\d{4})", node_text(cells[0]))
        date = dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1))) if match else None
        head = re.split(r"<input|<a\s", cells[1].html or "", maxsplit=1)[0]
        action = clean(re.sub(r"<[^>]+>", " ", head)).replace(" ,", ",")
        if not action:
            continue
        documents = [
            {"title": node_text(link) or "PDF", "url": absolute(link.attributes["href"].split("?")[0])}
            for link in cells[1].css("a")
            if ".pdf" in link.attributes.get("href", "").lower()
        ]
        code = node_text(cells[2]) if len(cells) > 2 else "SE"
        events.append(
            {"date": date, "chamber": CHAMBERS.get(code, code), "action": action, "notes": None, "documents": documents}
        )
    return events


def link(conn: psycopg.Connection) -> int:
    """Senate votes and agenda items go to the cdep.ro bill with the same Senate number, else to the Senate bill.
    Initiators are linked by name (surname first, as both chambers print it) when it is unique."""
    linked = 0
    for table, scope in (
        ("votes", "t.chamber = 'senat'"),
        ("agenda_items", "t.agenda_id LIKE 'senat-%%'"),
    ):
        result = conn.execute(
            f"""UPDATE {table} t SET bill_id = best.id
                FROM (SELECT DISTINCT ON (senate_key) senate_key, id FROM bills WHERE senate_key IS NOT NULL
                      ORDER BY senate_key, chamber) best
                WHERE {scope} AND t.bill_ref = best.senate_key AND t.bill_id IS DISTINCT FROM best.id"""
        )
        linked += result.rowcount
    people: dict[str, list[str]] = {}
    for row in conn.execute("SELECT id, sort_name FROM members"):
        people.setdefault(fold(row["sort_name"]), []).append(row["id"])
    rows = conn.execute(
        """SELECT DISTINCT i.name FROM bill_initiators i JOIN bills b ON b.id = i.bill_id
           WHERE b.chamber = 'senat' AND i.member_ref IS NULL"""
    ).fetchall()
    for row in rows:
        match = people.get(fold(row["name"]), [])
        if len(match) == 1:
            result = conn.execute(
                """UPDATE bill_initiators SET member_ref = %s
                   WHERE name = %s AND member_ref IS NULL AND bill_id LIKE 'senat-%%'""",
                (match[0], row["name"]),
            )
            linked += result.rowcount
    conn.commit()
    return linked


def ingest(conn: psycopg.Connection, fetcher: Fetcher, codes: list[str], refresh_days: int | None = 30) -> int:
    """Fetch Senate bill pages. Bills already stored whose last event is older than refresh_days are skipped."""
    log = db.log_start(conn, SOURCE, f"bills senat ({len(set(codes))})")
    stale_before = dt.date.today() - dt.timedelta(days=refresh_days) if refresh_days else None
    stored = {
        row["source_id"]: row["last_event_on"]
        for row in conn.execute("SELECT source_id, last_event_on FROM bills WHERE chamber = 'senat'")
    }
    count, errors = 0, []
    for cod in dict.fromkeys(codes):
        if cod in stored and (stale_before is None or (stored[cod] and stored[cod] < stale_before)):
            continue
        try:
            bill = parse_bill(fetcher.get("senat", bill_url(cod)))
            bill["senate_url"] = bill_url(cod)
        except (FetchError, ParseError) as error:
            errors.append(f"{cod}: {error}")
            continue
        with conn.transaction():
            store_bill(conn, cod, bill, chamber="senat", url=bill_url(cod))
        count += 1
    link(conn)
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
