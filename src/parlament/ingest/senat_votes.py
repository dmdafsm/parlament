"""Electronic votes of the Senate (senat.ro Voturiplen.aspx): calendar, daily list and nominal results.

The calendar and the daily list are ASP.NET postbacks on the same page; we submit the page's own form, as a
browser does when a day is clicked. Days with votes are highlighted in the calendar. The nominal page
(VoturiPlenDetaliu.aspx) is a plain link. It lists the senators registered at the vote; a row with no option
marked is not counted as present by the Senate and is not stored, like a missing deputy on cdep.ro.
"""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.senat_members import BASE, member_id
from parlament.parsing import ParseError, form_fields, html, int_or_none, node_text, query_param

SOURCE = "senat.ro"
VOTES_URL = f"{BASE}/Voturiplen.aspx"
CALENDAR = "ctl00$B_Center$VoturiPlen1$calVOT"
PAGING = "ctl00$B_Center$VoturiPlen1$chkPaginare"
# ASP.NET calendars number days from 1 January 2000.
EPOCH = dt.date(2000, 1, 1)
# Columns of the nominal table after name, first name and group.
CHOICES = ["yes", "no", "abstain", "present_not_voting"]


def nominal_url(app_id: str) -> str:
    return f"{BASE}/VoturiPlenDetaliu.aspx?AppID={app_id.lower()}"


def form_state(page: str) -> dict[str, str]:
    """The paging checkbox is left out (unchecked), so a day lists all its votes."""
    return form_fields(page, leave_out=(PAGING,))


def postback(state: dict[str, str], argument: str) -> dict[str, str]:
    return {**state, "__EVENTTARGET": CALENDAR, "__EVENTARGUMENT": argument}


def vote_days(page: str) -> list[dt.date]:
    """Days highlighted in the calendar (the Senate held electronic votes)."""
    days = []
    for cell in html(page).css("td.myCalendarDay, td.myCalendarToday"):
        link = cell.css_first("a")
        match = re.search(r"calVOT','(\d+)'", link.attributes.get("href", "")) if link else None
        if match and (cell.attributes.get("bgcolor") or "").lower() == "cyan":
            days.append(EPOCH + dt.timedelta(days=int(match.group(1))))
    return sorted(set(days))


def parse_day(page: str, day: dt.date) -> list[dict]:
    box = html(page).css_first("div.voturi-plen-agenda")
    votes = []
    for row in box.css("tr") if box is not None else []:
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) != 9:
            continue
        detail = cells[2].css_first("a")
        app_id = query_param(detail.attributes.get("href", ""), "AppID") if detail else None
        if not app_id:
            continue
        bill = cells[1].css_first("a")
        heading, _, title = (detail.html or "").partition("<br>")
        name = node_text(html(f"<p>{heading}</p>").css_first("p")).replace("|", " ")
        ref = re.match(r"([LB]\d+/\d{4})", node_text(cells[1]))
        time = re.match(r"(\d{1,2}):(\d{2})", node_text(cells[0]))
        description = node_text(html(f"<p>{title}</p>").css_first("p"))
        votes.append(
            {
                "app_id": app_id.lower(),
                "seq": len(votes),
                "voted_at": dt.datetime.combine(
                    day, dt.time(int(time.group(1)), int(time.group(2))) if time else dt.time()
                ),
                "description": f"{re.sub(r'\s+', ' ', name).strip()}: {description}" if description else name,
                "bill_ref": ref.group(1) if ref else None,
                "bill_cod": query_param(bill.attributes.get("href", ""), "cod") if bill else None,
                "result": node_text(cells[3]) or None,
                "present": int_or_none(node_text(cells[4])),
                "yes": int_or_none(node_text(cells[5])),
                "no": int_or_none(node_text(cells[6])),
                "abstain": int_or_none(node_text(cells[7])),
                "not_voted": int_or_none(node_text(cells[8])),
            }
        )
    return votes


def parse_nominal(page: str, legislature: int) -> list[dict]:
    records = []
    for table in html(page).css("table"):
        header = [node_text(cell) for cell in table.css("th")]
        if header[:3] != ["Nume", "Prenume", "Grup"]:
            continue
        for row in table.css("tr"):
            cells = [cell for cell in row.iter() if cell.tag == "td"]
            if len(cells) < 7:
                continue
            link = cells[0].css_first("a")
            guid = query_param(link.attributes.get("href", ""), "ParlamentarID") if link else None
            marked = [choice for choice, cell in zip(CHOICES, cells[3:7], strict=True) if node_text(cell) == "X"]
            if not guid or len(marked) != 1:
                continue
            records.append(
                {
                    "member_id": member_id(legislature, guid),
                    "name": f"{node_text(cells[0])} {node_text(cells[1])}",
                    "group": node_text(cells[2]),
                    "choice": marked[0],
                }
            )
    return records


def store_vote(conn: psycopg.Connection, vote: dict, records: list[dict] | None) -> None:
    vid = f"senat-{vote['app_id']}"
    conn.execute(
        """INSERT INTO votes (id, chamber, source_id, voted_at, seq, description, bill_ref, result, present, yes, no,
               abstain, not_voted, has_nominal, url)
           VALUES (%s, 'senat', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO UPDATE SET voted_at = EXCLUDED.voted_at, seq = EXCLUDED.seq,
               description = EXCLUDED.description, bill_ref = EXCLUDED.bill_ref, result = EXCLUDED.result,
               present = EXCLUDED.present, yes = EXCLUDED.yes, no = EXCLUDED.no, abstain = EXCLUDED.abstain,
               not_voted = EXCLUDED.not_voted, has_nominal = votes.has_nominal OR EXCLUDED.has_nominal""",
        (
            vid,
            vote["app_id"],
            vote["voted_at"],
            vote["seq"],
            vote["description"],
            vote["bill_ref"],
            vote["result"],
            vote["present"],
            vote["yes"],
            vote["no"],
            vote["abstain"],
            vote["not_voted"],
            records is not None,
            nominal_url(vote["app_id"]),
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


def months(start: dt.date, end: dt.date) -> list[dt.date]:
    result, month = [], start.replace(day=1)
    while month <= end:
        result.append(month)
        month = (month + dt.timedelta(days=32)).replace(day=1)
    return result


def ingest(
    conn: psycopg.Connection, fetcher: Fetcher, start: dt.date, end: dt.date, legislature: int, nominal: bool = True
) -> tuple[int, list[str]]:
    """Votes between start and end. Returns (votes stored, Senate bill codes seen)."""
    log = db.log_start(conn, SOURCE, f"votes senat {start}..{end}")
    done = {
        row["source_id"] for row in conn.execute("SELECT source_id FROM votes WHERE chamber = 'senat' AND has_nominal")
    }
    count, codes, errors = 0, [], []
    today = dt.date.today()
    try:
        # A fresh form for this session; past months and days are kept in the raw cache under their own key.
        state = form_state(fetcher.get("senat", VOTES_URL, fresh=True))
    except (FetchError, ParseError) as error:
        db.log_end(conn, log, "error", 0, str(error))
        return 0, []
    for month in months(start, end):
        current = month.year == today.year and month.month == today.month
        try:
            argument = f"V{(month - EPOCH).days}"
            calendar = fetcher.post(
                "senat", VOTES_URL, postback(state, argument), f"month={month:%Y-%m}", fresh=current
            )
        except FetchError as error:
            errors.append(str(error))
            continue
        for day in vote_days(calendar):
            if not start <= day <= end:
                continue
            try:
                page = fetcher.post(
                    "senat",
                    VOTES_URL,
                    postback(form_state(calendar), str((day - EPOCH).days)),
                    f"day={day}",
                    fresh=(today - day).days < 7,
                )
                votes = parse_day(page, day)
            except (FetchError, ParseError) as error:
                errors.append(str(error))
                continue
            for vote in votes:
                records = None
                if nominal and vote["app_id"] not in done:
                    try:
                        records = parse_nominal(fetcher.get("senat", nominal_url(vote["app_id"])), legislature)
                    except FetchError as error:
                        errors.append(str(error))
                with conn.transaction():
                    store_vote(conn, vote, records)
                if vote["bill_cod"]:
                    codes.append(vote["bill_cod"])
                count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count, codes
