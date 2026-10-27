"""RSS 2.0 feeds so people can follow an MP, a bill, new bills or new votes in any reader."""

import datetime as dt
from email.utils import format_datetime
from xml.sax.saxutils import escape

import psycopg

from parlament.web.filters import CHOICES


def _date(value) -> str:
    if value is None:
        return ""
    moment = value if isinstance(value, dt.datetime) else dt.datetime(value.year, value.month, value.day, 12)
    return format_datetime(moment.replace(tzinfo=dt.timezone(dt.timedelta(hours=2))))


def render(title: str, link: str, description: str, items: list[dict]) -> str:
    entries = "".join(
        f"<item><title>{escape(item['title'])}</title><link>{escape(item['link'])}</link>"
        f'<guid isPermaLink="false">{escape(item["guid"])}</guid><pubDate>{_date(item.get("date"))}</pubDate>'
        f"<description>{escape(item.get('description') or '')}</description></item>"
        for item in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{escape(title)}</title><link>{escape(link)}</link><description>{escape(description)}</description>"
        f"<language>ro</language>{entries}</channel></rss>"
    )


def bills_feed(conn: psycopg.Connection, base: str) -> str:
    rows = conn.execute(
        """SELECT DISTINCT ON (e.bill_id, e.seq) e.bill_id, e.seq, e.event_date, e.action, b.number, b.title
           FROM bill_events e JOIN bills b ON b.id = e.bill_id
           WHERE e.event_date IS NOT NULL ORDER BY e.bill_id, e.seq"""
    ).fetchall()
    rows = sorted(rows, key=lambda row: row["event_date"], reverse=True)[:100]
    items = [
        {
            "title": f"{row['number']}: {row['action']}",
            "link": f"{base}lege/{row['bill_id']}",
            "guid": f"{row['bill_id']}-{row['seq']}",
            "date": row["event_date"],
            "description": row["title"],
        }
        for row in rows
    ]
    return render("Proiecte legislative – noutăți", f"{base}legi", "Ultimele etape din procesul legislativ", items)


def votes_feed(conn: psycopg.Connection, base: str) -> str:
    rows = conn.execute("SELECT * FROM votes WHERE NOT is_test ORDER BY voted_at DESC LIMIT 100").fetchall()
    items = [
        {
            "title": row["description"],
            "link": f"{base}vot/{row['id']}",
            "guid": row["id"],
            "date": row["voted_at"],
            "description": (
                f"Pentru {row['yes']}, contra {row['no']}, abțineri {row['abstain']}, prezenți {row['present']}"
            ),
        }
        for row in rows
    ]
    return render("Voturi în plen", f"{base}voturi", "Ultimele voturi electronice", items)


def member_feed(conn: psycopg.Connection, base: str, member_id: str) -> str | None:
    member = conn.execute("SELECT name FROM members WHERE id = %s", (member_id,)).fetchone()
    if member is None:
        return None
    items = [
        {
            "title": f"Vot: {CHOICES.get(row['choice'], row['choice'])} – {row['description']}",
            "link": f"{base}vot/{row['id']}",
            "guid": f"{member_id}-{row['id']}",
            "date": row["voted_at"],
        }
        for row in conn.execute(
            """SELECT v.id, v.voted_at, v.description, r.choice FROM vote_records r JOIN votes v ON v.id = r.vote_id
               WHERE r.member_id = %s ORDER BY v.voted_at DESC LIMIT 50""",
            (member_id,),
        )
    ]
    items += [
        {
            "title": f"Inițiativă: {row['number']} – {row['title']}",
            "link": f"{base}lege/{row['id']}",
            "guid": f"{member_id}-{row['id']}",
            "date": row["registered_on"],
        }
        for row in conn.execute(
            """SELECT b.id, b.number, b.title, b.registered_on FROM bill_initiators i JOIN bills b ON b.id = i.bill_id
               WHERE i.member_ref = %s ORDER BY b.registered_on DESC NULLS LAST LIMIT 50""",
            (member_id,),
        )
    ]
    items += [
        {
            "title": f"Luare de cuvânt: {row['topic']}",
            "link": row["url"] or f"{base}parlamentar/{member_id}",
            "guid": f"{member_id}-speech-{row['seq']}",
            "date": row["sitting_on"],
            "description": row["sitting"],
        }
        for row in conn.execute(
            "SELECT * FROM speeches WHERE member_id = %s ORDER BY sitting_on DESC NULLS LAST LIMIT 30", (member_id,)
        )
    ]
    items.sort(key=lambda item: _sort_key(item.get("date")), reverse=True)
    return render(
        f"{member['name']} – activitate", f"{base}parlamentar/{member_id}", "Voturi, inițiative, luări de cuvânt", items
    )


def bill_feed(conn: psycopg.Connection, base: str, bill_id: str) -> str | None:
    bill = conn.execute("SELECT number, title FROM bills WHERE id = %s", (bill_id,)).fetchone()
    if bill is None:
        return None
    items = [
        {
            "title": row["action"],
            "link": f"{base}lege/{bill_id}",
            "guid": f"{bill_id}-{row['seq']}",
            "date": row["event_date"],
            "description": row["notes"] or "",
        }
        for row in conn.execute("SELECT * FROM bill_events WHERE bill_id = %s ORDER BY seq DESC", (bill_id,))
    ]
    return render(f"{bill['number']} – parcurs", f"{base}lege/{bill_id}", bill["title"], items)


def _sort_key(value) -> dt.datetime:
    if value is None:
        return dt.datetime.min
    return value if isinstance(value, dt.datetime) else dt.datetime(value.year, value.month, value.day)
