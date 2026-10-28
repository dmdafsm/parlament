import datetime as dt

from parlament import analytics, exports, feeds
from parlament.ingest import cdep_bills
from tests.seed import seed


def by_id(rows):
    return {row["id"]: row for row in rows}


def test_attendance_and_loyalty(conn):
    seed(conn)
    members = by_id(analytics.members(conn, 2024, "cd"))
    # One nominal, non-test vote; deputies 1, 3, 4, 5 present; 6 was not yet in office.
    assert members["cd-2024-1"]["attendance"] == 1
    assert members["cd-2024-6"]["attendance_base"] is None
    # PSD present: 1 yes, 4 no, 5 yes -> group line 'yes' (2 of 3); deputy 4 voted against it.
    assert members["cd-2024-4"]["loyalty"] == 0
    assert members["cd-2024-5"]["loyalty"] == 1
    # USR had one member present (abstain) -> majority of one.
    assert members["cd-2024-3"]["loyalty"] == 1
    assert members["cd-2024-1"]["group_changes"] == 2 and members["cd-2024-1"]["party_changes"] == 1


def test_senator_attendance_uses_published_session_counts(conn):
    seed(conn)
    senator = analytics.members(conn, 2024, "senat")[0]
    assert (senator["attendance_present"], senator["attendance_base"]) == (77, 100)
    assert float(senator["attendance"]) == 0.77 and senator["attendance_unit"] == "session"


def test_sorting_and_filters(conn):
    seed(conn)
    by_speeches = [row["id"] for row in analytics.members(conn, 2024, "cd", sort="luari")]
    assert by_speeches[0] == "cd-2024-1"  # 12 speeches in the fixture
    assert {row["id"] for row in analytics.members(conn, 2024, query="enescu")} == {"cd-2024-5"}
    assert {row["id"] for row in analytics.members(conn, 2024, group="USR")} == {"cd-2024-3"}


def test_member_votes_flag_votes_against_group(conn):
    seed(conn)
    vote = analytics.member_votes(conn, "cd-2024-4")[0]
    assert vote["choice"] == "no" and vote["group_choice"] == "yes" and vote["against_group"]


def test_votes_and_agenda_link_to_bills(conn):
    seed(conn)
    assert conn.execute("SELECT bill_id FROM votes WHERE id = 'cd-40002'").fetchone()["bill_id"] == "cd-22001"
    assert conn.execute("SELECT bill_id FROM votes WHERE id = 'cd-40001'").fetchone()["bill_id"] is None
    # The agenda was stored before the bill: relink attaches its item afterwards.
    cdep_bills.relink(conn)
    items = {row["bill_ref"]: row["bill_id"] for row in conn.execute("SELECT bill_ref, bill_id FROM agenda_items")}
    assert items == {"PHCD 72/2026": None, "PL-x 501/2025": "cd-22001", "Pl-x 7/2025": None}


def test_senator_initiators_are_matched_by_name(conn):
    seed(conn)
    cdep_bills.relink(conn)
    refs = [row["member_ref"] for row in conn.execute("SELECT member_ref FROM bill_initiators ORDER BY seq")]
    # 'Dobre Elena' (cdep.ro senator id 5) is the senat.ro senator 'DOBRE Elena'.
    assert refs == ["cd-2024-1", "cd-2024-3", "senat-2024-aaaaaaaa-1111-2222-3333-444444444444"]


def test_group_flows(conn):
    seed(conn)
    flows = analytics.group_flows(conn, 2024)
    assert [(f["from_group"], f["to_group"], f["members"]) for f in flows] == [
        ("Grupul parlamentar al Partidului Național Liberal", "Grupul parlamentar al Partidului Social Democrat", 1)
    ]


def test_ordinances_and_stages(conn):
    seed(conn)
    stats = analytics.ordinance_stats(conn)
    assert (stats["total"], stats["approved_by_law"], stats["emergency"]) == (1, 1, 1)
    bill = analytics.bills(conn, ordinance=True)[0]
    assert bill["stage"] == "lege" and bill["days_to_law"] == (dt.date(2025, 7, 10) - dt.date(2025, 3, 18)).days
    assert analytics.bills(conn, query="ordonanta urgenta")[0]["id"] == "cd-22001"


def test_search(conn):
    seed(conn)
    results = analytics.search(conn, "Albescu")
    assert results["members"][0]["id"] == "cd-2024-1"
    assert analytics.search(conn, "PL-x 501/2025")["bills"][0]["id"] == "cd-22001"


def test_exports_and_feeds(conn, tmp_path):
    seed(conn)
    paths = exports.write_all(conn, str(tmp_path))
    assert {path.name for path in paths} >= {"parlamentari.csv", "voturi_nominale.csv"}
    header, *rows = (tmp_path / "voturi_nominale.csv").read_text(encoding="utf-8").splitlines()
    assert header == "vote_id,member_id,member_name,group_code,choice" and len(rows) == 4
    xml = feeds.member_feed(conn, "https://example.invalid/", "cd-2024-1")
    assert "<rss" in xml and "Vot: Pentru" in xml and "Inițiativă: PL-x 501/2025" in xml
    assert feeds.member_feed(conn, "https://example.invalid/", "nope") is None
