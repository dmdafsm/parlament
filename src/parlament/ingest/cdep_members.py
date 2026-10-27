"""Deputies from cdep.ro: list, profile, group/party history, committees and activity counters."""

import datetime as dt
import re
from dataclasses import dataclass, field

import psycopg

from parlament import db
from parlament.config import CURRENT_LEGISLATURE
from parlament.fetch import Fetcher, FetchError
from parlament.parsing import (
    ParseError,
    clean,
    html,
    int_or_none,
    node_text,
    parse_long_date,
    parse_month_label,
    query_param,
)

BASE = "https://www.cdep.ro"
SOURCE = "cdep.ro"
CHAMBER_CODE = {"cd": "2", "senat": "1"}  # cdep.ro `cam` parameter

# Profile counters: label prefix on the page -> metric name.
STAT_LABELS = {
    "luări de cuvânt": "speeches",
    "luari de cuvânt": "speeches",
    "propuneri legislative iniţiate": "bills",
    "propuneri legislative inițiate": "bills",
    "proiecte de hotarâre iniţiate": "resolutions",
    "proiecte de hotărâre inițiate": "resolutions",
    "întrebări şi interpelări": "questions",
    "întrebări și interpelări": "questions",
    "moţiuni": "motions",
    "moțiuni": "motions",
    "declaraţii politice": "political_statements",
    "declarații politice": "political_statements",
}


def list_url(legislature: int) -> str:
    # Without `leg` the site lists the legislature in office; this is the URL its own menu links to.
    if legislature == CURRENT_LEGISLATURE:
        return f"{BASE}/pls/parlam/structura2015.de?idl=1"
    return f"{BASE}/pls/parlam/structura2015.de?leg={legislature}&idl=1"


def profile_url(idm: str, legislature: int, chamber: str = "cd") -> str:
    return f"{BASE}/pls/parlam/structura2015.mp?idm={idm}&cam={CHAMBER_CODE[chamber]}&leg={legislature}"


def member_id(chamber: str, legislature: int, idm: str) -> str:
    return f"{chamber}-{legislature}-{idm}"


def member_ref_from_url(url: str) -> str | None:
    """'/pls/parlam/structura2015.mp?idm=273&leg=2020&cam=2' -> 'cd-2020-273'."""
    idm, leg, cam = query_param(url, "idm"), query_param(url, "leg"), query_param(url, "cam")
    if not (idm and leg and cam in ("1", "2")):
        return None
    return member_id("cd" if cam == "2" else "senat", int(leg), idm)


def absolute(url: str) -> str:
    return url if url.startswith("http") else BASE + url


@dataclass
class ListedDeputy:
    idm: str
    sort_name: str
    constituency_no: int | None
    constituency: str | None
    group_source_id: str | None
    group_short: str | None


def parse_deputy_list(page: str) -> list[ListedDeputy]:
    tree = html(page)
    result = []
    for row in tree.css("div.grup-parlamentar-list table tbody tr"):
        cells = row.css("td")
        link = cells[1].css_first("a") if len(cells) >= 4 else None
        if link is None or "structura2015.mp" not in (link.attributes.get("href") or ""):
            continue
        number = name = None
        place = cells[2].css_first("a")
        if place is not None:
            match = re.match(r"(\d+)\s*/\s*(.+)", node_text(place))
            if match:
                number, name = int(match.group(1)), match.group(2).title()
        group = cells[3].css_first("a")
        result.append(
            ListedDeputy(
                idm=query_param(link.attributes["href"], "idm"),
                sort_name=node_text(link),
                constituency_no=number,
                constituency=name,
                group_source_id=query_param(group.attributes["href"], "idg") if group else None,
                group_short=node_text(group) if group else None,
            )
        )
    if not result:
        raise ParseError("cdep deputy list: no rows found")
    return result


@dataclass
class Period:
    start: dt.date | None
    end: dt.date | None


def parse_period(text: str) -> Period:
    """'- membru din sep. 2023', '- până în feb. 2024', 'din sep. 2023 - până în feb. 2024'."""
    text = clean(text).lower()
    start = re.search(r"\bdin\s+([a-zăâî]+\.?\s+\d{4})", text)
    end = re.search(r"până în\s+([a-zăâî]+\.?\s+\d{4})", text)
    return Period(
        parse_month_label(start.group(1)) if start else None,
        parse_month_label(end.group(1)) if end else None,
    )


@dataclass
class Profile:
    name: str
    birth_date: dt.date | None = None
    photo_url: str | None = None
    elected_note: str | None = None
    constituency_no: int | None = None
    constituency: str | None = None
    validated_on: dt.date | None = None
    mandate_end: dt.date | None = None
    mandate_end_note: str | None = None
    minority_org: str | None = None
    parties: list[dict] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    committees: list[dict] = field(default_factory=list)
    stats: dict[str, tuple[int, str | None]] = field(default_factory=dict)
    offices: str | None = None
    email: str | None = None


def _sections(tree) -> dict[str, object]:
    sections = {}
    for box in tree.css("div.boxDep"):
        title = box.css_first("h3")
        if title is not None:
            sections[node_text(title).rstrip(":").lower()] = box
    return sections


def parse_profile(page: str) -> Profile:
    tree = html(page)
    heading = tree.css_first("div.profile-dep h1")
    if heading is None:
        raise ParseError("cdep profile: missing name heading")
    profile = Profile(name=node_text(heading))
    picture = tree.css_first("div.profile-pic-dep")
    if picture is not None:
        image = picture.css_first("img")
        if image is not None and image.attributes.get("src"):
            profile.photo_url = absolute(image.attributes["src"])
        born = re.search(r"n\.\s*(.+)", node_text(picture))
        profile.birth_date = parse_long_date(born.group(1)) if born else None

    sections = _sections(tree)
    for title, box in sections.items():
        text = node_text(box)
        if title in ("deputat", "senator"):
            body = node_text(box.css_first("p"))
            profile.elected_note = re.split(r"data (?:valid|înceta|inceta)", body)[0].strip()
            match = re.search(r"nr\.\s*(\d+)\s+(.+?)(?:\s+pe listele|\s+data|$)", profile.elected_note)
            if match:
                profile.constituency_no = int(match.group(1))
                profile.constituency = match.group(2).strip().title()
            validated = re.search(r"data validării?:\s*([^-]+)", body, re.IGNORECASE) or re.search(
                r"data validarii:\s*([^-]+)", body
            )
            profile.validated_on = parse_long_date(validated.group(1)) if validated else None
            ended = re.search(r"data (?:încet|incet)\w* mandatului:\s*(.+)", body, re.IGNORECASE)
            if ended:
                profile.mandate_end = parse_long_date(ended.group(1))
                profile.mandate_end_note = clean(ended.group(1))
        elif title.startswith("formaţiunea politică") or title.startswith("formațiunea politică"):
            profile.parties = _parse_parties(box)
        elif title.startswith("organizaţia minorităţilor") or title.startswith("organizația minorităților"):
            link = box.css_first("a")
            profile.minority_org = node_text(link) if link else text
        elif title.startswith("grupul parlamentar"):
            groups, profile.roles = _parse_groups(box)
            # The current group is listed first, earlier ones after it; order the history by date.
            profile.groups = sorted(groups, key=lambda g: (g["start"] or dt.date.min, g["end"] or dt.date.max))
        elif title.startswith("comisii") or title.startswith("delegaţii") or title.startswith("delegații"):
            profile.committees.extend(_parse_committees(box, title))
        elif title.startswith("activitatea parlamentar"):
            profile.stats = _parse_stats(box)
        elif title.startswith("biroul parlamentar"):
            profile.offices = clean(re.sub(r"^biroul parlamentar:?", "", text, flags=re.IGNORECASE))
    mail = tree.css_first('div.profile-dep a[href^="mailto:"], div.boxDep a[href^="mailto:"]')
    if mail is not None:
        profile.email = mail.attributes["href"].removeprefix("mailto:").strip()
    return profile


def _parse_parties(box) -> list[dict]:
    parties = []
    for inner in box.css("table table tr"):
        cells = inner.css("td")
        link = inner.css_first("a")
        if link is None:
            continue
        short = node_text(link)
        texts = [node_text(cell) for cell in cells]
        name = texts[2] if len(texts) >= 3 and texts[1] == "-" else None
        period = (
            parse_period(texts[-1]) if texts and ("din" in texts[-1] or "până" in texts[-1]) else Period(None, None)
        )
        parties.append({"party": short, "party_name": name, "start": period.start, "end": period.end})
    return parties


def _parse_groups(box) -> tuple[list[dict], list[dict]]:
    groups, roles = [], []
    current = None
    for row in box.css("tr"):
        cells = row.css("td")
        if not cells:
            continue
        link = cells[0].css_first("a")
        rest = cells
        if link is not None and "structura2015.gp" in (link.attributes.get("href") or ""):
            current = node_text(link)
            period = parse_period(node_text(cells[1])) if len(cells) > 1 else Period(None, None)
            groups.append(
                {
                    "group_source_id": query_param(link.attributes["href"], "idg"),
                    "group_name": current,
                    "start": period.start,
                    "end": period.end,
                }
            )
            rest = cells[2:]
        else:
            rest = cells[1:]
        texts = [node_text(cell) for cell in rest]
        texts = [text for text in texts if text]
        if current and texts and not texts[0].startswith("-"):
            period = parse_period(" ".join(texts[1:]))
            roles.append({"group_name": current, "role": texts[0], "start": period.start, "end": period.end})
    return groups, roles


def _parse_committees(box, title: str) -> list[dict]:
    result = []
    for link in box.css("a"):
        href = link.attributes.get("href") or ""
        if "structura2015.co" not in href:
            continue
        role = None
        sibling = link.next
        if sibling is not None and sibling.tag == "-text":
            match = re.search(r"-\s*([^\n]+)", sibling.text())
            role = clean(match.group(1)) if match else None
        result.append(
            {
                "source_id": query_param(href, "idc"),
                "name": node_text(link),
                "role": role,
                "kind": title,
                "url": absolute(href),
            }
        )
    return result


def _parse_stats(box) -> dict[str, tuple[int, str | None]]:
    stats = {}
    for row in box.css("tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        label = node_text(cells[0]).rstrip(":").strip().lower()
        metric = next((name for prefix, name in STAT_LABELS.items() if label.startswith(prefix)), None)
        if metric is None:
            continue
        bold = cells[1].css_first("b")
        value = int_or_none(node_text(bold)) if bold else None
        if value is None:
            continue
        link = cells[1].css_first("a")
        stats[metric] = (value, absolute(link.attributes["href"]) if link else None)
        sessions = re.search(r"în\s+(\d+)\s+şedinţe|în\s+(\d+)\s+ședințe", node_text(cells[1]))
        if sessions:
            stats["speech_sessions"] = (int(sessions.group(1) or sessions.group(2)), None)
    return stats


def display_name(sort_name: str) -> str:
    """cdep.ro list names are 'Surname Given'; profile headings are 'Given SURNAME'. Prefer the heading."""
    return sort_name


def store_deputy(conn: psycopg.Connection, legislature: int, listed: ListedDeputy, profile: Profile, url: str) -> str:
    mid = member_id("cd", legislature, listed.idm)
    group_id = None
    if listed.group_source_id is not None:
        group_id = f"cd-{legislature}-{listed.group_source_id}"
        conn.execute(
            """INSERT INTO parl_groups (id, chamber, legislature, source_id, short_name, name, url)
               VALUES (%s, 'cd', %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET short_name = EXCLUDED.short_name""",
            (
                group_id,
                legislature,
                listed.group_source_id,
                listed.group_short,
                listed.group_short,
                f"{BASE}/pls/parlam/structura2015.gp?idg={listed.group_source_id}&leg={legislature}",
            ),
        )
    current_party = next(
        (p for p in profile.parties if p["end"] is None), profile.parties[-1] if profile.parties else None
    )
    conn.execute(
        """INSERT INTO members (id, chamber, legislature, source, source_id, name, sort_name, birth_date,
               photo_url, url,
               constituency_no, constituency, elected_note, group_id, party, party_name, minority_org, validated_on,
               mandate_end, mandate_end_note, offices, email, in_office, updated_at)
           VALUES (%s, 'cd', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, sort_name = EXCLUDED.sort_name,
               birth_date = EXCLUDED.birth_date, photo_url = EXCLUDED.photo_url, url = EXCLUDED.url,
               constituency_no = EXCLUDED.constituency_no, constituency = EXCLUDED.constituency,
               elected_note = EXCLUDED.elected_note, group_id = EXCLUDED.group_id, party = EXCLUDED.party,
               party_name = EXCLUDED.party_name, minority_org = EXCLUDED.minority_org,
               validated_on = EXCLUDED.validated_on, mandate_end = EXCLUDED.mandate_end,
               mandate_end_note = EXCLUDED.mandate_end_note, offices = EXCLUDED.offices, email = EXCLUDED.email,
               in_office = EXCLUDED.in_office, updated_at = now()""",
        (
            mid,
            legislature,
            SOURCE,
            listed.idm,
            profile.name,
            listed.sort_name,
            profile.birth_date,
            profile.photo_url,
            url,
            profile.constituency_no if profile.constituency_no is not None else listed.constituency_no,
            profile.constituency or listed.constituency,
            profile.elected_note,
            group_id,
            current_party["party"] if current_party else None,
            current_party["party_name"] if current_party else None,
            profile.minority_org,
            profile.validated_on,
            profile.mandate_end,
            profile.mandate_end_note,
            profile.offices,
            profile.email,
            profile.mandate_end is None,
        ),
    )
    store_history(conn, mid, "cd", legislature, profile)
    return mid


def store_history(conn: psycopg.Connection, mid: str, chamber: str, legislature: int, profile: Profile) -> None:
    """Delete-and-replace the member's history rows from the latest profile."""
    for table in ("group_memberships", "party_memberships", "group_roles", "committee_memberships", "member_stats"):
        conn.execute(f"DELETE FROM {table} WHERE member_id = %s", (mid,))
    for seq, group in enumerate(profile.groups):
        gid = None
        if group.get("group_source_id") is not None:
            gid = f"{chamber}-{legislature}-{group['group_source_id']}"
            conn.execute(
                """INSERT INTO parl_groups (id, chamber, legislature, source_id, name)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name""",
                (gid, chamber, legislature, group["group_source_id"], group["group_name"]),
            )
        conn.execute(
            "INSERT INTO group_memberships VALUES (%s, %s, %s, %s, %s, %s, 'month')",
            (mid, seq, gid, group["group_name"], group["start"], group["end"]),
        )
    for seq, party in enumerate(profile.parties):
        conn.execute(
            "INSERT INTO party_memberships VALUES (%s, %s, %s, %s, %s, %s, 'month')",
            (mid, seq, party["party"], party["party_name"], party["start"], party["end"]),
        )
    for seq, role in enumerate(profile.roles):
        conn.execute(
            "INSERT INTO group_roles VALUES (%s, %s, %s, %s, %s, %s)",
            (mid, seq, role["group_name"], role["role"], role["start"], role["end"]),
        )
    for committee in profile.committees:
        cid = f"{chamber}-{legislature}-c{committee['source_id']}"
        conn.execute(
            """INSERT INTO committees (id, chamber, legislature, name, url) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name""",
            (cid, chamber, legislature, committee["name"], committee["url"]),
        )
        conn.execute(
            """INSERT INTO committee_memberships (member_id, committee_id, role, start_date) VALUES (%s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            (mid, cid, committee["role"], committee.get("start")),
        )
    for metric, (value, url) in profile.stats.items():
        conn.execute(
            "INSERT INTO member_stats (member_id, metric, value, url) VALUES (%s, %s, %s, %s)",
            (mid, metric, value, url),
        )


def ingest(conn: psycopg.Connection, fetcher: Fetcher, legislature: int, limit: int | None = None) -> int:
    log = db.log_start(conn, SOURCE, f"members cd {legislature}")
    count, errors = 0, []
    listed = parse_deputy_list(fetcher.get("cdep", list_url(legislature)))
    for deputy in listed[:limit] if limit else listed:
        url = profile_url(deputy.idm, legislature)
        try:
            profile = parse_profile(fetcher.get("cdep", url))
        except (FetchError, ParseError) as error:
            # Keep the deputy from the list row (name, constituency, group); the profile is retried next run.
            errors.append(str(error))
            profile = Profile(name=deputy.sort_name)
            if deputy.group_source_id is not None:
                profile.groups = [
                    {
                        "group_source_id": deputy.group_source_id,
                        "group_name": deputy.group_short,
                        "start": None,
                        "end": None,
                    }
                ]
        with conn.transaction():
            store_deputy(conn, legislature, deputy, profile, url)
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
