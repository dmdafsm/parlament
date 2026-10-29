"""Deputies from cdep.ro: list, profile, group/party history, committees, activity counters and CV."""

import datetime as dt
import json
import re
from dataclasses import dataclass, field

import psycopg

from parlament import db
from parlament.config import CURRENT_LEGISLATURE
from parlament.fetch import Fetcher, FetchError
from parlament.parsing import (
    ParseError,
    block_text,
    clean,
    fold,
    html,
    node_text,
    parse_long_date,
    parse_month_label,
    query_param,
)

BASE = "https://www.cdep.ro"
# Since 2025 the Oracle applications are served under /ords (old /pls/... URLs return 404).
SITE = f"{BASE}/ords"
SOURCE = "cdep.ro"
CHAMBER_CODE = {"cd": "2", "senat": "1"}  # cdep.ro `cam` parameter

# Profile counters: label prefix on the page -> metric name.
# Profile counters: label (unaccented, lower case) prefix -> metric name.
# Checked in order; "Luari de cuvant in BP" (Standing Bureau sittings) must not count as plenary speeches.
STAT_LABELS = {
    "luari de cuvant in bp": None,
    "luari de cuvant": "speeches",
    "propuneri legislative initiate": "bills",
    "proiecte de hotarare initiate": "resolutions",
    "intrebari si interpelari": "questions",
    "motiuni": "motions",
    "declaratii politice": "political_statements",
}


def list_url(legislature: int) -> str:
    # Without `leg` the site lists the legislature in office; this is the URL its own menu links to.
    if legislature == CURRENT_LEGISLATURE:
        return f"{SITE}/pls/parlam/structura2015.de?idl=1"
    return f"{SITE}/pls/parlam/structura2015.de?leg={legislature}&idl=1"


def profile_url(idm: str, legislature: int, chamber: str = "cd") -> str:
    return f"{SITE}/pls/parlam/structura2015.mp?idm={idm}&cam={CHAMBER_CODE[chamber]}&leg={legislature}"


def cv_url(idm: str, legislature: int) -> str:
    """The profile's "Curriculum Vitae" view."""
    return f"{profile_url(idm, legislature)}&pag=0"


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
    """Titled boxes: `div.boxDep > h3` (layout until 2025) or `div.mp-info-box2025 > h4` (2025 redesign)."""
    sections = {}
    for box in tree.css("div.boxDep, div.mp-info-box2025"):
        title = box.css_first("h3, h4")
        if title is not None:
            sections[node_text(title).rstrip(":").lower()] = box
    return sections


def _parse_elected(profile: "Profile", body: str) -> None:
    """'ales deputat în circumscriptia electorala nr.35 SUCEAVA ... data validarii: 21 decembrie 2024 - HCD ...'."""
    profile.elected_note = re.split(r"data (?:valid|înceta|inceta)", body)[0].strip()
    match = re.search(r"nr\.\s*(\d+)\s+(.+?)(?:\s+pe listele|\s+data|$)", profile.elected_note)
    if match:
        profile.constituency_no = int(match.group(1))
        name = match.group(2).strip(" -")
        # Constituency 43 is printed as 'Circumscriptia ... cu domiciliul în afara tarii'.
        profile.constituency = "Diaspora" if "afara" in name.lower() else name.title()
    validated = re.search(r"data valid(?:ării|arii|ării?)?\w*:\s*([^-]+)", body, re.IGNORECASE)
    profile.validated_on = parse_long_date(validated.group(1)) if validated else None
    ended = re.search(r"data (?:încet|incet)\w* mandatului:\s*(.+)", body, re.IGNORECASE)
    if ended:
        profile.mandate_end = parse_long_date(ended.group(1))
        profile.mandate_end_note = clean(ended.group(1))


def parse_profile(page: str) -> Profile:
    tree = html(page)
    heading = tree.css_first("div.profile-dep h1, h1.mp-profile-name2025")
    if heading is None:
        raise ParseError("cdep profile: missing name heading")
    # Members of the Permanent Bureau have their office after a line break ('Ana POP<br>chestor al Camerei ...').
    profile = Profile(name=node_text(html(re.split(r"<br\s*/?>", heading.html or "", maxsplit=1)[0])))
    picture = tree.css_first("div.profile-pic-dep, div.mp-profile-photo2025")
    if picture is not None:
        image = picture.css_first("img")
        if image is not None and image.attributes.get("src"):
            profile.photo_url = absolute(image.attributes["src"])
    born_node = tree.css_first("div.profile-pic-dep, div.mp-contact-item2025")
    born = re.search(r"n\.\s*(.+)", node_text(born_node)) if born_node is not None else None
    profile.birth_date = parse_long_date(born.group(1)) if born else None
    details = tree.css_first("div.mp-profile-details2025 ul")
    if details is not None:
        _parse_elected(profile, " ".join(node_text(item) for item in details.css("li")))

    sections = _sections(tree)
    for title, box in sections.items():
        text = node_text(box)
        if title in ("deputat", "senator"):
            _parse_elected(profile, node_text(box.css_first("p")))
        elif title.startswith("formațiunea politică"):
            profile.parties = _parse_parties(box)
        elif title.startswith("organizația minorităților"):
            link = box.css_first("a")
            profile.minority_org = node_text(link) if link else text
        elif title.startswith("grupul parlamentar"):
            groups, profile.roles = _parse_groups(box)
            # The current group is listed first, earlier ones after it; order the history by date.
            profile.groups = sorted(groups, key=lambda g: (g["start"] or dt.date.min, g["end"] or dt.date.max))
        elif title.startswith("comisii"):
            profile.committees.extend(_parse_committees(box, title))
        elif title.startswith("activitatea parlamentar"):
            profile.stats = _parse_stats(box)
        elif title.startswith("biroul parlamentar"):
            profile.offices = clean(re.sub(r"^biroul parlamentar:?", "", text, flags=re.IGNORECASE))
    mail = tree.css_first(
        'div.profile-dep a[href^="mailto:"], div.boxDep a[href^="mailto:"], div.mp-profile-card2025 a[href^="mailto:"]'
    )
    if mail is not None:
        profile.email = mail.attributes["href"].removeprefix("mailto:").strip()
    return profile


def _parse_parties(box) -> list[dict]:
    """Rows link the party; the old layout shows 'PNL - Partidul Național Liberal', the 2025 one only the full name."""
    from parlament.ingest.senat_members import short_party

    parties = []
    for row in box.css("tr"):
        link = row.css_first("a")
        if link is None or len(row.css("tr")) > 1:  # css() includes the row itself; skip outer rows
            continue
        texts = [node_text(cell) for cell in row.iter() if cell.tag == "td"]
        label = node_text(link)
        if len(texts) >= 3 and "-" in texts:
            short, name = label, texts[texts.index("-") + 1]
        elif label.lower().startswith("fără adeziune"):
            short, name = label, None
        else:
            short, name = short_party(label), label
        last = texts[-1] if texts else ""
        period = parse_period(last) if ("din" in last or "până" in last) else Period(None, None)
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
    """Counters as table rows (until 2025) or as 'Label: value' lines separated by <br> (2025 redesign)."""
    lines = []
    rows = [row for row in box.css("tr") if len(row.css("td")) >= 2]
    if rows:
        lines = [(node_text(row.css("td")[0]), row.css("td")[1]) for row in rows]
    else:
        paragraph = box.css_first("p")
        for chunk in re.split(r"<br\s*/?>", paragraph.html if paragraph is not None else ""):
            node = html(f"<div>{chunk}</div>").css_first("div")
            label, _, _ = node_text(node).partition(":")
            lines.append((label, node))
    stats = {}
    for label, value_node in lines:
        key = fold(label.rstrip(":"))
        prefix = next((prefix for prefix in STAT_LABELS if key.startswith(prefix)), None)
        metric = STAT_LABELS.get(prefix)
        if metric is None:
            continue
        text = node_text(value_node)
        value_text = text.split(":", 1)[1] if ":" in text and rows == [] else text
        number = re.search(r"\d+", value_text)
        if number is None:
            continue
        link = value_node.css_first("a")
        stats[metric] = (int(number.group(0)), absolute(link.attributes["href"]) if link else None)
        sessions = re.search(r"în\s+(\d+)\s+ședințe", value_text)
        if sessions:
            stats["speech_sessions"] = (int(sessions.group(1)), None)
        laws = re.search(r"din care\s+(\d+)\s+promulgat", value_text)
        if laws:
            stats["laws"] = (int(laws.group(1)), None)
    return stats


# Personal details of the CV that are not about the public role are not stored (ADR 0001).
CV_SKIP_SECTIONS = ("informatii personale", "date personale", "date biografice", "date contact", "date de contact")
CV_SKIP_LABELS = (
    "data nasterii",
    "cetatenie",
    "nationalitate",
    "gen",
    "sex",
    "e-mail",
    "email",
    "telefon",
    "adresa",
    "facebook",
)
CV_BAND = re.compile(r'<div id="bandaCV(?:2025)?">(.*?)</div[^>]*>', re.S)
CV_TABLES = "table.cveuro2025, table.tbcveur2025"
# Some CVs are one table whose section headings are rows ('<h3 class="maj">Experienţa profesională</h3>' and an
# empty value cell); such a row is turned into a band so the sections split the same way.
CV_HEADING_ROW = re.compile(
    r'<tr>\s*<td class="colleft">\s*<h3 class="maj">(.*?)</h3>\s*</td>\s*<td[^>]*>\s*</td>\s*</tr>', re.S
)


def parse_cv(page: str) -> list[dict]:
    """The CV view, as [{"section": ..., "entries": [{"label": ..., "text": ...}]}] like the Senate biography.

    Deputies fill it in as Europass rows of label and value (two table styles and one of divs; one block per job
    or school, 'Perioada' first) or as free paragraphs and lists. Sections are the cdep.ro bands
    ('EXPERIENŢA PROFESIONALĂ', 'Studii şi specializări', ...).
    An empty list means the deputy has no CV on the site (some publish only the PDF)."""
    match = re.search(r'<div class="cv-content2025">(.*)', page, re.S)
    if match is None:
        return []
    # The content runs until the page's own "Right content end" marker; the footer comes after it.
    content = re.split(r'<!-- Right content end -->|<div id="footer"', match.group(1))[0]
    content = CV_HEADING_ROW.sub(r'</table><div id="bandaCV">\1</div><table class="tbcveur2025">', content)
    parts = CV_BAND.split(content)
    sections = []
    for title_html, body in zip(parts[1::2], parts[2::2], strict=True):
        title = clean(html(f"<div>{title_html}</div>").css_first("div").text()).capitalize()
        if not title or any(skip in fold(title) for skip in CV_SKIP_SECTIONS):
            continue
        tree = html(body)
        tables = tree.css(CV_TABLES)
        pairs = tree.css("div.cv-eu-pass-container2025")
        if tables:
            rows = [_cells([c for c in tr.iter() if c.tag == "td"]) for t in tables for tr in t.css("tr")]
            entries = _cv_rows(rows)
        elif pairs:
            entries = _cv_rows([_cells([c for c in pair.iter() if c.tag == "div"]) for pair in pairs])
        else:
            entries = _cv_paragraphs(tree)
        if entries:
            sections.append({"section": title, "entries": entries})
    return sections


def _cells(cells: list) -> list[str]:
    """Label on one line; values keep their lines (job title, period, one line per role)."""
    return [node_text(cells[0]), *(block_text(cell) for cell in cells[1:])] if cells else []


def _cv_rows(rows: list[list[str]]) -> list[dict]:
    """Rows of cell texts: label first, then the value(s)."""
    entries, block, header = [], [], []

    def close():
        if block and fold(block[0][0] or "").startswith("perioada"):
            entries.append({"label": block[0][1], "text": "\n".join(value for _, value in block[1:])})
        else:
            entries.extend({"label": label, "text": value} for label, value in block)
        block.clear()

    for cells in rows:
        if not cells:
            continue
        label = cells[0].rstrip(": ") or None
        values = cells[1:]
        if not label and not any(values):
            close()
        elif label and fold(label).startswith("perioada"):
            close()
            block.append((label, values[0] if values else ""))
        elif len(cells) > 2:
            # Language grid: a header row (no label) names the columns, then one row per language.
            if not label:
                header = values[1:]
            else:
                grades = ", ".join(
                    f"{name.lower()} {grade}" for name, grade in zip(header, values[1:], strict=False) if grade
                )
                block.append((label, grades))
        elif label and fold(label).startswith(CV_SKIP_LABELS):
            continue
        elif values and values[0]:
            block.append((label, values[0]))
    close()
    return entries


def _cv_paragraphs(tree) -> list[dict]:
    lines = [node_text(node) for node in tree.css("p, li")]
    text = "\n".join(line for line in lines if line and not fold(line).startswith(CV_SKIP_LABELS))
    return [{"label": None, "text": text}] if text else []


def store_cv(conn: psycopg.Connection, mid: str, sections: list[dict], url: str) -> None:
    conn.execute(
        "UPDATE members SET cv = %s, cv_url = %s WHERE id = %s",
        (json.dumps(sections, ensure_ascii=False) if sections else None, url, mid),
    )


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
                f"{SITE}/pls/parlam/structura2015.gp?idg={listed.group_source_id}&leg={legislature}",
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
        try:
            cv = parse_cv(fetcher.get("cdep", cv_url(deputy.idm, legislature)))
        except FetchError as error:
            errors.append(str(error))
            cv = None
        with conn.transaction():
            mid = store_deputy(conn, legislature, deputy, profile, url)
            if cv is not None:
                store_cv(conn, mid, cv, cv_url(deputy.idm, legislature))
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
