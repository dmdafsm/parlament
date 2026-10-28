import pytest
from fastapi.testclient import TestClient

from parlament import db
from tests.seed import seed


@pytest.fixture
def client(database_url, monkeypatch):
    from parlament.web import app as web

    with db.connect(database_url) as conn:
        seed(conn)
    monkeypatch.setattr(web, "CONF", web.CONF.__class__(**{**web.CONF.__dict__, "database_url": database_url}))
    monkeypatch.setattr(web, "_pool", None)
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
    vote = client.get("/vot/cd-40002").text
    # Deputy 6 was validated after the vote and must not be listed as absent.
    assert "Nu figurează ca prezenți" not in vote or "Florea Ion" not in vote
    assert "PL-x 501/2025" in client.get("/lege/cd-22001").text


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
    deputy = client.get("/parlamentar/cd-2024-1").text
    # Free-text CVs have no entry labels.
    assert "Spitalul Exemplu" in deputy and "None" not in deputy
    agenda = client.get("/ordinea-de-zi?camera=senat").text
    assert "Ordinea de zi a Ședinței Senatului din 24 iunie 2025" in agenda and "/lege/senat-901" in agenda
