import datetime as dt

from parlament.ingest import cdep_activity, cdep_agenda, cdep_bills, cdep_votes
from tests.conftest import fixture


def test_bill():
    bill = cdep_bills.parse_bill(fixture("cdep_bill.html"))
    assert bill["number"] == "PL-x 501/2025"
    assert bill["ordinance"] == "OUG 12/2025"
    assert bill["registered_on"] == dt.date(2025, 3, 18)
    assert bill["senate_number"] == "L1/2025" and bill["urgent"] is True
    assert bill["law"] == "Lege 77/2025" and bill["kind"] == "Proiect de Lege"
    assert bill["initiator_summary"] == "3 deputati+senatori"
    assert [(i["name"], i["member_ref"]) for i in bill["initiators"]] == [
        ("Albescu Ana-Maria", "cd-2024-1"),
        ("Cernat Vlad", "cd-2024-3"),
        ("Dobre Elena", "senat-2024-5"),
    ]
    assert [d["title"] for d in bill["documents"]] == ["Expunerea de motive", "Avizul Consiliului Legislativ"]
    events = bill["events"]
    assert [(e["date"], e["chamber"]) for e in events] == [
        (dt.date(2025, 3, 18), "CD"),
        (dt.date(2025, 3, 18), "CD"),  # blank date cell = same day as the row above
        (dt.date(2025, 6, 25), "CD"),
        (dt.date(2025, 7, 10), "Promulgare"),
    ]
    assert events[0]["action"] == "prezentare în Biroul Permanent al Camerei Deputatilor"
    assert events[0]["documents"][0]["title"] == "Adresa Senatului"
    assert events[1]["action"] == "trimis pentru raport la: Comisia pentru buget"
    assert events[1]["notes"] == "termen depunere raport: 04.04.2025"
    assert bill["last_event_on"] == dt.date(2025, 7, 10)


def test_votes():
    day = cdep_votes.parse_day(fixture("cdep_vote_day.html"), dt.date(2025, 6, 23))
    assert [v["idv"] for v in day] == ["40001", "40002"]
    assert day[0]["is_test"] and not day[1]["is_test"]
    assert day[1]["voted_at"] == dt.datetime(2025, 6, 23, 12, 7)
    assert (day[1]["present"], day[1]["yes"], day[1]["no"], day[1]["abstain"], day[1]["not_voted"]) == (4, 2, 1, 1, 0)
    records = cdep_votes.parse_nominal(fixture("cdep_vote_nominal.html"))
    assert [(r["member_id"], r["group"], r["choice"]) for r in records] == [
        ("cd-2024-1", "PSD", "yes"),
        ("cd-2024-4", "PSD", "no"),
        ("cd-2024-5", "PSD", "yes"),
        ("cd-2024-3", "USR", "abstain"),
    ]
    assert cdep_votes.nominal_subject(fixture("cdep_vote_nominal.html")) == "PL-x 501/2025 - Vot final adoptare"


def test_sitting_days_skip_weekends():
    days = cdep_votes.sitting_days(dt.date(2025, 6, 20), dt.date(2025, 6, 23))
    assert days == [dt.date(2025, 6, 20), dt.date(2025, 6, 23)]


def test_agenda():
    agenda = cdep_agenda.parse_agenda(fixture("cdep_agenda.html"))
    assert agenda["oid"] == "3001"
    assert agenda["approved_on"] == dt.date(2025, 6, 23) and agenda["first_day"] == dt.date(2025, 6, 23)
    assert agenda["pdf_url"].endswith("F1/ODZ.pdf")
    assert [(i["position"], i["bill_ref"], i["bill_idp"]) for i in agenda["items"]] == [
        ("-", "PHCD 72/2026", None),  # chamber resolution: different application, its id is not a bill id
        ("1", "PL-x 501/2025", "22001"),
        ("2", "Pl-x 7/2025", "22002"),
    ]


def test_activity_lists():
    initiatives = cdep_activity.parse_initiatives(fixture("cdep_initiatives.html"))
    assert [(i["idp"], i["status"]) for i in initiatives] == [("22001", "Lege 77/2025"), ("22002", "raport depus")]
    questions = cdep_activity.parse_questions(fixture("cdep_questions.html"))
    assert [(q["idi"], q["kind"], q["number"], q["asked_on"], q["title"]) for q in questions] == [
        ("70001", "interpelare", "297B", dt.date(2025, 6, 3), "Situația drumurilor județene"),
        ("70002", "intrebare", "15A", dt.date(2025, 2, 10), "Finanțarea spitalului"),
    ]
    assert questions[0]["url"] == "https://www.cdep.ro/ords/pls/parlam/interpelari2015.detalii?idi=70001&idl=1"
    motions = cdep_activity.parse_motions(fixture("cdep_motions.html"))
    assert (
        motions[0]["id"] == "cd-1601"
        and motions[0]["title"] == "Moțiune de exemplu"
        and motions[0]["result"] == "Respinsă"
    )
    speeches = cdep_activity.parse_speeches(fixture("cdep_speeches.html"))
    assert len(speeches) == 2
    assert speeches[0]["sitting_on"] == dt.date(2025, 6, 24) and speeches[0]["duration"] == "02m13s"
    assert speeches[1]["topic"] == "Declarații politice."
    pages = cdep_activity.speech_pages(fixture("cdep_speeches.html"))
    assert [page.rsplit("pags=", 1)[1] for page in pages] == ["21", "41"]


def test_latest_sitting_date():
    assert cdep_votes.page_date(fixture("cdep_vote_day.html")) == dt.date(2025, 6, 23)
