import datetime as dt
import hashlib
import json
import zipfile

import httpx
import pytest

from parlament import exports, releases
from tests.seed import seed

DAY = dt.date(2026, 11, 1)


@pytest.fixture
def built(conn, tmp_path):
    seed(conn)
    exports.write_all(conn, str(tmp_path / "export"))
    return releases.build(conn, DAY, tmp_path / "export", tmp_path / "release")


def test_archive_holds_every_export_with_a_readme(built):
    (archive, sums), body = built
    assert archive.name == "parlament-date-2026-11-01.zip"
    with zipfile.ZipFile(archive) as zipped:
        names = set(zipped.namelist())
        readme = zipped.read("parlament-date-2026-11-01/README.md").decode()
    assert names == {f"parlament-date-2026-11-01/{name}.csv" for name in exports.TABLES} | {
        "parlament-date-2026-11-01/README.md"
    }
    assert "la 1 noiembrie 2026" in readme and "`present_not_voting`" in readme and "nu înseamnă zero" in readme
    assert sums.read_text() == f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    assert "| `voturi_nominale.csv` |" in body and "Legea nr. 8/1996" in body


def github(responses, calls):
    def handle(request):
        calls.append(request)
        return responses(request)

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_publish_creates_the_release_and_uploads_the_files(built):
    (archive, sums), body = built
    calls = []

    def responses(request):
        if request.method == "GET":
            return httpx.Response(404)
        if request.url.path.endswith("/releases"):
            return httpx.Response(201, json={"id": 7, "html_url": "https://github.com/o/r/releases/tag/data-x"})
        return httpx.Response(201, json={})

    url = releases.publish([archive, sums], "data-x", "Titlu", body, "o/r", "secret", github(responses, calls))
    assert url == "https://github.com/o/r/releases/tag/data-x"
    created = json.loads(calls[1].content)
    assert created["tag_name"] == "data-x" and created["target_commitish"] == "main"
    uploads = calls[2:]
    assert [u.url.params["name"] for u in uploads] == [archive.name, "SHA256SUMS"]
    assert uploads[0].headers["content-type"] == "application/zip" and uploads[0].content == archive.read_bytes()
    assert all(c.headers["authorization"] == "Bearer secret" for c in calls)


def test_an_existing_release_is_left_alone(built):
    (archive, sums), body = built
    calls = []
    client = github(lambda request: httpx.Response(200, json={"id": 1}), calls)
    assert releases.publish([archive, sums], "data-x", "Titlu", body, "o/r", "secret", client) is None
    assert [c.method for c in calls] == ["GET"]


def test_a_failed_upload_removes_the_release(built):
    (archive, sums), body = built
    calls = []

    def responses(request):
        if request.method == "GET":
            return httpx.Response(404)
        if request.method == "POST" and request.url.path.endswith("/releases"):
            return httpx.Response(201, json={"id": 7, "html_url": "u"})
        if request.method == "POST":
            return httpx.Response(500)
        return httpx.Response(204)

    with pytest.raises(httpx.HTTPStatusError):
        releases.publish([archive, sums], "data-x", "Titlu", body, "o/r", "secret", github(responses, calls))
    assert calls[-1].method == "DELETE" and calls[-1].url.path.endswith("/releases/7")
