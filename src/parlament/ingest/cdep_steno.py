"""Stenogram text of Chamber sittings (cdep.ro steno2015.stenograma), split into speaker turns.

Pages come from the speeches lists of the deputies (`speeches.url`), so only agenda points where a deputy spoke
are fetched. A published stenogram does not change; each page is fetched once.
"""

import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_members import member_ref_from_url
from parlament.parsing import ParseError, html, node_text, parse_long_date

SOURCE = "cdep.ro"
# Each paragraph block of the text sits between these markers.
BLOCK = re.compile(r"<!-- START=[^>]*-->(.*?)<!-- END -->", re.S)
# A new turn starts with the speaker's name in bold, followed by a colon.
SPEAKER = re.compile(r"\s*(?:<p[^>]*>\s*)?<B>(.*?)</B>\s*:", re.S | re.I)
# The "detalii vot" link after a vote is not part of the text.
VOTE_LINK = re.compile(r'<div id="MaiMulte">.*?</div>', re.S)


def parse_stenogram(page: str) -> dict:
    """{'sitting', 'sitting_on', 'title', 'turns': [{'speaker', 'member_ref', 'body'}]}."""
    tree = html(page)
    heading = tree.css_first("div.box-title h3")
    point = tree.css_first('td[width="100%"][bgcolor="#fef9c2"]')
    if heading is None or not BLOCK.search(page):
        raise ParseError("cdep stenogram: no sitting heading or text")
    turns = []
    for block in BLOCK.findall(page):
        match = SPEAKER.match(block)
        if match:
            head = html(f"<div>{match.group(1)}</div>")
            link = head.css_first("a")
            turns.append(
                {
                    "speaker": node_text(head.css_first("div")),
                    "member_ref": member_ref_from_url(link.attributes.get("href", "")) if link else None,
                    "parts": [],
                }
            )
            block = block[match.end() :]
        if turns:  # stage directions before the first speaker ('După pauză') are left out
            turns[-1]["parts"].extend(_paragraphs(block))
    sitting = node_text(heading)
    return {
        "sitting": sitting,
        "sitting_on": parse_long_date(sitting),
        "title": node_text(point) or None,
        "turns": [
            {"speaker": t["speaker"], "member_ref": t["member_ref"], "body": "\n".join(t["parts"])}
            for t in turns
            if t["parts"]
        ],
    }


def _paragraphs(block: str) -> list[str]:
    pieces = re.split(r"<p[^>]*>", VOTE_LINK.sub("", block), flags=re.I)
    texts = (node_text(html(f"<div>{piece}</div>").css_first("div")) for piece in pieces)
    return [text for text in texts if text]


def store(conn: psycopg.Connection, url: str, stenogram: dict, members: set[str], chamber: str = "cd") -> None:
    """Upsert a stenogram and replace its turns; shared with senat_steno."""
    conn.execute(
        """INSERT INTO stenograms (url, chamber, sitting, sitting_on, title) VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (url) DO UPDATE SET sitting = EXCLUDED.sitting, sitting_on = EXCLUDED.sitting_on,
               title = EXCLUDED.title, fetched_at = now()""",
        (url, chamber, stenogram["sitting"], stenogram["sitting_on"], stenogram["title"]),
    )
    conn.execute("DELETE FROM speech_texts WHERE url = %s", (url,))
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO speech_texts (url, seq, member_id, speaker, body) VALUES (%s, %s, %s, %s, %s)",
            [
                (url, seq, turn["member_ref"] if turn["member_ref"] in members else None, turn["speaker"], turn["body"])
                for seq, turn in enumerate(stenogram["turns"])
            ],
        )


def ingest(conn: psycopg.Connection, fetcher: Fetcher, limit: int | None = None) -> int:
    """Fetch the stenogram pages linked from the speeches lists that are not stored yet."""
    urls = [
        row["url"]
        for row in conn.execute(
            """SELECT DISTINCT s.url, s.sitting_on FROM speeches s JOIN members m ON m.id = s.member_id
               WHERE m.chamber = 'cd' AND s.url LIKE '%%steno2015.stenograma%%'
                   AND NOT EXISTS (SELECT 1 FROM stenograms t WHERE t.url = s.url)
               ORDER BY s.sitting_on DESC NULLS LAST"""
        )
    ]
    members = {row["id"] for row in conn.execute("SELECT id FROM members")}
    # log_start commits, so each stenogram below is its own transaction and survives an interrupted run.
    log = db.log_start(conn, SOURCE, f"stenograms ({len(urls)})")
    count, errors = 0, []
    for url in urls[:limit] if limit else urls:
        try:
            stenogram = parse_stenogram(fetcher.get("cdep", url))
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        with conn.transaction():
            store(conn, url, stenogram, members)
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
