import datetime as dt

from parlament.ingest import cdep_votes
from tests.conftest import fixture
from tests.seed import seed

DAY = dt.date(2025, 6, 23)


class Pages:
    """Serves fixtures by URL instead of the network; records what was asked for."""

    def __init__(self, pages: dict[str, str]):
        self.pages, self.asked = pages, []

    def get(self, source, url, encoding=None, fresh=False):
        self.asked.append(url)
        for marker, name in self.pages.items():
            if marker in url:
                return fixture(name)
        raise AssertionError(f"unexpected URL {url}")


def test_xml_parsers():
    totals = cdep_votes.parse_xml_day(fixture("cdep_vote_day.xml"))
    assert totals["40002"] == {"present": 4, "yes": 2, "no": 1, "abstain": 1, "not_voted": 0}
    deputies = {"albescu ana maria": ["cd-2024-1"], "dima petre": ["cd-2024-4"], "enescu maria": ["cd-2024-5"]}
    # Cernat Vlad is not known: the XML list is not used for this vote.
    assert cdep_votes.parse_xml_nominal(fixture("cdep_vote_nominal.xml"), deputies) is None
    deputies["cernat vlad"] = ["cd-2024-3"]
    records = cdep_votes.parse_xml_nominal(fixture("cdep_vote_nominal.xml"), deputies)
    assert [(r["member_id"], r["choice"]) for r in records] == [
        ("cd-2024-1", "yes"),
        ("cd-2024-4", "no"),
        ("cd-2024-5", "yes"),
        ("cd-2024-3", "abstain"),
    ]


def test_ingest_fills_not_voted_and_reads_xml_nominal(conn):
    seed(conn)
    conn.execute("DELETE FROM votes WHERE chamber = 'cd'")
    pages = Pages(
        {
            "evot2015.data": "cdep_vote_day_short.html",
            "par1=1": "cdep_vote_day.xml",
            "par1=2": "cdep_vote_nominal.xml",
        }
    )
    assert cdep_votes.ingest_days(conn, pages, [DAY]) == 2
    vote = conn.execute("SELECT not_voted, has_nominal FROM votes WHERE id = 'cd-40002'").fetchone()
    assert vote == {"not_voted": 0, "has_nominal": True}
    records = conn.execute(
        "SELECT member_id, choice FROM vote_records WHERE vote_id = 'cd-40002' ORDER BY member_id"
    ).fetchall()
    assert [(r["member_id"], r["choice"]) for r in records] == [
        ("cd-2024-1", "yes"),
        ("cd-2024-3", "abstain"),
        ("cd-2024-4", "no"),
        ("cd-2024-5", "yes"),
    ]
    # The HTML nominal page was not needed.
    assert not any("evot2015.nominal" in url for url in pages.asked)


def test_ingest_falls_back_to_html_nominal(conn):
    seed(conn)
    conn.execute("DELETE FROM votes WHERE chamber = 'cd'")
    conn.execute("UPDATE members SET sort_name = 'Altcineva Vlad' WHERE id = 'cd-2024-3'")
    pages = Pages(
        {
            "evot2015.data": "cdep_vote_day.html",
            "par1=2": "cdep_vote_nominal.xml",
            "evot2015.nominal": "cdep_vote_nominal.html",
        }
    )
    cdep_votes.ingest_days(conn, pages, [DAY])
    assert conn.execute("SELECT count(*) AS n FROM vote_records WHERE vote_id = 'cd-40002'").fetchone()["n"] == 4
    # The HTML daily list had all totals, so the XML daily list was not requested.
    assert not any("par1=1" in url for url in pages.asked)
