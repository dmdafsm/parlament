"""Stenogram text of Senate plenary sittings, split into speaker turns, for the same search as the Chamber's.

senat.ro publishes one PDF per sitting (text, not scanned), listed by day in a yearly calendar
(stenogramecalendar.aspx?Plen=1, year chosen with the page's own form). Joint sittings with the Chamber
('... comuna.pdf') are listed there too. Speakers are printed as 'Domnul Prenume Nume:' on their own line and are
matched to MPs of the legislature by their set of name words (`link_turns`). A published stenogram does not change.
"""

import datetime as dt
import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_steno import store
from parlament.ingest.senat_members import BASE
from parlament.parsing import ParseError, fold, form_fields, parse_long_date, pdf_text

SOURCE = "senat.ro"
CALENDAR = f"{BASE}/stenogramecalendar.aspx?Plen=1"
YEAR_FIELD = "ctl00$B_Center$StenogrameCalendar$txtAn"
YEAR_BUTTON = "ctl00$B_Center$StenogrameCalendar$Button2"
PDF_LINK = re.compile(r'href="(PAGINI/Stenograme/[^"]+?/(\d{2})\.(\d{2})\.(\d{2})[^"/]*\.pdf)"', re.I)
SPEAKER = re.compile(r"^(?:Domnul|Doamna)\s+([^:()]{3,70}?)(?:\s*\([^)]*\))?\s*:\s*$")
PAGE_NUMBER = re.compile(r"^\s*-\s*\d+\s*-\s*$")


def calendar_links(page: str) -> list[tuple[str, dt.date]]:
    """PDF links of one calendar year with their sitting date (from the file name 'YY.MM.DD...')."""
    links = {}
    for href, year, month, day in PDF_LINK.findall(page):
        links[f"{BASE}/{href.replace(' ', '%20')}"] = dt.date(2000 + int(year), int(month), int(day))
    return sorted(links.items(), key=lambda item: (item[1], item[0]))


def parse_stenogram(text: str, day: dt.date) -> dict:
    """{'sitting', 'sitting_on', 'title', 'turns': [{'speaker', 'member_ref', 'body'}]} from the PDF text."""
    lines = [line.strip() for line in text.splitlines()]
    heading = next((lines[i + 1] for i, line in enumerate(lines[:-1]) if line.replace(" ", "") == "STENOGRAMA"), "")
    if not heading:
        raise ParseError("senat stenogram: no heading")
    # 'ședinței Senatului din 7 octombrie 2026' -> 'Ședința Senatului din 7 octombrie 2026'
    sitting = re.sub(r"^ședinței\b", "Ședința", heading, flags=re.I)
    start = next((i for i, line in enumerate(lines) if line.startswith("Ședința a început")), 0)
    turns: list[dict] = []
    for line in lines[start:]:
        if not line or PAGE_NUMBER.match(line):
            continue
        match = SPEAKER.match(line)
        if match:
            turns.append({"speaker": match.group(1).strip(), "member_ref": None, "lines": []})
        elif turns:  # the opening lines (chair, secretaries) come before the first speaker
            turns[-1]["lines"].append(line)
    return {
        "sitting": sitting,
        "sitting_on": parse_long_date(sitting) or day,
        "title": None,
        "turns": [
            {"speaker": t["speaker"], "member_ref": None, "body": _join(t["lines"])} for t in turns if t["lines"]
        ],
    }


def _join(lines: list[str]) -> str:
    """Unwrap the PDF lines; a line ending a sentence closes a paragraph. 'într -un' -> 'într-un' (PDF spacing)."""
    text = ""
    for line in lines:
        text += line + ("\n" if line.endswith((".", "!", "?", ":")) else " ")
    return re.sub(r"(\w) -(\w)", r"\1-\2", text).strip()


def name_key(name: str) -> frozenset[str]:
    """Words of a name in any order; a role after a dash ('Ilie Bolojan – prim-ministrul ...') is left out."""
    return frozenset(fold(re.split(r"\s[–-]\s", name)[0]).split())


def link_turns(conn: psycopg.Connection, legislature: int) -> int:
    """Link Senate stenogram turns to MPs of the legislature whose name words match exactly one MP."""
    people: dict[frozenset[str], list[str]] = {}
    for row in conn.execute("SELECT id, sort_name FROM members WHERE legislature = %s", (legislature,)):
        people.setdefault(name_key(row["sort_name"]), []).append(row["id"])
    turns = conn.execute(
        """SELECT t.url, t.seq, t.speaker, t.member_id FROM speech_texts t JOIN stenograms s ON s.url = t.url
           WHERE s.chamber = 'senat' AND s.sitting_on >= %s""",
        (dt.date(legislature, 12, 1),),
    ).fetchall()
    changed = 0
    with conn.cursor() as cursor:
        for turn in turns:
            match = people.get(name_key(turn["speaker"]), [])
            member = match[0] if len(match) == 1 else None
            if member != turn["member_id"]:
                cursor.execute(
                    "UPDATE speech_texts SET member_id = %s WHERE url = %s AND seq = %s",
                    (member, turn["url"], turn["seq"]),
                )
                changed += 1
    conn.commit()
    return changed


def ingest(conn: psycopg.Connection, fetcher: Fetcher, legislature: int, limit: int | None = None) -> int:
    """Fetch the stenograms of the legislature's Senate sittings that are not stored yet."""
    since = dt.date(legislature, 12, 1)
    stored = {row["url"] for row in conn.execute("SELECT url FROM stenograms WHERE chamber = 'senat'")}
    # log_start commits, so each stenogram below is its own transaction and survives an interrupted run.
    log = db.log_start(conn, SOURCE, f"stenograms senat {legislature}")
    count, errors, links = 0, [], []
    try:
        page = fetcher.get("senat", CALENDAR, fresh=True)
        for year in range(since.year, dt.date.today().year + 1):
            form = {**form_fields(page), YEAR_FIELD: str(year), YEAR_BUTTON: "Update"}
            links += calendar_links(fetcher.post("senat", CALENDAR, form, f"an={year}", fresh=True))
    except (FetchError, ParseError) as error:
        errors.append(f"calendar: {error}")
    todo = [(url, day) for url, day in dict(links).items() if day >= since and url not in stored]
    for url, day in todo[:limit] if limit else todo:
        try:
            stenogram = parse_stenogram(pdf_text(fetcher.get_bytes("senat", url)), day)
        except (FetchError, ParseError) as error:
            errors.append(f"{url}: {error}")
            continue
        with conn.transaction():
            store(conn, url, stenogram, set(), chamber="senat")
        count += 1
    link_turns(conn, legislature)
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
