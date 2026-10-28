"""Open-data exports: one CSV per table, regenerated weekly and served at /date-deschise."""

import csv
from pathlib import Path

import psycopg

from parlament.config import settings

# Published tables and their columns (internal search vectors are left out).
TABLES = {
    "parlamentari": """SELECT id, chamber, legislature, source, source_id, name, sort_name, birth_date,
        constituency_no, constituency, group_id, party, party_name, minority_org, validated_on, mandate_end,
        in_office, url FROM members ORDER BY id""",
    "grupuri": "SELECT * FROM parl_groups ORDER BY id",
    "istoric_grupuri": """SELECT member_id, seq, group_id, group_name, start_date, end_date, precision
        FROM group_memberships ORDER BY 1, 2""",
    "istoric_partide": """SELECT member_id, seq, party, party_name, start_date, end_date, precision
        FROM party_memberships ORDER BY 1, 2""",
    "comisii": """SELECT c.id, c.chamber, c.legislature, c.name, cm.member_id, cm.role, cm.start_date
        FROM committees c JOIN committee_memberships cm ON cm.committee_id = c.id ORDER BY 1, 5""",
    "statistici": "SELECT member_id, metric, value, collected_at FROM member_stats ORDER BY 1, 2",
    "proiecte": """SELECT id, chamber, number, cd_number, senate_number, senate_key, title, kind, decisional_chamber,
        character, urgent, status, law, ordinance, initiator_summary, registered_on, last_event_on, url
        FROM bills ORDER BY id""",
    "proiecte_initiatori": "SELECT * FROM bill_initiators ORDER BY 1, 2",
    "proiecte_parcurs": "SELECT bill_id, seq, event_date, chamber, action, notes FROM bill_events ORDER BY 1, 2",
    "voturi": """SELECT id, chamber, voted_at, seq, description, bill_ref, bill_id, result, present, yes, no, abstain,
        not_voted, is_test, has_nominal, url FROM votes ORDER BY voted_at, seq""",
    "voturi_nominale": "SELECT * FROM vote_records ORDER BY 1, 2",
    "intrebari": "SELECT id, member_id, kind, number, asked_on, title, url FROM questions ORDER BY asked_on",
    "luari_de_cuvant": "SELECT member_id, seq, sitting, sitting_on, topic, duration, url FROM speeches ORDER BY 1, 2",
}


def export_dir(directory: str | None = None) -> Path:
    return Path(directory) if directory else settings().data_dir / "export"


def write_all(conn: psycopg.Connection, directory: str | None = None) -> list[Path]:
    target = export_dir(directory)
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, sql in TABLES.items():
        path = target / f"{name}.csv"
        tmp = path.with_suffix(".tmp")
        with conn.cursor() as cursor, tmp.open("w", newline="", encoding="utf-8") as handle:
            cursor.execute(sql)
            writer = csv.writer(handle)
            writer.writerow([column.name for column in cursor.description])
            for row in cursor:
                writer.writerow(row.values())
        tmp.replace(path)
        paths.append(path)
    return paths
