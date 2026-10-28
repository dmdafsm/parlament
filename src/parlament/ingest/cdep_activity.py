"""Per-deputy activity lists on cdep.ro: bills initiated, questions, motions, speeches, declarations.

Profile sub-pages are `structura2015.mp?...&pag=N`: 2 = bills initiated, 3 = questions and interpellations,
6 = interest declarations (scanned PDFs), 11 = motions signed. Speeches come from the stenogram search
linked on the profile (`steno2015.lista?idv=...`).
"""

import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_members import SITE, absolute
from parlament.parsing import ParseError, html, node_text, parse_dotted_date, parse_long_date, query_param

SOURCE = "cdep.ro"


def subpage_url(idm: str, legislature: int, page: int) -> str:
    return f"{SITE}/pls/parlam/structura2015.mp?idm={idm}&cam=2&leg={legislature}&pag={page}&idl=1&prn=0&par="


def parse_initiatives(page: str) -> list[dict]:
    """Bills the deputy initiated: cdep id (idp), numbers, title and stage."""
    result = []
    for row in html(page).css("div.grup-parlamentar-list table tbody tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) < 5:
            continue
        link = cells[1].css_first("a")
        idp = query_param(link.attributes.get("href", ""), "idp") if link else None
        if idp:
            result.append(
                {"idp": idp, "cd_number": node_text(link), "title": node_text(cells[3]), "status": node_text(cells[4])}
            )
    return result


def parse_questions(page: str) -> list[dict]:
    result = []
    for row in html(page).css("div.grup-parlamentar-list table tr"):
        link = row.css_first("a")
        if link is None or "interpelari2015.detalii" not in link.attributes.get("href", ""):
            continue
        label = node_text(link)
        match = re.match(r"(Întrebarea|Interpelarea)\s+nr\.\s*(\S+?)\s*/\s*([\d.-]+)", label)
        cell_text = node_text(row.css("td")[-1])
        title = cell_text[len(label) :].strip() if cell_text.startswith(label) else cell_text
        href = link.attributes["href"]
        result.append(
            {
                "idi": query_param(href, "idi"),
                "kind": "interpelare" if label.startswith("Interpel") else "intrebare",
                "number": match.group(2) if match else None,
                "asked_on": parse_dotted_date(match.group(3)) if match else None,
                "title": title or None,
                "url": absolute(href if href.startswith("/") else "/ords/pls/parlam/" + href),
            }
        )
    return result


def parse_motions(page: str) -> list[dict]:
    result = []
    for row in html(page).css("table.video-table tbody tr"):
        cells = row.css("td")
        link = row.css_first("a")
        if link is None or len(cells) < 5:
            continue
        href = link.attributes.get("href", "")
        result.append(
            {
                "id": f"cd-{query_param(href, 'idm') or href}",
                "title": node_text(link).strip('"„”'),
                "initiators": node_text(cells[2]),
                "registered": node_text(cells[3]),
                "result": node_text(cells[4]) or None,
                "url": absolute(href),
            }
        )
    return result


MAX_SPEECH_PAGES = 30


def speech_pages(page: str) -> list[str]:
    """Links to the other result pages of a stenogram search, in order (`pags` is the first row index: 21, 41, ...)."""
    pages = {}
    for link in html(page).css("a"):
        href = link.attributes.get("href", "")
        number = query_param(href, "pags")
        if "steno2015.lista" in href and number and number.isdigit() and number != "1":
            pages[int(number)] = absolute(href)
    return [pages[number] for number in sorted(pages)][:MAX_SPEECH_PAGES]


def parse_speeches(page: str) -> list[dict]:
    """Stenogram search results: a sitting header row followed by one row per agenda point spoken on."""
    result, sitting, sitting_on, duration = [], None, None, None
    for row in html(page).css("tr"):
        cells = [cell for cell in row.iter() if cell.tag == "td"]
        if len(cells) >= 2 and "fef9c2" in (cells[1].attributes.get("bgcolor") or ""):
            bold = cells[1].css_first("b")
            sitting = node_text(bold) if bold else node_text(cells[1])
            sitting_on = parse_long_date(sitting)
            inner = [node_text(cell) for cell in cells[1].css("td")]
            duration = next((text for text in inner if re.fullmatch(r"\d+m\d+s|\d+h\d+m\d+s", text)), None)
        elif sitting and len(cells) >= 3 and "fffef2" in (cells[2].attributes.get("bgcolor") or ""):
            link = cells[1].css_first("a")
            result.append(
                {
                    "sitting": sitting,
                    "sitting_on": sitting_on,
                    "topic": node_text(cells[2]),
                    "duration": duration,
                    "url": absolute(link.attributes["href"]) if link else None,
                }
            )
    return result


def parse_declarations(page: str) -> list[dict]:
    """Interest/asset declaration PDFs linked from the profile sub-page (we link to them, we do not OCR them)."""
    result = []
    heading = next((node_text(h) for h in html(page).css("h3") if "Declara" in node_text(h)), "")
    kind = "avere" if "avere" in heading.lower() else "interese"
    filed = parse_dotted_date(heading)
    for link in html(page).css("a"):
        href = link.attributes.get("href", "")
        if href.lower().endswith(".pdf") and "/declaratii/" in href:
            result.append({"kind": kind, "filed_on": filed, "url": absolute(href)})
    return list({item["url"]: item for item in result}.values())


def store(conn: psycopg.Connection, member_id: str, data: dict) -> None:
    """Replace the member's lists present in `data`; shared with senat_activity (same tables, own ids)."""
    if "questions" in data:
        conn.execute("DELETE FROM questions WHERE member_id = %s", (member_id,))
        for item in data["questions"]:
            conn.execute(
                """INSERT INTO questions (id, member_id, kind, number, asked_on, title, recipient, answered, url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET member_id = EXCLUDED.member_id, title = EXCLUDED.title,
                       recipient = EXCLUDED.recipient, answered = EXCLUDED.answered""",
                (
                    item.get("id") or f"cd-{item['idi']}",
                    member_id,
                    item["kind"],
                    item["number"],
                    item["asked_on"],
                    item["title"],
                    item.get("recipient"),
                    item.get("answered"),
                    item["url"],
                ),
            )
    if "speeches" in data:
        conn.execute("DELETE FROM speeches WHERE member_id = %s", (member_id,))
        for seq, item in enumerate(data["speeches"]):
            conn.execute(
                """INSERT INTO speeches (member_id, seq, sitting, sitting_on, topic, duration, url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (member_id, seq, item["sitting"], item["sitting_on"], item["topic"], item["duration"], item["url"]),
            )
    if "motions" in data:
        conn.execute("DELETE FROM motion_signatures WHERE member_id = %s", (member_id,))
        for item in data["motions"]:
            conn.execute(
                """INSERT INTO motions (id, chamber, title, initiators, registered, result, url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET result = EXCLUDED.result""",
                (
                    item["id"],
                    item.get("chamber", "cd"),
                    item["title"],
                    item["initiators"],
                    item["registered"],
                    item["result"],
                    item["url"],
                ),
            )
            conn.execute(
                "INSERT INTO motion_signatures VALUES (%s, %s) ON CONFLICT DO NOTHING", (item["id"], member_id)
            )
    if "declarations" in data:
        for item in data["declarations"]:
            conn.execute(
                "INSERT INTO declarations VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (member_id, item["kind"], item["filed_on"], item["url"]),
            )


def ingest(
    conn: psycopg.Connection, fetcher: Fetcher, legislature: int, limit: int | None = None
) -> tuple[int, list[str]]:
    """Collect activity lists for every stored deputy; returns (deputies done, bill idps discovered)."""
    log = db.log_start(conn, SOURCE, f"activity cd {legislature}")
    deputies = conn.execute(
        """SELECT m.id, m.source_id, s.value AS speeches, s.url AS speeches_url,
                  coalesce(q.value, 0) AS questions, coalesce(mo.value, 0) AS motions, coalesce(b.value, 0) AS bills
           FROM members m
           LEFT JOIN member_stats s ON s.member_id = m.id AND s.metric = 'speeches'
           LEFT JOIN member_stats q ON q.member_id = m.id AND q.metric = 'questions'
           LEFT JOIN member_stats mo ON mo.member_id = m.id AND mo.metric = 'motions'
           LEFT JOIN member_stats b ON b.member_id = m.id AND b.metric = 'bills'
           WHERE m.chamber = 'cd' AND m.legislature = %s ORDER BY m.sort_name""",
        (legislature,),
    ).fetchall()
    count, idps, errors = 0, [], []
    for deputy in deputies[:limit] if limit else deputies:
        data: dict[str, list] = {}
        idm = deputy["source_id"]
        # Only open sub-pages the profile says are non-empty, to keep the request count low.
        pages = [
            (2, "initiatives", parse_initiatives, deputy["bills"]),
            (3, "questions", parse_questions, deputy["questions"]),
            (11, "motions", parse_motions, deputy["motions"]),
        ]
        try:
            for number, key, parser, expected in pages:
                if expected:
                    data[key] = parser(fetcher.get("cdep", subpage_url(idm, legislature, number)))
            if deputy["speeches"] and deputy["speeches_url"]:
                first = fetcher.get("cdep", deputy["speeches_url"])
                data["speeches"] = parse_speeches(first)
                for url in speech_pages(first):
                    data["speeches"].extend(parse_speeches(fetcher.get("cdep", url)))
        except (FetchError, ParseError) as error:
            errors.append(f"{deputy['id']}: {error}")
            continue
        idps.extend(item["idp"] for item in data.pop("initiatives", []))
        with conn.transaction():
            store(conn, deputy["id"], data)
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count, idps
