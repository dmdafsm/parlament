import datetime as dt

from parlament import analytics
from parlament.ingest import senat_steno
from tests.conftest import fixture
from tests.seed import SENATOR, seed

PDF = "https://www.senat.ro/PAGINI/Stenograme/Stenograme_2025/Plen/25.06.24_1.pdf"


def test_calendar_links():
    links = senat_steno.calendar_links(fixture("senat_steno_calendar.html"))
    assert links == [
        ("https://www.senat.ro/PAGINI/Stenograme/Stenograme_2024/Plen/24.11.18.pdf", dt.date(2024, 11, 18)),
        ("https://www.senat.ro/PAGINI/Stenograme/Stenograme_2025/Plen/25.06.24%20comuna.pdf", dt.date(2025, 6, 24)),
        (PDF, dt.date(2025, 6, 24)),
    ]


def test_stenogram_turns():
    steno = senat_steno.parse_stenogram(fixture("senat_stenogram.txt"), dt.date(2025, 6, 24))
    assert steno["sitting"] == "Ședința Senatului din 24 iunie 2025"
    assert steno["sitting_on"] == dt.date(2025, 6, 24)
    chair, senator, chair_again = steno["turns"]
    # The summary page and the opening lines before the first speaker are left out; page numbers are dropped.
    assert chair["speaker"] == "Ion Exemplu"
    assert chair["body"] == "Bună dimineața, stimați colegi!\nInvit la microfon pe doamna senator Elena Dobre."
    assert senator["speaker"] == "Elena Dobre"
    assert "într-un context bugetar dificil.\nVă mulțumesc." in senator["body"]
    assert chair_again["speaker"] == "Ion Exemplu"


class Calendar:
    def __init__(self):
        self.years = []

    def get(self, source, url, encoding=None, fresh=False):
        return fixture("senat_steno_calendar.html")

    def post(self, source, url, form, key, fresh=False):
        self.years.append(form[senat_steno.YEAR_FIELD])
        return fixture("senat_steno_calendar.html")

    def get_bytes(self, source, url, fresh=False):
        return url.encode()


def test_ingest_links_senators_and_search(conn, monkeypatch):
    seed(conn)
    monkeypatch.setattr(senat_steno, "pdf_text", lambda content: fixture("senat_stenogram.txt"))
    fetcher = Calendar()
    # Sittings before the legislature (18 Nov 2024) are skipped; the joint sitting and the Senate sitting are kept.
    assert senat_steno.ingest(conn, fetcher, 2024) == 2
    assert fetcher.years[0] == "2024"
    texts = analytics.search(conn, "spitalelor ambulanta", 2024)["texts"]
    assert {(t["url"], t["chamber"], t["member_id"]) for t in texts} >= {(PDF, "senat", SENATOR)}
    # Stored stenograms are not fetched again.
    assert senat_steno.ingest(conn, Calendar(), 2024) == 0
