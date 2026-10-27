"""Electronic votes of the Chamber of Deputies (cdep.ro evot2015): daily list and nominal results.

The nominal page lists only deputies who were present. Not being listed is not stored as a vote;
analytics derive 'not present' from the mandate dates.
"""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_bills import find_bill_ref
from parlament.ingest.cdep_members import BASE, member_ref_from_url
from parlament.parsing import ParseError, clean, html, int_or_none, node_text, parse_long_date, query_param

SOURCE = "cdep.ro"
CHOICES = {"DA": "yes", "NU": "no", "AB": "abstain", "-": "present_not_voting"}


def day_url(day: dt.date) -> str:
    return f"{BASE}/pls/steno/evot2015.data?dat={day:%Y%m%d}&cam=2&idl=1"


def nominal_url(idv: str) -> str:
    return f"{BASE}/pls/steno/evot2015.nominal?idv={idv}&idl=1"


def latest_url() -> str:
    """Without a date the page shows the most recent sitting with electronic votes."""
    return f"{BASE}/pls/steno/evot2015.data"


def page_date(page: str) -> dt.date | None:
    """'Luni, 23 decembrie  2024' in the page heading."""
    heading = html(page).css_first("div.boxTitle h1")
    return parse_long_date(node_text(heading)) if heading is not None else None


def parse_day(page: str, day: dt.date) -> list[dict]:
    """Rows of the daily list: id, time, description and totals."""
    votes = []
    for row in html(page).css("table tbody tr"):
        cells = {cell.attributes.get("data-label", ""): cell for cell in row.css("td")}
        if "Id vot" not in cells:
            continue
        idv = node_text(cells["Id vot"])
        time = re.match(r"(\d{1,2}):(\d{2})", node_text(cells.get("Ora")))
        if not idv.isdigit() or not time:
            continue
        description = node_text(cells.get("Descriere"))
        not_voted = next((cell for label, cell in cells.items() if label.startswith("Nu au votat")), None)
        against = next((cell for label, cell in cells.items() if label.endswith("mpotriva")), None)
        votes.append(
            {
                "idv": idv,
                "voted_at": dt.datetime(day.year, day.month, day.day, int(time.group(1)), int(time.group(2))),
                "description": description,
                "present": int_or_none(node_text(cells.get("Prezenta"))),
                "yes": int_or_none(node_text(cells.get("Pentru"))),
                "no": int_or_none(node_text(against)),
                "abstain": int_or_none(node_text(cells.get("Abtineri"))),
                "not_voted": int_or_none(node_text(not_voted)),
                "is_test": description.lower().startswith("vot test"),
            }
        )
    return votes


def parse_nominal(page: str) -> list[dict]:
    """Deputies present at one vote, with group and option."""
    records = []
    for row in html(page).css("tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) != 4 or not re.match(r"\d+\.$", node_text(cells[0])):
            continue
        link = cells[1].css_first("a")
        choice = CHOICES.get(clean(node_text(cells[3])).upper())
        ref = member_ref_from_url(link.attributes.get("href", "")) if link else None
        if ref is None or choice is None:
            continue
        records.append({"member_id": ref, "name": node_text(link), "group": node_text(cells[2]), "choice": choice})
    return records


def nominal_subject(page: str) -> str | None:
    for row in html(page).css("tr"):
        cells = row.css("td")
        if len(cells) == 2 and node_text(cells[0]).startswith("Subiect vot"):
            return node_text(cells[1])
    return None


def store_vote(conn: psycopg.Connection, vote: dict, records: list[dict] | None) -> None:
    vid = f"cd-{vote['idv']}"
    conn.execute(
        """INSERT INTO votes (id, chamber, source_id, voted_at, description, bill_ref, present, yes, no, abstain,
               not_voted, is_test, has_nominal, url)
           VALUES (%s, 'cd', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET description = EXCLUDED.description, bill_ref = EXCLUDED.bill_ref,
               present = EXCLUDED.present, yes = EXCLUDED.yes, no = EXCLUDED.no, abstain = EXCLUDED.abstain,
               not_voted = EXCLUDED.not_voted, is_test = EXCLUDED.is_test,
               has_nominal = votes.has_nominal OR EXCLUDED.has_nominal""",
        (
            vid,
            vote["idv"],
            vote["voted_at"],
            vote["description"],
            find_bill_ref(vote["description"]),
            vote["present"],
            vote["yes"],
            vote["no"],
            vote["abstain"],
            vote["not_voted"],
            vote["is_test"],
            records is not None,
            nominal_url(vote["idv"]),
        ),
    )
    if records is not None:
        conn.execute("DELETE FROM vote_records WHERE vote_id = %s", (vid,))
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO vote_records (vote_id, member_id, member_name, group_code, choice)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                [(vid, r["member_id"], r["name"], r["group"], r["choice"]) for r in records],
            )


def ingest_days(conn: psycopg.Connection, fetcher: Fetcher, days: list[dt.date | None], nominal: bool = True) -> int:
    """Votes for each day; None means the latest sitting (the page without a date)."""
    label = "votes latest" if days == [None] else f"votes {days[0]}..{days[-1]}" if days else "votes"
    log = db.log_start(conn, SOURCE, label)
    done = {
        row["source_id"] for row in conn.execute("SELECT source_id FROM votes WHERE chamber = 'cd' AND has_nominal")
    }
    count, errors = 0, []
    for day in days:
        try:
            page = fetcher.get("cdep", day_url(day) if day else latest_url())
            day = day or page_date(page)
            if day is None:
                raise ParseError("cdep votes: no date in the latest-sitting page")
            votes = parse_day(page, day)
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        for vote in votes:
            records = None
            if nominal and not vote["is_test"] and vote["idv"] not in done:
                try:
                    records = parse_nominal(fetcher.get("cdep", nominal_url(vote["idv"])))
                except FetchError as error:
                    errors.append(str(error))
            with conn.transaction():
                store_vote(conn, vote, records)
            count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count


def sitting_days(start: dt.date, end: dt.date) -> list[dt.date]:
    """Plenary votes happen on weekdays; the daily page for other days is simply empty."""
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def idv_from_url(url: str) -> str | None:
    return query_param(url, "idv")
