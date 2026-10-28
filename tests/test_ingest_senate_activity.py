import datetime as dt

from parlament.ingest import senat_activity
from tests.conftest import fixture
from tests.seed import SENATOR, seed

PROFILE = "https://www.senat.ro/FisaSenator.aspx?ParlamentarID=x"


def test_senate_lists():
    first, older = senat_activity.parse_questions(fixture("senat_questions.html"), "intrebare", PROFILE)
    assert first["id"] == "senat-aaaaaaaa-0000-0000-0000-000000000001"
    assert (first["number"], first["asked_on"], first["title"]) == (
        "12/a",
        dt.date(2025, 10, 14),
        "Drumul județean Exemplu",
    )
    assert first["recipient"] == "Ministerul Exemplu - Domnului Ion Exemplu – Ministru" and first["answered"]
    assert first["url"] == "https://www.senat.ro/PDFIntrebari/12a%20exemplu.pdf"
    assert older["url"] == PROFILE and older["answered"] is False
    speeches = senat_activity.parse_speeches(fixture("senat_speeches.html"))
    assert [s["sitting"] for s in speeches] == [
        "Ședința Senatului din 24 iunie 2025",
        "Ședința Senatului din 10 martie 2025",
    ]
    simple, censure = senat_activity.parse_motions(fixture("senat_motions.html"))
    assert simple["id"] == "senat-mo_250326_ms" and simple["title"] == "Ministrul Exemplu trebuie să plece"
    assert simple["result"] == "Respinsă (41 pentru, 45 împotrivă, 1 abțineri)"
    assert censure["url"] == "https://www.senat.ro/PDFMotiuni/leg/mo_250225_mc.pdf"


class Posts:
    def __init__(self, pages):
        self.pages, self.posted = pages, []

    def get(self, source, url, encoding=None, fresh=False):
        return fixture("senat_questions.html")

    def post(self, source, url, form, key, fresh=False):
        self.posted.append((form["__EVENTTARGET"], form["__EVENTARGUMENT"]))
        return fixture(self.pages[key])


def test_paging_stops_before_the_legislature(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO member_stats (member_id, metric, value) VALUES (%s, 'questions', 2), (%s, 'speeches', 2)"
        " ON CONFLICT (member_id, metric) DO UPDATE SET value = EXCLUDED.value",
        (SENATOR, SENATOR),
    )
    # The seeded profile also counts interpellations and motions: their lists are served empty / from fixtures.
    fetcher = Posts(
        {
            "intrebari": "senat_questions.html",
            "interpelari": "senat_speeches.html",
            "luaricuvint": "senat_speeches.html",
            "motiuni": "senat_motions.html",
        }
    )
    assert senat_activity.ingest(conn, fetcher, 2024) == 1
    # The first page already reaches back before December 2024: page 2 is not requested.
    assert ("ctl00$B_Center$cIntrebari$GridViewListaIntrebari", "Page$2") not in fetcher.posted
    rows = conn.execute("SELECT id, answered FROM questions WHERE member_id = %s", (SENATOR,)).fetchall()
    # Only the question from this legislature is stored.
    assert [(r["id"], r["answered"]) for r in rows] == [("senat-aaaaaaaa-0000-0000-0000-000000000001", True)]
    speeches = conn.execute("SELECT count(*) AS n FROM speeches WHERE member_id = %s", (SENATOR,)).fetchone()
    assert speeches["n"] == 2
