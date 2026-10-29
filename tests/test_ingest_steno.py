import datetime as dt

from parlament import analytics
from parlament.ingest import cdep_steno
from tests.conftest import fixture
from tests.seed import seed


def test_stenogram_turns():
    steno = cdep_steno.parse_stenogram(fixture("cdep_stenogram.html"))
    assert steno["sitting_on"] == dt.date(2025, 6, 4)
    assert steno["title"].startswith("Dezbaterea Proiectului de Lege")
    first, second = steno["turns"]
    # A turn runs until the next speaker; the "detalii vot" link and text before the first speaker are left out.
    assert first == {
        "speaker": "Doamna Ana-Maria Albescu",
        "member_ref": "cd-2024-1",
        "body": "Stimați colegi,\nÎncepem votul.\nOrdonanța a fost adoptată. (Aplauze.)",
    }
    assert second["member_ref"] is None and second["speaker"] == "Domnul Ion Exemplu (ministru)"


def test_stenogram_search(conn):
    seed(conn)  # stores the stenogram fixture
    texts = analytics.search(conn, "invatamantul", 2024)["texts"]
    assert [(t["speaker"], t["member_id"]) for t in texts] == [("Domnul Ion Exemplu (ministru)", None)]
    # The search ignores diacritics; the snippet keeps them and marks the matching word.
    assert ("învățământul", True) in texts[0]["snippet"]
    texts = analytics.search(conn, "ordonanta adoptata", 2024)["texts"]
    assert texts[0]["member_id"] == "cd-2024-1"
