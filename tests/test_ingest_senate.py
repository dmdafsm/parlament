import datetime as dt

from parlament import analytics
from parlament.ingest import senat_agenda, senat_bills, senat_members, senat_votes
from tests.conftest import fixture
from tests.seed import SENATOR, seed


def test_calendar_days_and_form_state():
    page = fixture("senat_vote_calendar.html")
    # Highlighted (cyan) days are the days with votes; the number is days since 1 January 2000.
    assert senat_votes.vote_days(page) == [dt.date(2025, 6, 24), dt.date(2025, 6, 30)]
    state = senat_votes.form_state(page)
    assert state["__VIEWSTATE"] == "STARE-CALENDAR"
    assert senat_votes.PAGING not in state  # unchecked: the day lists all its votes on one page
    post = senat_votes.postback(state, "9306")
    assert post["__EVENTTARGET"] == senat_votes.CALENDAR and post["__EVENTARGUMENT"] == "9306"
    assert senat_votes.months(dt.date(2024, 12, 21), dt.date(2025, 2, 3)) == [
        dt.date(2024, 12, 1),
        dt.date(2025, 1, 1),
        dt.date(2025, 2, 1),
    ]


def test_day_and_nominal():
    votes = senat_votes.parse_day(fixture("senat_vote_day.html"), dt.date(2025, 6, 24))
    assert [(v["app_id"], v["seq"], v["bill_ref"], v["bill_cod"], v["result"]) for v in votes] == [
        ("bbbbbbbb-0000-0000-0000-000000000001", 0, "L1/2025", "900", "Adoptat"),
        ("bbbbbbbb-0000-0000-0000-000000000002", 1, "L7/2025", "901", "Respins"),
    ]
    assert votes[0]["description"].startswith("L1/2025 vot final: Proiect de lege")
    assert (votes[0]["present"], votes[0]["yes"], votes[0]["no"]) == (3, 2, 1)
    records = senat_votes.parse_nominal(fixture("senat_vote_nominal.html"), 2024)
    # The row with no option marked is not counted as present (the Senate's own total says 3).
    assert [(r["member_id"][-12:], r["choice"], r["group"]) for r in records] == [
        ("444444444444", "yes", "PNL"),
        ("555555555555", "yes", "PSD"),
        ("666666666666", "no", "AUR"),
    ]
    assert records[0]["member_id"] == SENATOR


def test_bill_agenda_and_biography():
    bill = senat_bills.parse_bill(fixture("senat_bill.html"))
    assert (bill["number"], bill["status"], bill["character"]) == ("L7/2025", "Respins definitiv", "Organică")
    assert bill["registered_on"] == dt.date(2025, 2, 3) and bill["last_event_on"] == dt.date(2025, 6, 24)
    assert bill["events"][0]["documents"][0]["url"] == "https://www.senat.ro/legis/PDF/2025/25L007FG.PDF"
    assert [d["url"][-12:] for d in bill["documents"]] == ["25L007FG.pdf", "25L007EM.pdf"]
    assert [(p["name"], p["label"]) for p in bill["initiators"]][:2] == [
        ("Dobre Elena", "senator PNL"),
        ("Cernat Vlad", "deputat USR"),
    ]
    assert senat_bills.senate_key("L111/09.02.2026") == "L111/2026"
    assert bill["law"] is None
    assert senat_bills.LAW.search("A devenit Legea nr.8/10.02.2025 publicatã în M.O.").groups() == ("8", "2025")
    agenda = senat_agenda.parse_agenda(fixture("senat_agenda.html"), dt.date(2025, 6, 24))
    assert agenda["day"] == dt.date(2025, 6, 24)
    assert [(i["bill_ref"], i["bill_cod"]) for i in agenda["items"]] == [("L1/2025", "900"), ("L7/2025", "901")]
    assert senat_agenda.parse_agenda("<html><body><p>Nimic</p></body></html>", dt.date(2025, 6, 25)) is None
    # A day without a sitting (or not yet published) has only the heading: no agenda.
    heading_only = "<html><body><h2>Ordinea de zi a Ședinței Senatului din 25 iunie 2025</h2></body></html>"
    assert senat_agenda.parse_agenda(heading_only, dt.date(2025, 6, 25)) is None
    biography = senat_members.parse_biography(fixture("senat_biography.html"))
    assert [s["section"] for s in biography] == ["Experiență profesională", "Alte informații"]
    assert biography[0]["entries"][0]["text"].startswith("2020-2024, Profesor\nLiceul Exemplu")
    # The "Mai mult..." postback (details on request) is not part of the text.
    assert biography[0]["entries"][0]["text"].endswith("Consiliul Local Exemplu")
    # Nationality and contact details are left out.
    assert [e["label"] for e in biography[1]["entries"]] == ["Limbi străine cunoscute"]


def test_store_link_and_attendance(conn):
    seed(conn)
    votes = {
        row["id"]: row
        for row in conn.execute("SELECT id, bill_id, has_nominal, result FROM votes WHERE chamber = 'senat'")
    }
    # L1/2025 is also on cdep.ro (PL-x 501/2025): the Senate vote goes to that page. L7/2025 is Senate-only.
    assert votes["senat-bbbbbbbb-0000-0000-0000-000000000001"]["bill_id"] == "cd-22001"
    assert votes["senat-bbbbbbbb-0000-0000-0000-000000000002"]["bill_id"] == "senat-901"
    assert conn.execute("SELECT senate_key FROM bills WHERE id = 'cd-22001'").fetchone()["senate_key"] == "L1/2025"
    listed = [b["id"] for b in analytics.bills(conn)]
    assert "senat-901" in listed and "cd-22001" in listed
    initiator = conn.execute(
        "SELECT member_ref FROM bill_initiators WHERE bill_id = 'senat-901' AND seq = 0"
    ).fetchone()
    assert initiator["member_ref"] == SENATOR
    senator = analytics.member(conn, SENATOR)
    assert senator["attendance_unit"] == "vote" and senator["attendance_base"] == 1 and senator["attendance"] == 1
    cv = conn.execute("SELECT cv FROM members WHERE id = %s", (SENATOR,)).fetchone()["cv"]
    assert cv[0]["section"] == "Experiență profesională"
    agenda = conn.execute(
        "SELECT bill_id FROM agenda_items WHERE agenda_id = 'senat-2025-06-24' ORDER BY seq"
    ).fetchall()
    assert [row["bill_id"] for row in agenda] == ["cd-22001", "senat-901"]


class ListForms:
    """Returns the list page for every request and records the postbacks."""

    def __init__(self):
        self.posts = []

    def get(self, source, url, fresh=False):
        return fixture("senat_list_2020.html")

    def post(self, source, url, form, key, fresh=False):
        self.posts.append((form["__EVENTTARGET"], form[senat_members.LEGISLATURE_FIELD], key))
        return fixture("senat_list_2020.html")


def test_list_of_an_earlier_legislature():
    page = fixture("senat_list_2020.html")
    assert senat_members.legislature_option(page, 2016) == "11111111-0000-0000-0000-000000002016"
    # Cards with photos: the name and the group only; each mandate has its own id.
    assert [
        (s["guid"][:8], s["sort_name"], s["group_name"], s["constituency"])
        for s in senat_members.parse_senator_list(page)
    ] == [
        ("cccccccc", "FLOREA Ioana-Maria", "Partidul Național Liberal", None),
        ("dddddddd", "GHEORGHE Radu", "Partidul Social Democrat", None),
    ]
    fetcher = ListForms()
    senat_members.senator_list(fetcher, 2020)
    assert fetcher.posts == [
        (senat_members.LEGISLATURE_FIELD, "11111111-0000-0000-0000-000000002020", "legislatura=2020"),
        (senat_members.FILTER_BUTTON, "11111111-0000-0000-0000-000000002020", "legislatura=2020&filtru"),
    ]
    fetcher = ListForms()
    senat_members.senator_list(fetcher, 2024)  # the current legislature is the plain list
    assert fetcher.posts == []
