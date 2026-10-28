"""Activity lists of senators on senat.ro: questions, interpellations, speeches and motions.

Each list is a postback on the profile page (like the biography). Questions, interpellations and speeches are
paged grids, newest first, spanning the senator's earlier mandates too: pages are followed until the dates fall
before the legislature (at most MAX_PAGES). Motions are listed for the selected (current) legislature.
Speeches are only the dates of the sittings where the senator spoke; the Senate lists no topic per speech.
"""

import datetime as dt
import re
from functools import partial

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_activity import store
from parlament.ingest.senat_members import BASE, profile_url
from parlament.parsing import ParseError, form_fields, html, node_text, parse_dotted_date

SOURCE = "senat.ro"
PREFIX = "ctl00$B_Center$Repeater14$ctl00$"
# list -> (profile link, grid that pages it, profile counter that says whether to open it)
LISTS = {
    "intrebare": ("Intrebari", "ctl00$B_Center$cIntrebari$GridViewListaIntrebari", "questions"),
    "interpelare": ("Interpelari", "ctl00$B_Center$cInterpelari$GridViewListaIntrebari", "interpellations"),
    "speeches": ("LuariCuvint", "ctl00$B_Center$cSteno$gr2Rezultat", "speeches"),
    "motions": ("Motiuni", None, "motions"),
}
MAX_PAGES = 15
DATE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4})\b")

MONTHS = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]  # fmt: skip


def absolute(href: str) -> str:
    """'PDFIntrebari\\1600a x.pdf' -> https://www.senat.ro/PDFIntrebari/1600a%20x.pdf."""
    href = href.replace("\\", "/").replace(" ", "%20")
    return href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"


def parse_questions(page: str, kind: str, fallback_url: str) -> list[dict]:
    """One row per question (`tr.question-answer-wrapper`); answers are nested inside the row."""
    result = []
    for row in html(page).css("tr.question-answer-wrapper"):
        box = row.css_first("div.question-box")
        key = row.css_first('input[name$="hTipIntrebareID"]')
        if box is None or key is None:
            continue
        header = node_text(box.css_first("div"))
        number = re.search(r"nr\.\s*(\S+)", header)
        date = DATE.search(header)
        title = box.css_first('div[style*="font-weight"]')
        recipient = re.search(r"Destinatar:\s*(.+?)(?:\s+Click pt\.|$)", node_text(box))
        link = box.css_first('a[href*="PDF"]')
        result.append(
            {
                "id": f"senat-{key.attributes.get('value')}",
                "kind": kind,
                "number": number.group(1) if number else None,
                "asked_on": parse_dotted_date(date.group(1)) if date else None,
                "title": node_text(title) or None,
                "recipient": recipient.group(1) if recipient else None,
                "answered": row.css_first("div.answer-box") is not None,
                "url": absolute(link.attributes["href"]) if link else fallback_url,
            }
        )
    return result


def parse_speeches(page: str) -> list[dict]:
    result = []
    for row in html(page).css("tr.senator-steno-table-tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", node_text(cells[0])) if cells else None
        if match is None:
            continue
        day = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        result.append(
            {
                "sitting": f"Ședința Senatului din {day.day} {MONTHS[day.month - 1]} {day.year}",
                "sitting_on": day,
                "topic": None,
                "duration": None,
                "url": None,
            }
        )
    return result


def parse_motions(page: str) -> list[dict]:
    """Simple motions (Senate) and censure motions (joint sitting) signed by the senator."""
    result = []
    for grid in ("GridViewMotiuneSenat", "GridViewMotiuneCenzura"):
        table = html(page).css_first(f'table[id$="{grid}"]')
        for row in table.css("tr") if table is not None else []:
            cells = [cell for cell in row.iter() if cell.tag == "td"]
            link = cells[0].css_first("a") if len(cells) == 5 else None
            if link is None:
                continue
            url = absolute(link.attributes.get("href", ""))
            votes = re.search(r"(\d+)\s+(\d+)\s+(\d+)\s*$", node_text(cells[4]))
            outcome = node_text(cells[4]).split(" DA ")[0].strip()
            if votes:
                outcome += f" ({votes.group(1)} pentru, {votes.group(2)} împotrivă, {votes.group(3)} abțineri)"
            result.append(
                {
                    "id": "senat-" + re.sub(r"\.pdf$", "", url.rsplit("/", 1)[-1], flags=re.I),
                    "chamber": "senat",
                    "title": node_text(link).strip('"„”'),
                    "initiators": None,
                    "registered": node_text(cells[2]) or None,
                    "result": outcome or None,
                    "url": url,
                }
            )
    return result


def list_pages(fetcher: Fetcher, url: str, profile: str, link: str, grid: str | None, parse, since: dt.date) -> list:
    """Items of the list opened from the profile, following its pages while they are within the legislature."""
    form = {**form_fields(profile), "__EVENTTARGET": PREFIX + link, "__EVENTARGUMENT": ""}
    page = fetcher.post("senat", url, form, link.lower())
    items = parse(page)
    for number in range(2, MAX_PAGES + 1):
        dates = [item.get("asked_on") or item.get("sitting_on") for item in items]
        dates = [d for d in dates if d]
        if grid is None or f"Page${number}" not in page or not dates or min(dates) < since:
            break
        form = {**form_fields(page), "__EVENTTARGET": grid, "__EVENTARGUMENT": f"Page${number}"}
        page = fetcher.post("senat", url, form, f"{link.lower()}-{number}")
        items += parse(page)
    return items


def ingest(conn: psycopg.Connection, fetcher: Fetcher, legislature: int, limit: int | None = None) -> int:
    # Dates before the legislature belong to earlier mandates (same rule as the votes: elections in December).
    since = dt.date(legislature, 12, 1)
    senators = conn.execute(
        """SELECT m.id, m.source_id, jsonb_object_agg(s.metric, s.value) FILTER (WHERE s.metric IS NOT NULL) AS stats
           FROM members m LEFT JOIN member_stats s ON s.member_id = m.id
           WHERE m.chamber = 'senat' AND m.legislature = %s GROUP BY m.id, m.source_id ORDER BY m.id""",
        (legislature,),
    ).fetchall()
    # log_start commits, so each senator below is its own transaction and survives an interrupted run.
    log = db.log_start(conn, SOURCE, f"activity senat {legislature}")
    count, errors = 0, []
    for senator in senators[:limit] if limit else senators:
        stats = senator["stats"] or {}
        wanted = {key: spec for key, spec in LISTS.items() if stats.get(spec[2])}
        if not wanted:
            continue
        url = profile_url(senator["source_id"])
        data: dict[str, list] = {"questions": []}
        try:
            profile = fetcher.get("senat", url)
            for key, (link, grid, _) in wanted.items():
                if key in ("intrebare", "interpelare"):
                    parse = partial(parse_questions, kind=key, fallback_url=url)
                    data["questions"] += list_pages(fetcher, url, profile, link, grid, parse, since)
                elif key == "speeches":
                    data["speeches"] = list_pages(fetcher, url, profile, link, grid, parse_speeches, since)
                else:
                    data["motions"] = list_pages(fetcher, url, profile, link, grid, parse_motions, since)
        except (FetchError, ParseError) as error:
            errors.append(f"{senator['id']}: {error}")
            continue
        data["questions"] = [q for q in data["questions"] if not q["asked_on"] or q["asked_on"] >= since]
        if "speeches" in data:
            data["speeches"] = [s for s in data["speeches"] if s["sitting_on"] >= since]
        with conn.transaction():
            store(conn, senator["id"], data)
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
