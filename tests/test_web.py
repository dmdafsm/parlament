import datetime as dt

import pytest
from fastapi.testclient import TestClient

from parlament import analytics, db
from parlament.ingest import cdep_members
from parlament.ingest.cdep_members import ListedDeputy, Profile
from tests.seed import deputy, seed


@pytest.fixture
def client(database_url, monkeypatch):
    from parlament.web import app as web

    with db.connect(database_url) as conn:
        seed(conn)
    monkeypatch.setattr(web, "CONF", web.CONF.__class__(**{**web.CONF.__dict__, "database_url": database_url}))
    monkeypatch.setattr(web, "_pool", None)
    monkeypatch.setattr(web, "_slots", None, raising=False)
    with TestClient(web.app) as test_client:
        yield test_client
    if web._pool is not None:
        web._pool.close()
        web._pool = None


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/parlamentari",
        "/parlamentari?grupare=grup&sort=prezenta",
        "/parlamentari?grupare=judet&camera=cd",
        "/parlamentari?grupare=camera&q=albescu",
        "/parlamentar/cd-2024-1",
        "/parlamentar/cd-2024-1/voturi",
        "/parlamentar/senat-2024-aaaaaaaa-1111-2222-3333-444444444444",
        "/legi",
        "/legi?q=ordonanta&stadiu=lege",
        "/lege/cd-22001",
        "/voturi",
        "/vot/cd-40002",
        "/voturi?camera=senat",
        "/vot/senat-bbbbbbbb-0000-0000-0000-000000000001",
        "/lege/senat-901",
        "/ordinea-de-zi",
        "/ordinea-de-zi?camera=senat",
        "/cauta?q=Albescu",
        "/traseism",
        "/ordonante",
        "/invata",
        "/invata/cum-se-face-o-lege",
        "/metodologie",
        "/date-deschise",
    ],
)
def test_pages(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text[:500]
    assert "Content-Security-Policy" in response.headers
    assert "<html" in response.text


def test_page_content(client):
    member = client.get("/parlamentar/cd-2024-1").text
    assert "Ana-Maria ALBESCU" in member and "Vicelider" in member and "Profil oficial" in member
    # Initiatives, speeches and questions are folded; the CV keeps one line per role.
    assert member.count('<details class="fold">') >= 3
    vote = client.get("/vot/cd-40002").text
    # Deputy 6 was validated after the vote and must not be listed as absent.
    assert "Nu figurează ca prezenți" not in vote or "Florea Ion" not in vote
    # The nominal list is grouped by parliamentary group.
    assert '<p class="bold no-margin top-margin">PSD' in vote
    # The votes list says what was voted: the linked bill's number and title.
    assert "PL-x 501/2025 –" in client.get("/voturi").text
    assert "PL-x 501/2025" in client.get("/lege/cd-22001").text


def test_ended_mandates_filter_and_collapsible_groups(client, database_url):
    with db.connect(database_url) as conn:
        conn.execute("UPDATE members SET in_office = false WHERE id = 'cd-2024-1'")
        analytics.refresh(conn)
        conn.commit()
    # 'Mandat încetat' lists only the members whose mandate ended; by default they are left out.
    ended = client.get("/parlamentari?fosti=true").text
    assert "Ana-Maria ALBESCU" in ended and "mandat încetat" in ended and "/parlamentar/cd-2024-3" not in ended
    current = client.get("/parlamentari").text
    assert "Ana-Maria ALBESCU" not in current and "/parlamentar/cd-2024-3" in current
    # The API keeps its meaning: fosti=true adds them to the members in office.
    ids = {m["id"] for m in client.get("/api/v1/parlamentari?fosti=true").json()}
    assert {"cd-2024-1", "cd-2024-3"} <= ids
    # Each group of a grouped list can be folded.
    assert '<details class="fold" open>' in client.get("/parlamentari?grupare=grup").text


def test_htmx_returns_partial(client):
    response = client.get("/parlamentari?sort=luari", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<table" in response.text and "<html" not in response.text


def test_api_and_feeds(client):
    members = client.get("/api/v1/parlamentari?camera=cd").json()
    assert {m["id"] for m in members} >= {"cd-2024-1", "cd-2024-4"}
    assert client.get("/api/v1/parlamentari/cd-2024-4").json()["voturi_recente"][0]["against_group"] is True
    bill = client.get("/api/v1/proiecte/cd-22001").json()
    assert bill["ordinance"] == "OUG 12/2025" and len(bill["parcurs"]) == 4
    assert client.get("/api/v1/voturi/cd-40002").json()["yes"] == 2
    assert client.get("/feed/voturi.xml").headers["content-type"].startswith("application/rss+xml")
    assert client.get("/feed/lege/cd-22001.xml").status_code == 200


def test_not_found_and_validation(client):
    assert client.get("/parlamentar/nu-exista").status_code == 404
    assert client.get("/api/v1/proiecte/nu-exista").status_code == 404
    assert client.get("/parlamentari?camera=altceva").status_code == 422
    assert client.get("/date-deschise/../../etc/passwd.csv").status_code == 404
    assert client.get("/foto/..%2F..%2Fetc").status_code in (307, 404)


def test_empty_county_from_form_is_all(client):
    assert client.get("/parlamentari?judet=&camera=&sort=luari").status_code == 200
    assert client.get("/parlamentari?judet=44").status_code == 422


def test_senate_pages(client):
    vote = client.get("/vot/senat-bbbbbbbb-0000-0000-0000-000000000001").text
    assert "Adoptat" in vote and "/lege/cd-22001" in vote
    assert "24 iun. 2025" in vote and "24 iun. 2025, 00:00" not in vote  # the Senate publishes no time of day
    bill = client.get("/lege/cd-22001").text
    assert "Senat · 24 iun. 2025" in bill  # the Senate vote is listed on the Chamber's bill page
    senate_only = client.get("/lege/senat-901").text
    assert "Respins definitiv" in senate_only and "Prima cameră: Senat" in senate_only
    profile = client.get("/parlamentar/senat-2024-aaaaaaaa-1111-2222-3333-444444444444").text
    assert "Biografie (CV)" in profile and "Liceul Exemplu" in profile and "Tel.: 000" not in profile
    found = client.get("/cauta?q=adoptata").text
    assert "Ce s-a spus în plen (1)" in found and "<mark>adoptată.</mark>" in found
    deputy = client.get("/parlamentar/cd-2024-1").text
    # Free-text CVs have no entry labels.
    assert "Spitalul Exemplu" in deputy and "None" not in deputy
    agenda = client.get("/ordinea-de-zi?camera=senat").text
    assert "Ordinea de zi a Ședinței Senatului din 24 iunie 2025" in agenda and "/lege/senat-901" in agenda


def test_bill_summary(client, database_url):
    with db.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO bill_summaries (bill_id, summary, model, source_url) VALUES"
            " ('senat-901', 'Proiectul propune un exemplu.', 'Model de test', 'https://example.invalid/em.pdf')"
        )
        conn.commit()
    page = client.get("/lege/senat-901").text
    assert "Pe înțelesul tuturor" in page and "Proiectul propune un exemplu." in page
    assert "Model de test" in page and 'href="https://example.invalid/em.pdf"' in page
    assert "Pe înțelesul tuturor" not in client.get("/lege/cd-22001").text


def test_earlier_mandates(client, database_url):
    with db.connect(database_url) as conn, conn.transaction():
        # The same person as deputy 3 (Cernat Vlad), in the 2020 legislature under another id.
        profile = Profile(name="Cernat Vlad", validated_on=dt.date(2020, 12, 21))
        profile.groups = [{"group_source_id": "9", "group_name": "Grupul vechi", "start": None, "end": None}]
        cdep_members.store_deputy(
            conn, 2020, ListedDeputy("77", "Cernat Vlad", 1, "Alba", "9", "Grupul vechi"), profile, "https://e.invalid"
        )
        analytics.refresh(conn)
    # Earlier legislatures are collected only for "other mandates": not listed and not searched.
    page = client.get("/parlamentari").text
    assert "/parlamentar/cd-2024-3" in page and "cd-2020-77" not in page
    assert "cd-2020-77" not in client.get("/cauta?q=Cernat").text
    # The current profile links the earlier mandate to its official page.
    current = client.get("/parlamentar/cd-2024-3").text
    # Shown as text: the earlier mandate has no page here and the official profile is not needed.
    assert 'href="https://e.invalid"' not in current and "deputat 2020–2024" in current
    # The votes of the current legislature are not counted as absences in the earlier mandate.
    with db.connect(database_url) as conn:
        assert analytics.members(conn, 2020)[0]["attendance"] is None


def test_vote_title_starts_at_the_bill_number():
    from parlament.web.filters import vote_title

    assert vote_title({"description": "Vot final", "subject": "Vot final Respingere PL 480/2026 pentru exemplu"}) == (
        "PL 480/2026 pentru exemplu"
    )
    assert vote_title({"description": "PHCD 68/2026", "subject": "PHCD 68/2026 PHCD 68/2026 privind exemplul"}) == (
        "PHCD 68/2026 privind exemplul"
    )
    assert vote_title({"description": "Prezenta", "subject": ""}) == "Prezenta"
    assert vote_title({"description": "L1/2026 vot final: Exemplu", "subject": None}) == "L1/2026 vot final: Exemplu"


def test_absent_members_without_a_group(client, database_url):
    with db.connect(database_url) as conn:
        # A deputy in office on the vote day, not in the nominal list and in no group.
        deputy(conn, "99", "Ion FĂRĂGRUP", "PSD", "1")
        conn.execute("UPDATE members SET group_id = NULL WHERE id = 'cd-2024-99'")
        conn.commit()
    response = client.get("/vot/cd-40002")
    assert response.status_code == 200
    assert "<b>Fără grup</b>" in response.text


def test_home_counts_each_bill_once(client, database_url):
    # A bill debated in both chambers has two pages; the bills list shows it once, and so does the home count.
    with db.connect(database_url) as conn:
        senate = conn.execute("SELECT senate_number FROM bills WHERE id = 'senat-901'").fetchone()["senate_number"]
        conn.execute("UPDATE bills SET senate_number = %s WHERE id = 'cd-22001'", (senate,))
        conn.commit()
        listed = sum(row["n"] for row in analytics.bill_stage_counts(conn))
        total = conn.execute("SELECT count(*) AS n FROM bills").fetchone()["n"]
    assert listed < total
    assert f'<div class="value">{listed}</div><div class="label">proiecte urmărite' in client.get("/").text


def test_a_burst_of_cancelled_requests_does_not_stop_the_site(client):
    import contextlib
    import socket
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    import uvicorn

    from parlament.web import app as web

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(web.app, port=port, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    base = f"http://127.0.0.1:{port}"

    def given_up(path):  # a browser leaving a page while its photos and profiles still load
        with contextlib.suppress(httpx.HTTPError):
            httpx.get(base + path, timeout=0.02)

    try:
        with ThreadPoolExecutor(100) as browsers:
            list(browsers.map(given_up, ["/parlamentar/cd-2024-1", "/foto/nu-exista"] * 150))
        assert httpx.get(base + "/parlamentari", timeout=10).status_code == 200
    finally:
        server.should_exit = True
        thread.join(5)
