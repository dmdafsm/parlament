"""Derived indicators. All numbers shown on the site and in the API come from these queries.

Definitions (also on the methodology page):
- Vote attendance: share of the chamber's nominal, non-test votes held while the MP was in office at which the MP
  is listed as present (both chambers). A vote without a published nominal list is not counted. Senators without
  any collected nominal vote fall back to the session counts senat.ro prints on the profile.
- Party-line loyalty: among votes where the MP voted yes/no/abstain and their group (as printed on the vote)
  had a strict majority option among its present members, the share that matches that option. Unaffiliated
  MPs have no group line and get no loyalty score.
"""

import re

import psycopg

from parlament.parsing import fold

STOPWORDS = {"si", "de", "la", "in", "cu", "pe", "pentru", "privind", "a", "al", "ale", "din", "sau", "lege", "legea"}


def ts_query(text: str) -> str | None:
    """'ordonanța de urgență' -> 'ordona:* & urgen:*' for to_tsquery('simple', ...).

    Words are unaccented and cut to a prefix so inflected forms match (ordonanța/ordonanței/ordonanțe).
    """
    terms = []
    for word in re.findall(r"[a-z0-9]+", fold(text)):
        if word in STOPWORDS or (len(word) < 3 and not word.isdigit()):
            continue
        cut = word if word.isdigit() or len(word) <= 4 else word[: max(4, len(word) - 2)]
        terms.append(f"{cut}:*")
    return " & ".join(dict.fromkeys(terms)) or None


MEMBER_OVERVIEW = """
WITH vote_window AS (
    SELECT m.id AS member_id, count(v.id) AS eligible
    FROM members m
    JOIN votes v ON v.chamber = m.chamber AND v.has_nominal AND NOT v.is_test
         AND v.voted_at::date >= coalesce(m.validated_on, make_date(m.legislature, 12, 1))
         AND (m.mandate_end IS NULL OR v.voted_at::date <= m.mandate_end)
         -- A mandate of an earlier legislature with no end date ends when the next legislature starts.
         AND v.voted_at::date < coalesce((SELECT min(n.validated_on) FROM members n
                                          WHERE n.chamber = m.chamber AND n.legislature = m.legislature + 4),
                                         'infinity'::date)
    GROUP BY m.id
),
present AS (
    SELECT r.member_id, count(*) AS present,
           count(*) FILTER (WHERE r.choice = 'yes') AS yes,
           count(*) FILTER (WHERE r.choice = 'no') AS no,
           count(*) FILTER (WHERE r.choice = 'abstain') AS abstain
    FROM vote_records r JOIN votes v ON v.id = r.vote_id AND NOT v.is_test
    GROUP BY r.member_id
),
group_line AS (
    SELECT vote_id, group_code, choice
    FROM (
        SELECT vote_id, group_code, choice, count(*) AS n,
               sum(count(*)) OVER (PARTITION BY vote_id, group_code) AS total,
               rank() OVER (PARTITION BY vote_id, group_code ORDER BY count(*) DESC) AS rnk
        FROM vote_records
        WHERE choice IN ('yes', 'no', 'abstain') AND group_code NOT ILIKE 'neafilia%%'
        GROUP BY vote_id, group_code, choice
    ) ranked
    WHERE rnk = 1 AND n * 2 > total
),
loyalty AS (
    SELECT r.member_id, count(*) AS considered, count(*) FILTER (WHERE r.choice = g.choice) AS loyal
    FROM vote_records r
    JOIN group_line g ON g.vote_id = r.vote_id AND g.group_code = r.group_code
    WHERE r.choice IN ('yes', 'no', 'abstain')
    GROUP BY r.member_id
),
stats AS (
    SELECT member_id,
           max(value) FILTER (WHERE metric = 'speeches') AS speeches,
           max(value) FILTER (WHERE metric = 'bills') AS bills,
           max(value) FILTER (WHERE metric = 'laws') AS laws,
           max(value) FILTER (WHERE metric = 'questions') AS questions_stat,
           max(value) FILTER (WHERE metric = 'interpellations') AS interpellations,
           max(value) FILTER (WHERE metric = 'motions') AS motions,
           max(value) FILTER (WHERE metric = 'political_statements') AS statements,
           max(value) FILTER (WHERE metric = 'vote_sessions') AS vote_sessions,
           max(value) FILTER (WHERE metric = 'vote_sessions_total') AS vote_sessions_total
    FROM member_stats GROUP BY member_id
),
switches AS (
    SELECT member_id, count(*) - 1 AS group_changes FROM group_memberships GROUP BY member_id
),
party_switches AS (
    SELECT member_id, count(*) - 1 AS party_changes FROM party_memberships GROUP BY member_id
)
SELECT m.id, m.chamber, m.legislature, m.name, m.sort_name, m.photo_url, m.constituency_no, m.constituency,
       m.party, m.in_office, m.minority_org, g.id AS group_id, g.short_name AS group_short, g.name AS group_name,
       -- No counters at all means the profile was not collected: unknown, not zero.
       CASE WHEN s.member_id IS NOT NULL THEN coalesce(s.speeches, 0) END AS speeches,
       CASE WHEN s.member_id IS NOT NULL THEN coalesce(s.bills, 0) END AS bills,
       s.laws,
       CASE WHEN s.member_id IS NOT NULL
            THEN coalesce(s.questions_stat, 0) + coalesce(s.interpellations, 0) END AS questions,
       CASE WHEN s.member_id IS NOT NULL THEN coalesce(s.motions, 0) END AS motions,
       CASE WHEN s.member_id IS NOT NULL THEN coalesce(s.statements, 0) END AS statements,
       CASE WHEN w.eligible > 0 THEN w.eligible ELSE s.vote_sessions_total END AS attendance_base,
       CASE WHEN w.eligible > 0 THEN coalesce(p.present, 0) ELSE s.vote_sessions END AS attendance_present,
       CASE WHEN w.eligible > 0 THEN round(coalesce(p.present, 0)::numeric / w.eligible, 4)
            ELSE round(s.vote_sessions::numeric / nullif(s.vote_sessions_total, 0), 4) END AS attendance,
       CASE WHEN w.eligible > 0 THEN 'vote' WHEN s.vote_sessions_total > 0 THEN 'session' END AS attendance_unit,
       p.yes, p.no, p.abstain,
       l.considered AS loyalty_base,
       round(l.loyal::numeric / nullif(l.considered, 0), 4) AS loyalty,
       coalesce(sw.group_changes, 0) AS group_changes,
       coalesce(ps.party_changes, 0) AS party_changes
FROM members m
LEFT JOIN parl_groups g ON g.id = m.group_id
LEFT JOIN stats s ON s.member_id = m.id
LEFT JOIN vote_window w ON w.member_id = m.id
LEFT JOIN present p ON p.member_id = m.id
LEFT JOIN loyalty l ON l.member_id = m.id
LEFT JOIN switches sw ON sw.member_id = m.id
LEFT JOIN party_switches ps ON ps.member_id = m.id
"""

SORTS = {
    "nume": "sort_name",
    "luari": "speeches DESC NULLS LAST, sort_name",
    "initiative": "bills DESC NULLS LAST, sort_name",
    "intrebari": "questions DESC NULLS LAST, sort_name",
    "motiuni": "motions DESC NULLS LAST, sort_name",
    "prezenta": "attendance DESC NULLS LAST, sort_name",
    "absente": "attendance ASC NULLS LAST, sort_name",
    "loialitate": "loyalty ASC NULLS LAST, sort_name",
    "traseism": "group_changes + party_changes DESC, sort_name",
}


def members(
    conn: psycopg.Connection,
    legislature: int,
    chamber: str | None = None,
    sort: str = "nume",
    query: str | None = None,
    group: str | None = None,
    constituency: int | None = None,
    in_office: bool = True,
) -> list[dict]:
    where, params = ["legislature = %(leg)s"], {"leg": legislature}
    if chamber in ("cd", "senat"):
        where.append("chamber = %(chamber)s")
        params["chamber"] = chamber
    if in_office:
        where.append("in_office")
    if query:
        where.append("f_unaccent(name) ILIKE f_unaccent(%(q)s)")
        params["q"] = f"%{query}%"
    if group:
        where.append("group_short = %(group)s")
        params["group"] = group
    if constituency is not None:
        where.append("constituency_no = %(cir)s")
        params["cir"] = constituency
    order = SORTS.get(sort, SORTS["nume"])
    sql = f"SELECT * FROM ({MEMBER_OVERVIEW}) o WHERE {' AND '.join(where)} ORDER BY {order}"
    return conn.execute(sql, params).fetchall()


def legislatures(conn: psycopg.Connection) -> list[int]:
    """Legislatures with MPs in the database, newest first."""
    return [row["legislature"] for row in conn.execute("SELECT DISTINCT legislature FROM members ORDER BY 1 DESC")]


def mandates(conn: psycopg.Connection, member_id: str) -> list[dict]:
    """The same person's mandates in other legislatures or the other chamber: same name (folded), and same birth
    date when both records have one. Ids differ between legislatures, so the name is the only common key."""
    return conn.execute(
        """SELECT o.id, o.chamber, o.legislature FROM members m JOIN members o
               ON o.id <> m.id AND lower(f_unaccent(o.sort_name)) = lower(f_unaccent(m.sort_name))
                  AND (o.birth_date IS NULL OR m.birth_date IS NULL OR o.birth_date = m.birth_date)
           WHERE m.id = %s ORDER BY o.legislature DESC, o.chamber""",
        (member_id,),
    ).fetchall()


def member(conn: psycopg.Connection, member_id: str) -> dict | None:
    return conn.execute(f"SELECT * FROM ({MEMBER_OVERVIEW}) o WHERE id = %s", (member_id,)).fetchone()


def chamber_medians(conn: psycopg.Connection, legislature: int) -> dict[str, dict]:
    rows = conn.execute(
        f"""SELECT chamber,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY attendance) AS attendance,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY loyalty) AS loyalty,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY speeches) AS speeches,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY bills) AS bills,
                   count(*) AS members
            FROM ({MEMBER_OVERVIEW}) o WHERE legislature = %s AND in_office GROUP BY chamber""",
        (legislature,),
    ).fetchall()
    return {row["chamber"]: row for row in rows}


def group_summary(conn: psycopg.Connection, legislature: int) -> list[dict]:
    return conn.execute(
        f"""SELECT chamber, coalesce(group_short, 'Fără grup') AS group_short, count(*) AS members,
                   round(avg(attendance), 4) AS attendance, round(avg(loyalty), 4) AS loyalty,
                   sum(bills) AS bills, sum(speeches) AS speeches, sum(questions) AS questions
            FROM ({MEMBER_OVERVIEW}) o WHERE legislature = %s AND in_office
            GROUP BY chamber, group_short ORDER BY chamber, count(*) DESC""",
        (legislature,),
    ).fetchall()


def group_flows(conn: psycopg.Connection, legislature: int) -> list[dict]:
    """Group at the start of the mandate -> current group, for members who changed groups."""
    return conn.execute(
        """WITH ordered AS (
               SELECT gm.member_id, gm.group_name, m.chamber,
                      row_number() OVER (PARTITION BY gm.member_id ORDER BY gm.start_date NULLS FIRST,
                          gm.seq) AS first_rank,
                      row_number() OVER (PARTITION BY gm.member_id ORDER BY gm.end_date DESC NULLS FIRST,
                          gm.seq DESC) AS last_rank,
                      count(*) OVER (PARTITION BY gm.member_id) AS n
               FROM group_memberships gm JOIN members m ON m.id = gm.member_id
               WHERE m.legislature = %s
           )
           SELECT f.chamber, f.group_name AS from_group, l.group_name AS to_group, count(*) AS members
           FROM ordered f JOIN ordered l ON l.member_id = f.member_id AND l.last_rank = 1
           WHERE f.first_rank = 1 AND f.n > 1 AND f.group_name <> l.group_name
           GROUP BY f.chamber, f.group_name, l.group_name ORDER BY count(*) DESC""",
        (legislature,),
    ).fetchall()


def switchers(conn: psycopg.Connection, legislature: int) -> list[dict]:
    return conn.execute(
        f"""SELECT * FROM ({MEMBER_OVERVIEW}) o
            WHERE legislature = %s AND (group_changes > 0 OR party_changes > 0)
            ORDER BY group_changes + party_changes DESC, sort_name""",
        (legislature,),
    ).fetchall()


def member_votes(conn: psycopg.Connection, member_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    return conn.execute(
        """WITH line AS (
               SELECT vote_id, group_code, choice FROM (
                   SELECT vote_id, group_code, choice, count(*) AS n,
                          sum(count(*)) OVER (PARTITION BY vote_id, group_code) AS total,
                          rank() OVER (PARTITION BY vote_id, group_code ORDER BY count(*) DESC) AS rnk
                   FROM vote_records WHERE choice IN ('yes', 'no', 'abstain') GROUP BY vote_id, group_code, choice
               ) x WHERE rnk = 1 AND n * 2 > total
           )
           SELECT v.id, v.voted_at, v.description, v.bill_id, v.bill_ref, r.choice, r.group_code,
                  l.choice AS group_choice,
                  (l.choice IS NOT NULL AND r.choice IN ('yes', 'no', 'abstain') AND r.choice <> l.choice
                   AND r.group_code NOT ILIKE 'neafilia%%') AS against_group
           FROM vote_records r JOIN votes v ON v.id = r.vote_id
           LEFT JOIN line l ON l.vote_id = r.vote_id AND l.group_code = r.group_code
           WHERE r.member_id = %s ORDER BY v.voted_at DESC, v.seq DESC NULLS LAST LIMIT %s OFFSET %s""",
        (member_id, limit, offset),
    ).fetchall()


def vote_breakdown(conn: psycopg.Connection, vote_id: str) -> list[dict]:
    return conn.execute(
        """SELECT group_code,
                  count(*) FILTER (WHERE choice = 'yes') AS yes,
                  count(*) FILTER (WHERE choice = 'no') AS no,
                  count(*) FILTER (WHERE choice = 'abstain') AS abstain,
                  count(*) FILTER (WHERE choice = 'present_not_voting') AS present_not_voting,
                  count(*) AS present
           FROM vote_records WHERE vote_id = %s GROUP BY group_code ORDER BY count(*) DESC""",
        (vote_id,),
    ).fetchall()


def bill_stage(bill: dict) -> str:
    """Coarse stage for filters, derived from the published status text."""
    status = (bill.get("status") or "").lower()
    if bill.get("law"):
        return "lege"
    if "respins" in status:
        return "respins"
    if "retras" in status or "clasat" in status:
        return "retras"
    if "promulgare" in status:
        return "la promulgare"
    if "ccr" in status or "constitu" in status:
        return "la CCR"
    return "în dezbatere"


STAGE_SQL = """CASE WHEN law IS NOT NULL THEN 'lege'
                    WHEN status ILIKE '%%respins%%' THEN 'respins'
                    WHEN status ILIKE '%%retras%%' OR status ILIKE '%%clasat%%' THEN 'retras'
                    WHEN status ILIKE '%%promulgare%%' THEN 'la promulgare'
                    WHEN status ILIKE '%%ccr%%' OR status ILIKE '%%constitu%%' THEN 'la CCR'
                    ELSE 'în dezbatere' END"""


# A bill in both chambers has one page, the cdep.ro one; Senate records of such bills are not listed separately.
ONE_PAGE_PER_BILL = """NOT (chamber = 'senat' AND senate_key IN (
    SELECT senate_key FROM bills WHERE chamber = 'cd' AND senate_key IS NOT NULL))"""


def bills(
    conn: psycopg.Connection,
    query: str | None = None,
    stage: str | None = None,
    ordinance: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    where, params = [ONE_PAGE_PER_BILL], {"limit": limit, "offset": offset}
    if query:
        where.append("(search @@ to_tsquery('simple', %(q)s) OR number ILIKE %(like)s OR senate_number ILIKE %(like)s)")
        params["q"] = ts_query(query) or "''"
        params["like"] = f"%{query.strip()}%"
    if stage:
        where.append(f"{STAGE_SQL} = %(stage)s")
        params["stage"] = stage
    if ordinance:
        where.append("ordinance IS NOT NULL")
    sql = f"""SELECT id, chamber, number, senate_number, title, kind, status, law, ordinance, urgent, registered_on,
                  last_event_on,
                     initiator_summary, {STAGE_SQL} AS stage,
                     CASE WHEN law IS NOT NULL THEN last_event_on - registered_on END AS days_to_law
              FROM bills WHERE {" AND ".join(where)}
              ORDER BY last_event_on DESC NULLS LAST, id DESC LIMIT %(limit)s OFFSET %(offset)s"""
    return conn.execute(sql, params).fetchall()


def bill_stage_counts(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        f"SELECT {STAGE_SQL} AS stage, count(*) AS n FROM bills WHERE {ONE_PAGE_PER_BILL} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()


def ordinance_stats(conn: psycopg.Connection) -> dict:
    return conn.execute(
        f"""SELECT count(*) AS total,
                   count(*) FILTER (WHERE law IS NOT NULL) AS approved_by_law,
                   count(*) FILTER (WHERE {STAGE_SQL} = 'în dezbatere') AS pending,
                   round(avg(last_event_on - registered_on) FILTER (WHERE law IS NOT NULL)) AS avg_days,
                   count(*) FILTER (WHERE ordinance LIKE 'OUG%%') AS emergency
            FROM bills WHERE ordinance IS NOT NULL"""
    ).fetchone()


def ccr_events(conn: psycopg.Connection, limit: int = 100) -> list[dict]:
    """Procedure steps mentioning the Constitutional Court (referrals and decisions)."""
    return conn.execute(
        """SELECT e.bill_id, b.number, b.title, e.event_date, e.action, e.notes
           FROM bill_events e JOIN bills b ON b.id = e.bill_id
           WHERE e.action ILIKE '%%Curtea Constitu%%' OR e.action ILIKE '%%CCR%%' OR e.notes ILIKE '%%Curtea Constitu%%'
           ORDER BY e.event_date DESC NULLS LAST LIMIT %s""",
        (limit,),
    ).fetchall()


def tacit_adoptions(conn: psycopg.Connection, limit: int = 100) -> list[dict]:
    """Bills adopted tacitly (the first chamber missed the constitutional deadline, art. 75(2))."""
    return conn.execute(
        """SELECT DISTINCT ON (b.id) b.id, b.number, b.title, e.event_date, e.action
           FROM bills b JOIN bill_events e ON e.bill_id = b.id
           WHERE e.action ILIKE '%%tacit%%' OR e.notes ILIKE '%%tacit%%' OR e.notes ILIKE '%%art.75%%alin.(2)%%teza%%'
           ORDER BY b.id, e.event_date DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def snippet(text: str, query: str, words: int = 14) -> list[tuple[str, bool]]:
    """A window of `text` around the first word matching `query` (same prefixes as ts_query), as
    (text, is_match) pieces for the template to mark without building HTML."""
    prefixes = [term.removesuffix(":*") for term in (ts_query(query) or "").split(" & ") if term]
    tokens = text.split()
    hits = [i for i, token in enumerate(tokens) if any(fold(token).replace(" ", "").startswith(p) for p in prefixes)]
    if not hits:
        return [(" ".join(tokens[: words * 2]) + (" …" if len(tokens) > words * 2 else ""), False)]
    start, end = max(0, hits[0] - words), min(len(tokens), hits[0] + words + 1)
    pieces, hit_set = [], set(hits)
    if start > 0:
        pieces.append(("… ", False))
    for i in range(start, end):
        pieces.append((tokens[i], i in hit_set))
        pieces.append((" ", False))
    if end < len(tokens):
        pieces.append(("…", False))
    return pieces


def search(conn: psycopg.Connection, query: str, limit: int = 20) -> dict[str, list[dict]]:
    params = {"q": ts_query(query) or "''", "like": f"%{query.strip()}%", "limit": limit}
    return {
        "members": conn.execute(
            """SELECT id, name, chamber, party, constituency FROM members
               WHERE f_unaccent(name) ILIKE f_unaccent(%(like)s) ORDER BY in_office DESC, legislature DESC,
                   sort_name LIMIT %(limit)s""",
            params,
        ).fetchall(),
        "bills": conn.execute(
            f"""SELECT id, number, title, status, ts_rank(search, q) AS rank
               FROM bills, to_tsquery('simple', %(q)s) q
               WHERE (search @@ q OR number ILIKE %(like)s) AND {ONE_PAGE_PER_BILL} ORDER BY rank DESC,
                   last_event_on DESC NULLS LAST LIMIT %(limit)s""",
            params,
        ).fetchall(),
        "votes": conn.execute(
            """SELECT id, voted_at, description FROM votes, to_tsquery('simple', %(q)s) q
               WHERE search @@ q AND NOT is_test ORDER BY voted_at DESC LIMIT %(limit)s""",
            params,
        ).fetchall(),
        "speeches": conn.execute(
            """SELECT s.member_id, m.name, s.sitting, s.sitting_on, s.topic, s.url
               FROM speeches s JOIN members m ON m.id = s.member_id, to_tsquery('simple', %(q)s) q
               WHERE s.search @@ q ORDER BY s.sitting_on DESC NULLS LAST LIMIT %(limit)s""",
            params,
        ).fetchall(),
        # What was said: speaker turns from the stenograms, most recent sittings first.
        "texts": [
            {**row, "snippet": snippet(row["body"], query)}
            for row in conn.execute(
                """SELECT t.url, t.speaker, t.member_id, t.body, st.chamber, st.sitting_on, st.title
                   FROM speech_texts t JOIN stenograms st ON st.url = t.url, to_tsquery('simple', %(q)s) q
                   WHERE t.search @@ q ORDER BY st.sitting_on DESC NULLS LAST, t.url, t.seq LIMIT %(limit)s""",
                params,
            )
        ],
    }
