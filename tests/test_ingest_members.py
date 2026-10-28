import datetime as dt

import pytest

from parlament.ingest import cdep_members, senat_members
from parlament.parsing import ParseError
from tests.conftest import fixture


def test_deputy_list():
    rows = cdep_members.parse_deputy_list(fixture("cdep_list.html"))
    assert [row.idm for row in rows] == ["1", "2", "3"]
    # The constituency number shown (35) differs from the `cir` link parameter (34): keep the shown one.
    assert (rows[0].constituency_no, rows[0].constituency, rows[0].group_short) == (35, "Suceava", "PSD")
    assert rows[1].constituency_no is None and rows[1].group_source_id == "8"
    assert rows[2].constituency == "Diaspora"


def test_deputy_list_changed_structure_fails_loudly():
    with pytest.raises(ParseError):
        cdep_members.parse_deputy_list("<html><body><p>Mentenanta</p></body></html>")


def test_deputy_profile_with_history():
    profile = cdep_members.parse_profile(fixture("cdep_profile.html"))
    assert profile.name == "Ana-Maria ALBESCU"
    assert profile.birth_date == dt.date(1971, 3, 3)
    assert profile.photo_url == "https://www.cdep.ro/parlamentari/l2024/AlbescuAna.JPG"
    assert (profile.constituency_no, profile.constituency) == (35, "Suceava")
    assert profile.validated_on == dt.date(2024, 12, 21)
    assert profile.mandate_end == dt.date(2026, 3, 1)
    assert [(p["party"], p["start"], p["end"]) for p in profile.parties] == [
        ("PNL", None, dt.date(2025, 9, 1)),
        ("PSD", dt.date(2025, 9, 1), None),
    ]
    # Ordered by date although the page lists the current group first.
    assert [g["group_source_id"] for g in profile.groups] == ["3", "0", "1"]
    assert profile.groups[2]["start"] == dt.date(2026, 2, 1)
    assert profile.roles == [
        {
            "group_name": "Grupul parlamentar al Partidului Național Liberal",
            "role": "Vicelider",
            "start": dt.date(2025, 1, 1),
            "end": dt.date(2025, 9, 1),
        }
    ]
    assert [(c["source_id"], c["role"]) for c in profile.committees] == [("3", "Secretar"), ("46", None)]
    assert profile.stats["speeches"][0] == 12 and profile.stats["speech_sessions"][0] == 7
    assert profile.stats["bills"][0] == 4 and profile.stats["questions"][0] == 9 and profile.stats["motions"][0] == 1
    assert profile.offices == "Suceava, Str. Exemplului nr. 1"
    assert profile.email == "ana.albescu@example.invalid"


def test_minority_deputy_profile():
    profile = cdep_members.parse_profile(fixture("cdep_profile_minority.html"))
    assert profile.constituency_no is None
    assert profile.minority_org == "Asociația Exemplu"
    assert profile.groups[0]["start"] is None and profile.groups[0]["end"] is None


def test_senator_list_deduplicates():
    rows = senat_members.parse_senator_list(fixture("senat_list.html"))
    assert [row["sort_name"] for row in rows] == ["DOBRE Elena", "ENACHE Mihai"]
    assert rows[0]["guid"] == "aaaaaaaa-1111-2222-3333-444444444444"
    assert (rows[1]["constituency_no"], rows[1]["birth_date"]) == (42, dt.date(1987, 9, 1))


def test_senator_profile():
    profile = senat_members.parse_senator_profile(fixture("senat_profile.html"))
    assert profile.name == "Elena DOBRE"
    assert profile.photo_url == "https://www.senat.ro/Poze/Senatori/2024/Dobre_Elena.jpg"
    assert (profile.constituency_no, profile.constituency, profile.validated_on) == (13, "Cluj", dt.date(2024, 12, 21))
    assert profile.parties[0]["party"] == "PNL"
    assert profile.groups[0]["group_source_id"] == "3e33c37a-0e27-49da-a83a-bd98212e750c"
    assert [(c["name"], c["role"], c["start"]) for c in profile.committees] == [
        ("Biroul Permanent", "Președinte", dt.date(2025, 6, 24)),
        ("Comisia pentru energie", "Membru", dt.date(2024, 12, 21)),
    ]
    assert {k: v[0] for k, v in profile.stats.items()} == {
        "bills": 47, "laws": 23, "political_statements": 1, "questions": 3, "interpellations": 6,
        "speeches": 14, "speech_sessions_total": 169, "motions": 0, "vote_sessions": 77, "vote_sessions_total": 100,
    }  # fmt: skip
    assert profile.email == "elena.dobre@example.invalid"


def test_store_deputy_is_idempotent(conn):
    listed = cdep_members.parse_deputy_list(fixture("cdep_list.html"))[0]
    profile = cdep_members.parse_profile(fixture("cdep_profile.html"))
    for _ in range(2):
        with conn.transaction():
            cdep_members.store_deputy(conn, 2024, listed, profile, "https://example.invalid/p")
    member = conn.execute("SELECT * FROM members").fetchone()
    assert member["id"] == "cd-2024-1" and member["party"] == "PSD" and not member["in_office"]
    assert conn.execute("SELECT count(*) AS n FROM group_memberships").fetchone()["n"] == 3
    assert conn.execute("SELECT count(*) AS n FROM member_stats").fetchone()["n"] == 5


def test_store_senator(conn):
    listed = senat_members.parse_senator_list(fixture("senat_list.html"))[0]
    profile = senat_members.parse_senator_profile(fixture("senat_profile.html"))
    with conn.transaction():
        mid = senat_members.store_senator(conn, 2024, listed, profile)
    row = conn.execute("SELECT m.*, g.short_name FROM members m JOIN parl_groups g ON g.id = m.group_id").fetchone()
    assert mid == row["id"] and row["short_name"] == "PNL" and row["birth_date"] == dt.date(1984, 7, 23)


def test_deputy_profile_2025_layout():
    profile = cdep_members.parse_profile(fixture("cdep_profile_2025.html"))
    assert profile.name == "Dana GEORGESCU" and profile.birth_date == dt.date(1970, 8, 15)
    assert profile.photo_url == "https://www.cdep.ro/parlamentari/l2024/GeorgescuDana.JPG"
    assert (profile.constituency_no, profile.constituency, profile.validated_on) == (
        35,
        "Suceava",
        dt.date(2024, 12, 21),
    )
    # The 2025 layout shows the party by full name only.
    assert profile.parties == [{"party": "PSD", "party_name": "Partidul Social Democrat", "start": None, "end": None}]
    assert profile.groups[0]["group_source_id"] == "1"
    assert profile.roles[0]["role"] == "Vicelider" and profile.roles[0]["start"] == dt.date(2025, 2, 1)
    # Friendship groups are not committees.
    assert [(c["source_id"], c["role"]) for c in profile.committees] == [("5", None), ("7", "Secretar")]
    assert {k: v[0] for k, v in profile.stats.items()} == {
        "speeches": 25, "speech_sessions": 21, "political_statements": 8, "bills": 59, "laws": 15,
        "questions": 7, "motions": 1,
    }  # fmt: skip
    # The Standing Bureau line ("Luări de cuvânt în BP") must not replace the plenary speeches.
    assert profile.stats["speeches"][1].startswith("https://www.cdep.ro/ords/pls/steno/steno2015.lista")
    assert profile.stats["bills"][1].startswith("https://www.cdep.ro/ords/pls/parlam/structura2015.mp?idm=9")
    assert profile.offices == "Suceava, Str. Exemplului nr. 2; Vatra Dornei, Str. Exemplu nr. 4"


def test_diaspora_constituency_name():
    profile = cdep_members.Profile(name="x")
    cdep_members._parse_elected(
        profile,
        "ales deputat în circumscriptia electorala nr.43 - Circumscriptia electorala pentru cetatenii români cu "
        "domiciliul în afara tarii data validării: 21 decembrie 2024 - HCD",
    )
    assert (profile.constituency_no, profile.constituency) == (43, "Diaspora")
    assert senat_members.constituency_name(
        "Circumscripția electorală pentru românii cu domiciliul în afara României"
    ) == ("Diaspora")
