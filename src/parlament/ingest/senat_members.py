"""Senators from senat.ro: list, profile, current party/group, committees and activity counters.

senat.ro shows only the current party and group (no dated history) and loads detail lists through
ASP.NET postbacks; we use the counters printed on the profile page and do not replay postbacks.
"""

import re

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.ingest.cdep_members import Profile, store_cv, store_history
from parlament.parsing import ParseError, clean, fold, form_fields, html, node_text, parse_dotted_date, query_param

BASE = "https://www.senat.ro"
SOURCE = "senat.ro"
LIST_URL = f"{BASE}/FisaSenatori.aspx"

# Sidebar link text -> metric. Values are the numbers in brackets, e.g. 'Întrebări (3)'.
SIDEBAR = [
    (r"Ini[țţ]iative legislative \((\d+) din care (\d+) promulgate", ("bills", "laws")),
    (r"Declara[țţ]ii politice \((\d+)\)", ("political_statements",)),
    (r"Întrebări \((\d+)\)", ("questions",)),
    (r"Interpelări \((\d+)\)", ("interpellations",)),
    (r"Luări de cuvânt în plen \((\d+) în (\d+)", ("speeches", "speech_sessions_total")),
    (r"Mo[țţ]iuni \((\d+)\)", ("motions",)),
    (r"Votul electronic \((\d+) ședințe dintr-un total de (\d+)", ("vote_sessions", "vote_sessions_total")),
]


def member_id(legislature: int, guid: str) -> str:
    return f"senat-{legislature}-{guid.lower()}"


def profile_url(guid: str) -> str:
    return f"{BASE}/FisaSenator.aspx?ParlamentarID={guid.lower()}"


def constituency_name(name: str) -> str:
    """Constituency 43 is printed as 'Circumscripția electorală pentru românii cu domiciliul în afara României'."""
    name = name.strip(" -")
    return "Diaspora" if "afara" in name.lower() else name


def parse_senator_list(page: str) -> list[dict]:
    result, seen = [], set()
    # The page lists every senator twice (by group and alphabetically).
    for card in html(page).css("div.new-card-without-pics"):
        link = card.css_first("a")
        guid = query_param(link.attributes.get("href", ""), "ParlamentarID") if link else None
        if not guid or guid.lower() in seen:
            continue
        seen.add(guid.lower())
        lines = [node_text(p) for p in card.css("p")]
        place = next((line for line in lines if "Circumscrip" in line), "")
        match = re.search(r"nr\.\s*(\d+)\s+(.+)", place)
        result.append(
            {
                "guid": guid.lower(),
                "sort_name": node_text(link),
                "birth_date": parse_dotted_date(next((line for line in lines if "nasterii" in line), "")),
                "constituency_no": int(match.group(1)) if match else None,
                "constituency": constituency_name(match.group(2)) if match else None,
                "group_name": lines[-1] if lines else None,
            }
        )
    if not result:
        raise ParseError("senat.ro list: no senator cards found")
    return result


def parse_senator_profile(page: str) -> Profile:
    tree = html(page)
    heading = tree.css_first("div.senator-title-wrapper h2")
    if heading is None:
        raise ParseError("senat.ro profile: missing name heading")
    profile = Profile(name=node_text(heading))
    image = tree.css_first("div.senator-image-container img")
    if image is not None and image.attributes.get("src"):
        profile.photo_url = BASE + "/" + image.attributes["src"].replace("\\", "/").lstrip("/")
    details = tree.css_first("div.senator-details-container")
    if details is None:
        raise ParseError("senat.ro profile: missing details")
    elected = details.css_first("h5")
    if elected is not None:
        note = node_text(elected)
        profile.elected_note = note
        match = re.search(r"nr\.\s*(\d+)\s+(.+?)\s+în data", note)
        if match:
            profile.constituency_no, profile.constituency = int(match.group(1)), constituency_name(match.group(2))
        validated = re.search(r"validat în data de\s*([\d.]+)", note)
        profile.validated_on = parse_dotted_date(validated.group(1)) if validated else None
        ended = re.search(r"(?:încetat|incetat)\w*[^\d]*([\d.]+)", note, re.IGNORECASE)
        if ended:
            profile.mandate_end = parse_dotted_date(ended.group(1))
            profile.mandate_end_note = clean(ended.group(0))
    for wrapper in details.css("div.td-picture-wrapper"):
        text = node_text(wrapper)
        if text.startswith("Formațiunea politică:") or text.startswith("Formaţiunea politică:"):
            name = clean(text.split(":", 1)[1])
            profile.parties = [{"party": short_party(name), "party_name": name, "start": None, "end": None}]
        elif "Grupul parlamentar:" in text:
            link = wrapper.css_first("a")
            group_id = query_param(link.attributes.get("href", ""), "GrupID") if link else None
            profile.groups = [
                {
                    "group_source_id": group_id.lower() if group_id else None,
                    "group_name": clean(text.split(":", 1)[1]),
                    "start": None,
                    "end": None,
                }
            ]
    section = None
    for node in details.traverse():
        if node.tag == "h5":
            section = node_text(node).rstrip(":")
        elif node.tag == "tr" and section and (section.startswith("Comisii") or section == "Biroul permanent"):
            cells = node.css("td")
            link = node.css_first("a")
            if len(cells) < 2 or link is None:
                continue
            committee = query_param(link.attributes.get("href", ""), "ComisieID")
            role = re.match(r"(.+?), de la data de\s*([\d.]+)", node_text(cells[-1]))
            profile.committees.append(
                {
                    "source_id": (committee or "").lower(),
                    "name": node_text(link),
                    "role": role.group(1) if role else None,
                    "start": parse_dotted_date(role.group(2)) if role else None,
                    "kind": section.lower(),
                    "url": f"{BASE}/{link.attributes.get('href', '').lstrip('/')}",
                }
            )
    sidebar = " | ".join(node_text(item) for item in tree.css("ul.list-group li"))
    for pattern, metrics in SIDEBAR:
        match = re.search(pattern, sidebar)
        if match:
            for metric, value in zip(metrics, match.groups(), strict=True):
                profile.stats[metric] = (int(value), None)
    for mail in details.css('a[href^="mailto:"]'):
        address = mail.attributes["href"].removeprefix("mailto:").strip()
        if not address.startswith(("infopub@", "webmaster@")):
            profile.email = address
            break
    return profile


PARTY_SHORT = {
    "Partidul Social Democrat": "PSD",
    "Partidul Naţional Liberal": "PNL",
    "Partidul Național Liberal": "PNL",
    "Alianţa pentru Unirea Românilor": "AUR",
    "Alianța pentru Unirea Românilor": "AUR",
    "Uniunea Salvaţi România": "USR",
    "Uniunea Salvați România": "USR",
    "Uniunea Democrată Maghiară din România": "UDMR",
    "Partidul S.O.S. România": "SOS RO",
    "Partidul Oamenilor Tineri": "POT",
}


def short_party(name: str) -> str:
    return PARTY_SHORT.get(clean(name).replace("ș", "ş").replace("ț", "ţ"), PARTY_SHORT.get(clean(name), clean(name)))


def store_senator(conn: psycopg.Connection, legislature: int, listed: dict, profile: Profile) -> str:
    mid = member_id(legislature, listed["guid"])
    group = profile.groups[0] if profile.groups else None
    group_id = None
    if group and group["group_source_id"]:
        group_id = f"senat-{legislature}-{group['group_source_id']}"
        conn.execute(
            """INSERT INTO parl_groups (id, chamber, legislature, source_id, short_name, name, url)
               VALUES (%s, 'senat', %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, short_name = EXCLUDED.short_name""",
            (
                group_id,
                legislature,
                group["group_source_id"],
                group_short(group["group_name"]),
                group["group_name"],
                f"{BASE}/ComponentaGrupuri.aspx?GrupID={group['group_source_id']}",
            ),
        )
    party = profile.parties[0] if profile.parties else None
    conn.execute(
        """INSERT INTO members (id, chamber, legislature, source, source_id, name, sort_name, birth_date,
               photo_url, url,
               constituency_no, constituency, elected_note, group_id, party, party_name, validated_on, mandate_end,
               mandate_end_note, email, in_office, updated_at)
           VALUES (%s, 'senat', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, sort_name = EXCLUDED.sort_name,
               birth_date = EXCLUDED.birth_date, photo_url = EXCLUDED.photo_url,
                   constituency_no = EXCLUDED.constituency_no,
               constituency = EXCLUDED.constituency, elected_note = EXCLUDED.elected_note, group_id = EXCLUDED.group_id,
               party = EXCLUDED.party, party_name = EXCLUDED.party_name, validated_on = EXCLUDED.validated_on,
               mandate_end = EXCLUDED.mandate_end, mandate_end_note = EXCLUDED.mandate_end_note, email = EXCLUDED.email,
               in_office = EXCLUDED.in_office, updated_at = now()""",
        (
            mid,
            legislature,
            SOURCE,
            listed["guid"],
            profile.name,
            listed["sort_name"],
            listed["birth_date"],
            profile.photo_url,
            profile_url(listed["guid"]),
            profile.constituency_no or listed["constituency_no"],
            profile.constituency or listed["constituency"],
            profile.elected_note,
            group_id,
            party["party"] if party else None,
            party["party_name"] if party else None,
            profile.validated_on,
            profile.mandate_end,
            profile.mandate_end_note,
            profile.email,
            profile.mandate_end is None,
        ),
    )
    # senat.ro group ids are GUIDs; store_history derives the same '<chamber>-<leg>-<id>' key.
    store_history(conn, mid, "senat", legislature, profile)
    return mid


GROUP_SHORT = [
    ("Social Democrat", "PSD"),
    ("Național Liberal", "PNL"),
    ("Naţional Liberal", "PNL"),
    ("Unirea Românilor", "AUR"),
    ("Salvați România", "USR"),
    ("Salvaţi România", "USR"),
    ("Maghiare", "UDMR"),
    ("S.O.S", "SOS RO"),
    ("SOS", "SOS RO"),
    ("Oamenilor Tineri", "POT"),
    ("neafilia", "Neafiliați"),
    ("Minorit", "Minorități"),
]


def group_short(name: str) -> str:
    return next((short for needle, short in GROUP_SHORT if needle.lower() in name.lower()), name)


BIOGRAPHY = "ctl00$B_Center$Repeater14$ctl00$lnkBiog"
# Personal details the Senate prints with the CV that are not about the public role, or are shown elsewhere.
BIOGRAPHY_SKIP = ("nationalitate", "coordonate de contact")


def parse_biography(page: str) -> list[dict]:
    """The 'Biografie' view: sections (Experiență profesională, Educație și formare, ...) with labelled entries."""
    table = html(page).css_first("table.biografie-table")
    sections = []
    for row in _rows(table) if table is not None else []:
        cell = next((c for c in row.iter() if c.tag == "td"), None)
        # css() matches the node itself too, so the label table is reached through the bold wrapper.
        label = cell.css_first("b > table td") if cell is not None else None
        entries = []
        for inner in cell.css("table[id$=Fisa2]") if cell is not None else []:
            for line in _rows(inner):
                parts = [c for c in line.iter() if c.tag == "td"]
                if len(parts) < 2 or fold(node_text(parts[0])).startswith(BIOGRAPHY_SKIP):
                    continue
                text = "\n".join(clean(chunk) for chunk in re.split(r"<br\s*/?>", _inner_value(parts[1])))
                text = re.sub(r"\n{3,}", "\n\n", clean_tags(text)).strip()
                if text:
                    entries.append({"label": node_text(parts[0]), "text": text})
        if label is not None and entries:
            sections.append({"section": node_text(label), "entries": entries})
    return sections


def _rows(table) -> list:
    rows = []
    for child in table.iter():
        if child.tag == "tr":
            rows.append(child)
        elif child.tag == "tbody":
            rows.extend(r for r in child.iter() if r.tag == "tr")
    return rows


def _inner_value(cell) -> str:
    """The value cell holds a nested table whose last cell is the text."""
    cells = cell.css("td")
    value = (cells[-1] if cells else cell).html or ""
    # "Mai mult..." is a postback that opens the details of one entry; we keep what the page shows.
    return re.sub(r"<a\b[^>]*__doPostBack.*?</a>", "", value, flags=re.S)


def clean_tags(text: str) -> str:
    lines = [clean(html(f"<p>{line}</p>").css_first("p").text()) for line in text.split("\n")]
    return "\n".join(lines)


def ingest(conn: psycopg.Connection, fetcher: Fetcher, legislature: int, limit: int | None = None) -> int:
    log = db.log_start(conn, SOURCE, f"members senat {legislature}")
    listed = parse_senator_list(fetcher.get("senat", LIST_URL))
    count, errors = 0, []
    for senator in listed[:limit] if limit else listed:
        try:
            page = fetcher.get("senat", profile_url(senator["guid"]))
            profile = parse_senator_profile(page)
        except (FetchError, ParseError) as error:
            errors.append(str(error))
            continue
        with conn.transaction():
            mid = store_senator(conn, legislature, senator, profile)
        try:
            # The biography is a postback on the profile page ("Biografie" link).
            form = {**form_fields(page), "__EVENTTARGET": BIOGRAPHY, "__EVENTARGUMENT": ""}
            biography = parse_biography(fetcher.post("senat", profile_url(senator["guid"]), form, "biografie"))
            with conn.transaction():
                store_cv(conn, mid, biography, profile_url(senator["guid"]))
        except (FetchError, ParseError) as error:
            errors.append(f"{mid} biografie: {error}")
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
