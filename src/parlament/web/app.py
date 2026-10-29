"""Public website, JSON API and RSS feeds. Read-only: data enters only through `parlament ingest`."""

import datetime as dt
import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from parlament import analytics, exports, feeds
from parlament.config import settings
from parlament.ingest import photos
from parlament.web import filters
from parlament.web.learn import PAGES as LEARN_PAGES

HERE = Path(__file__).parent
CONF = settings()

app = FastAPI(
    title="Parlamentul pe înțelesul tuturor",
    description="Date deschise despre activitatea Parlamentului României, colectate de pe cdep.ro și senat.ro.",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
filters.register(templates.env)

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(CONF.database_url, min_size=1, max_size=10, kwargs={"row_factory": dict_row}, open=True)
        with _pool.connection() as conn:
            analytics.ensure_overview(conn)
    return _pool


def get_conn() -> Iterator[Connection]:
    with pool().connection() as conn:
        yield conn


CSP = (
    "default-src 'self'; img-src 'self' https://www.cdep.ro https://www.senat.ro data:; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif request.method == "GET" and response.status_code == 200:
        response.headers.setdefault("Cache-Control", "public, max-age=300")
    return response


def render(request: Request, name: str, partial: str | None = None, **context) -> HTMLResponse:
    """Full page, or only the partial block when HTMX asks for it."""
    template = partial if partial and request.headers.get("HX-Request") else name
    return templates.TemplateResponse(request, template, {"legislature": CONF.legislature, **context})


def last_update(conn: Connection) -> dt.datetime | None:
    row = conn.execute("SELECT max(finished_at) AS at FROM ingest_log WHERE status IN ('ok', 'partial')").fetchone()
    return row["at"] if row else None


# --- pages --------------------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, conn: Connection = Depends(get_conn)):
    counts = conn.execute(
        f"""SELECT (SELECT count(*) FROM members WHERE in_office AND chamber = 'cd' AND legislature = %(leg)s) AS
               deputies,
                  (SELECT count(*) FROM members WHERE in_office AND chamber = 'senat' AND legislature = %(leg)s) AS
                      senators,
                  (SELECT count(*) FROM bills WHERE {analytics.ONE_PAGE_PER_BILL}) AS bills,
                  (SELECT count(*) FROM votes WHERE NOT is_test) AS votes""",
        {"leg": CONF.legislature},
    ).fetchone()
    return render(
        request,
        "home.html",
        counts=counts,
        votes=conn.execute(
            f"SELECT v.*, {analytics.VOTE_BILL} FROM votes v {analytics.VOTE_BILL_JOIN}"
            " WHERE NOT v.is_test ORDER BY v.voted_at DESC LIMIT 6"
        ).fetchall(),
        bills=analytics.bills(conn, limit=6),
        agenda=conn.execute("SELECT * FROM agendas ORDER BY first_day DESC NULLS LAST, id DESC LIMIT 1").fetchone(),
        constituencies=constituencies(conn),
        updated=last_update(conn),
    )


def constituencies(conn: Connection) -> list[dict]:
    return conn.execute(
        """SELECT constituency_no AS no, min(constituency) AS name FROM members
           WHERE constituency_no IS NOT NULL AND legislature = %s GROUP BY constituency_no ORDER BY constituency_no""",
        (CONF.legislature,),
    ).fetchall()


GROUPINGS = {"grup": "group_short", "judet": "constituency", "camera": "chamber"}


@app.get("/parlamentari", response_class=HTMLResponse)
def members_page(
    request: Request,
    camera: str = Query("", pattern="^(|cd|senat)$"),
    grupare: str = Query("", pattern="^(|grup|judet|camera)$"),
    sort: str = Query("nume"),
    q: str = Query("", max_length=80),
    grup: str = Query("", max_length=40),
    judet: str = Query("", pattern=r"^(|[1-9]|[1-3]\d|4[0-3])$"),
    fosti: bool = Query(False),
    conn: Connection = Depends(get_conn),
):
    county = int(judet) if judet else None  # forms send an empty value for "all"
    leg = CONF.legislature
    # 'Mandat încetat' lists only the members whose mandate ended during the legislature.
    rows = analytics.members(conn, leg, camera or None, sort, q or None, grup or None, county, in_office=not fosti)
    sections: list[tuple[str, list[dict]]] = []
    if grupare:
        key = GROUPINGS[grupare]
        buckets: dict[str, list[dict]] = {}
        for row in rows:
            label = row[key]
            if grupare == "judet":
                label = (
                    f"{row['constituency_no']}. {row['constituency']}"
                    if row["constituency_no"]
                    else "Minorități naționale"
                )
            elif grupare == "camera":
                label = filters.chamber_label(row["chamber"], plural=True)
            buckets.setdefault(label or "Fără grup", []).append(row)
        order = (
            sorted(buckets, key=lambda name: (name[0].isdigit() and int(name.split(".")[0]), name))
            if grupare == "judet"
            else sorted(buckets, key=lambda name: -len(buckets[name]))
        )
        sections = [(name, buckets[name]) for name in order]
    else:
        sections = [("", rows)]
    groups = conn.execute(
        "SELECT DISTINCT short_name FROM parl_groups WHERE legislature = %s AND short_name IS NOT NULL ORDER BY 1",
        (leg,),
    ).fetchall()
    return render(
        request,
        "members.html",
        partial="_members_results.html",
        legislature=leg,
        sections=sections,
        total=len(rows),
        medians=analytics.chamber_medians(conn, leg),
        params={
            "camera": camera,
            "grupare": grupare,
            "sort": sort,
            "q": q,
            "grup": grup,
            "judet": judet,
            "fosti": fosti,
        },
        sorts=analytics.SORTS,
        groups=[row["short_name"] for row in groups],
        constituencies=constituencies(conn),
    )


@app.get("/parlamentar/{member_id}", response_class=HTMLResponse)
def member_page(request: Request, member_id: str, conn: Connection = Depends(get_conn)):
    member = analytics.member(conn, member_id)
    if member is None:
        raise HTTPException(404, "Parlamentar negăsit")
    details = conn.execute("SELECT * FROM members WHERE id = %s", (member_id,)).fetchone()
    initiatives = conn.execute(
        """SELECT b.id, b.number, b.title, b.status, b.law,
               b.last_event_on FROM bill_initiators i JOIN bills b ON b.id = i.bill_id
           WHERE i.member_ref = %s ORDER BY b.registered_on DESC NULLS LAST""",
        (member_id,),
    ).fetchall()
    return render(
        request,
        "member.html",
        m=member,
        d=details,
        groups=conn.execute(
            "SELECT * FROM group_memberships WHERE member_id = %s ORDER BY start_date NULLS FIRST, seq", (member_id,)
        ).fetchall(),
        parties=conn.execute(
            "SELECT * FROM party_memberships WHERE member_id = %s ORDER BY start_date NULLS FIRST, seq", (member_id,)
        ).fetchall(),
        roles=conn.execute(
            "SELECT * FROM group_roles WHERE member_id = %s ORDER BY start_date NULLS FIRST", (member_id,)
        ).fetchall(),
        committees=conn.execute(
            """SELECT c.name, c.url, cm.role,
                   cm.start_date FROM committee_memberships cm JOIN committees c ON c.id = cm.committee_id
               WHERE cm.member_id = %s ORDER BY c.name""",
            (member_id,),
        ).fetchall(),
        votes=analytics.member_votes(conn, member_id, limit=10),
        initiatives=initiatives,
        questions=conn.execute(
            "SELECT * FROM questions WHERE member_id = %s ORDER BY asked_on DESC NULLS LAST LIMIT 50", (member_id,)
        ).fetchall(),
        speeches=conn.execute(
            "SELECT * FROM speeches WHERE member_id = %s ORDER BY sitting_on DESC NULLS LAST, seq LIMIT 50",
            (member_id,),
        ).fetchall(),
        motions=conn.execute(
            "SELECT mo.* FROM motions mo JOIN motion_signatures s ON s.motion_id = mo.id WHERE s.member_id = %s",
            (member_id,),
        ).fetchall(),
        medians=analytics.chamber_medians(conn, member["legislature"]).get(member["chamber"]),
        mandates=analytics.mandates(conn, member_id),
    )


@app.get("/parlamentar/{member_id}/voturi", response_class=HTMLResponse)
def member_votes_page(
    request: Request, member_id: str, pagina: int = Query(1, ge=1, le=1000), conn: Connection = Depends(get_conn)
):
    member = analytics.member(conn, member_id)
    if member is None:
        raise HTTPException(404, "Parlamentar negăsit")
    votes = analytics.member_votes(conn, member_id, limit=100, offset=(pagina - 1) * 100)
    return render(request, "member_votes.html", m=member, votes=votes, page=pagina)


@app.get("/legi", response_class=HTMLResponse)
def bills_page(
    request: Request,
    q: str = Query("", max_length=120),
    stadiu: str = Query("", max_length=30),
    ordonante: bool = Query(False),
    pagina: int = Query(1, ge=1, le=1000),
    conn: Connection = Depends(get_conn),
):
    rows = analytics.bills(conn, q or None, stadiu or None, ordonante, limit=50, offset=(pagina - 1) * 50)
    return render(
        request,
        "bills.html",
        partial="_bills_results.html",
        bills=rows,
        stages=analytics.bill_stage_counts(conn),
        params={"q": q, "stadiu": stadiu, "ordonante": ordonante},
        page=pagina,
    )


@app.get("/lege/{bill_id}", response_class=HTMLResponse)
def bill_page(request: Request, bill_id: str, conn: Connection = Depends(get_conn)):
    bill = conn.execute("SELECT * FROM bills WHERE id = %s", (bill_id,)).fetchone()
    if bill is None:
        raise HTTPException(404, "Proiect negăsit")
    initiators = conn.execute(
        """SELECT i.*, m.id AS member_id FROM bill_initiators i LEFT JOIN members m ON m.id = i.member_ref
           WHERE i.bill_id = %s ORDER BY i.seq""",
        (bill_id,),
    ).fetchall()
    # The same bill in the other chamber's records (matched by Senate number).
    other = (
        conn.execute(
            "SELECT * FROM bills WHERE senate_key = %s AND chamber <> %s ORDER BY chamber LIMIT 1",
            (bill["senate_key"], bill["chamber"]),
        ).fetchone()
        if bill["senate_key"]
        else None
    )
    senate = other if bill["chamber"] == "cd" else bill
    return render(
        request,
        "bill.html",
        b=bill,
        other=other,
        stage=analytics.bill_stage(bill),
        summary=conn.execute("SELECT * FROM bill_summaries WHERE bill_id = %s", (bill_id,)).fetchone(),
        initiators=initiators,
        events=conn.execute("SELECT * FROM bill_events WHERE bill_id = %s ORDER BY seq", (bill_id,)).fetchall(),
        senate_events=(
            conn.execute("SELECT * FROM bill_events WHERE bill_id = %s ORDER BY seq", (senate["id"],)).fetchall()
            if senate and bill["chamber"] == "cd"
            else []
        ),
        senate=senate,
        documents=conn.execute("SELECT * FROM bill_documents WHERE bill_id = %s ORDER BY seq", (bill_id,)).fetchall(),
        votes=conn.execute(
            """SELECT * FROM votes WHERE bill_id = %s OR bill_id = %s OR (chamber = 'senat' AND bill_ref = %s)
               ORDER BY voted_at, seq NULLS FIRST""",
            (bill_id, other["id"] if other else None, bill["senate_key"]),
        ).fetchall(),
        agenda=conn.execute(
            """SELECT a.id, a.chamber, a.title, a.first_day, i.position
               FROM agenda_items i JOIN agendas a ON a.id = i.agenda_id
               WHERE i.bill_id = %s OR i.bill_id = %s OR (a.chamber = 'senat' AND i.bill_ref = %s)
               ORDER BY a.first_day DESC NULLS LAST""",
            (bill_id, other["id"] if other else None, bill["senate_key"]),
        ).fetchall(),
    )


@app.get("/voturi", response_class=HTMLResponse)
def votes_page(
    request: Request,
    q: str = Query("", max_length=120),
    camera: str = Query("", pattern="^(cd|senat)?$"),
    pagina: int = Query(1, ge=1, le=1000),
    conn: Connection = Depends(get_conn),
):
    params = {"limit": 50, "offset": (pagina - 1) * 50, "q": analytics.ts_query(q) or "''", "chamber": camera}
    where = "NOT v.is_test" + (" AND v.search @@ to_tsquery('simple', %(q)s)" if q else "")
    where += " AND v.chamber = %(chamber)s" if camera else ""
    rows = conn.execute(
        f"""SELECT v.*, {analytics.VOTE_BILL} FROM votes v {analytics.VOTE_BILL_JOIN} WHERE {where}
            ORDER BY v.voted_at DESC, v.seq DESC NULLS LAST LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()
    return render(
        request, "votes.html", partial="_votes_results.html", votes=rows, params={"q": q, "camera": camera}, page=pagina
    )


@app.get("/vot/{vote_id}", response_class=HTMLResponse)
def vote_page(request: Request, vote_id: str, conn: Connection = Depends(get_conn)):
    vote = conn.execute("SELECT * FROM votes WHERE id = %s", (vote_id,)).fetchone()
    if vote is None:
        raise HTTPException(404, "Vot negăsit")
    records = conn.execute(
        # The source writes 'PNL (afiliat)' and 'PNL(afiliat)' in the same vote; one spelling per group here.
        r"""SELECT r.*, regexp_replace(r.group_code, '\s*\(', ' (') AS group_label,
                  coalesce(m.name, r.member_name) AS name, m.id AS profile
           FROM vote_records r LEFT JOIN members m ON m.id = r.member_id
           WHERE r.vote_id = %s ORDER BY group_label, r.member_name""",
        (vote_id,),
    ).fetchall()
    absent = (
        conn.execute(
            """SELECT m.id, m.name, coalesce(g.short_name, 'Fără grup') AS group_short
           FROM members m LEFT JOIN parl_groups g ON g.id = m.group_id
           WHERE m.chamber = %(chamber)s AND m.id NOT IN (SELECT member_id FROM vote_records WHERE vote_id = %(id)s)
             AND %(day)s >= coalesce(m.validated_on, make_date(m.legislature, 12, 1))
             AND (m.mandate_end IS NULL OR %(day)s <= m.mandate_end)
             AND %(day)s < make_date(m.legislature + 4, 12, 21)
           ORDER BY m.sort_name""",
            {"chamber": vote["chamber"], "id": vote_id, "day": vote["voted_at"].date()},
        ).fetchall()
        if vote["has_nominal"]
        else []
    )
    bill = (
        conn.execute("SELECT id, number, title FROM bills WHERE id = %s", (vote["bill_id"],)).fetchone()
        if vote["bill_id"]
        else None
    )
    return render(
        request,
        "vote.html",
        v=vote,
        records=records,
        breakdown=analytics.vote_breakdown(conn, vote_id),
        absent=absent,
        bill=bill,
    )


@app.get("/ordinea-de-zi", response_class=HTMLResponse)
def agenda_page(
    request: Request,
    id: str | None = Query(None, max_length=60),
    camera: str = Query("cd", pattern="^(cd|senat)$"),
    conn: Connection = Depends(get_conn),
):
    if id and id.startswith("senat-"):
        camera = "senat"
    agendas = conn.execute(
        "SELECT * FROM agendas WHERE chamber = %s ORDER BY first_day DESC NULLS LAST, id DESC LIMIT 30", (camera,)
    ).fetchall()
    current = next((a for a in agendas if a["id"] == id), agendas[0] if agendas else None)
    if id and current and current["id"] != id:
        current = conn.execute("SELECT * FROM agendas WHERE id = %s", (id,)).fetchone() or current
    items = (
        conn.execute(
            """SELECT i.*, b.status, b.law FROM agenda_items i LEFT JOIN bills b ON b.id = i.bill_id
               WHERE i.agenda_id = %s ORDER BY i.seq""",
            (current["id"],),
        ).fetchall()
        if current
        else []
    )
    return render(request, "agenda.html", agendas=agendas, current=current, items=items, camera=camera)


@app.get("/cauta", response_class=HTMLResponse)
def search_page(request: Request, q: str = Query("", max_length=120), conn: Connection = Depends(get_conn)):
    results = analytics.search(conn, q, CONF.legislature) if q.strip() else None
    return render(request, "search.html", q=q, results=results)


@app.get("/traseism", response_class=HTMLResponse)
def switches_page(request: Request, conn: Connection = Depends(get_conn)):
    return render(
        request,
        "switches.html",
        flows=analytics.group_flows(conn, CONF.legislature),
        members=analytics.switchers(conn, CONF.legislature),
        groups=analytics.group_summary(conn, CONF.legislature),
    )


@app.get("/ordonante", response_class=HTMLResponse)
def ordinances_page(request: Request, conn: Connection = Depends(get_conn)):
    return render(
        request,
        "ordinances.html",
        stats=analytics.ordinance_stats(conn),
        bills=analytics.bills(conn, ordinance=True, limit=200),
        ccr=analytics.ccr_events(conn),
        tacit=analytics.tacit_adoptions(conn),
    )


@app.get("/invata", response_class=HTMLResponse)
@app.get("/invata/{slug}", response_class=HTMLResponse)
def learn_page(request: Request, slug: str = "rolul-parlamentului"):
    page = LEARN_PAGES.get(slug)
    if page is None:
        raise HTTPException(404, "Pagină negăsită")
    return render(request, "learn.html", page=page, slug=slug, pages=LEARN_PAGES)


@app.get("/metodologie", response_class=HTMLResponse)
def methodology_page(request: Request, conn: Connection = Depends(get_conn)):
    runs = conn.execute("SELECT * FROM ingest_log ORDER BY id DESC LIMIT 15").fetchall()
    return render(request, "methodology.html", runs=runs)


@app.get("/date-deschise", response_class=HTMLResponse)
def open_data_page(request: Request):
    directory = exports.export_dir()
    files = [{"name": name, "path": directory / f"{name}.csv"} for name in exports.TABLES]
    files = [
        {
            **item,
            "size": item["path"].stat().st_size,
            "updated": dt.datetime.fromtimestamp(item["path"].stat().st_mtime),
        }
        for item in files
        if item["path"].exists()
    ]
    return render(request, "open_data.html", files=files, tables=list(exports.TABLES))


@app.get("/date-deschise/{name}.csv")
def open_data_file(name: str):
    if name not in exports.TABLES:
        raise HTTPException(404)
    path = exports.export_dir() / f"{name}.csv"
    if not path.exists():
        raise HTTPException(404, "Exportul nu a fost generat încă")
    return FileResponse(path, media_type="text/csv; charset=utf-8", filename=f"{name}.csv")


@app.get("/foto/{member_id}")
def photo(member_id: str, marime: str = Query("mic", pattern="^(mic|mare)$"), conn: Connection = Depends(get_conn)):
    path = photos.photo_path(member_id, marime)
    if re.fullmatch(r"[a-z]+-\d{4}-[0-9a-f-]+", member_id) and path.exists():
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})
    row = conn.execute("SELECT photo_url FROM members WHERE id = %s", (member_id,)).fetchone()
    if row is None or not row["photo_url"]:
        return RedirectResponse("/static/avatar.svg")
    return RedirectResponse(row["photo_url"])


@app.get("/sanatate")
def health(conn: Connection = Depends(get_conn)):
    conn.execute("SELECT 1")
    return {"status": "ok"}


# --- JSON API -----------------------------------------------------------------------------------


@app.get("/api/v1/parlamentari", tags=["API"])
def api_members(
    camera: str = Query("", pattern="^(|cd|senat)$"),
    sort: str = Query("nume"),
    fosti: bool = Query(False),
    conn: Connection = Depends(get_conn),
):
    """Toți parlamentarii legislaturii curente, cu indicatorii de activitate."""
    return analytics.members(conn, CONF.legislature, camera or None, sort, in_office=None if fosti else True)


@app.get("/api/v1/parlamentari/{member_id}", tags=["API"])
def api_member(member_id: str, conn: Connection = Depends(get_conn)):
    member = analytics.member(conn, member_id)
    if member is None:
        raise HTTPException(404)
    member["grupuri"] = conn.execute(
        "SELECT * FROM group_memberships WHERE member_id = %s ORDER BY seq", (member_id,)
    ).fetchall()
    member["partide"] = conn.execute(
        "SELECT * FROM party_memberships WHERE member_id = %s ORDER BY seq", (member_id,)
    ).fetchall()
    member["voturi_recente"] = analytics.member_votes(conn, member_id, limit=100)
    member["cv"] = conn.execute("SELECT cv FROM members WHERE id = %s", (member_id,)).fetchone()["cv"]
    return member


@app.get("/api/v1/proiecte", tags=["API"])
def api_bills(
    q: str = Query("", max_length=120),
    stadiu: str = Query("", max_length=30),
    pagina: int = Query(1, ge=1, le=1000),
    conn: Connection = Depends(get_conn),
):
    return analytics.bills(conn, q or None, stadiu or None, limit=100, offset=(pagina - 1) * 100)


@app.get("/api/v1/proiecte/{bill_id}", tags=["API"])
def api_bill(bill_id: str, conn: Connection = Depends(get_conn)):
    bill = conn.execute("SELECT * FROM bills WHERE id = %s", (bill_id,)).fetchone()
    if bill is None:
        raise HTTPException(404)
    bill.pop("search", None)
    bill["initiatori"] = conn.execute(
        "SELECT * FROM bill_initiators WHERE bill_id = %s ORDER BY seq", (bill_id,)
    ).fetchall()
    bill["parcurs"] = conn.execute("SELECT * FROM bill_events WHERE bill_id = %s ORDER BY seq", (bill_id,)).fetchall()
    bill["voturi"] = conn.execute(
        "SELECT id, voted_at, description, yes, no, abstain FROM votes WHERE bill_id = %s", (bill_id,)
    ).fetchall()
    return bill


@app.get("/api/v1/voturi/{vote_id}", tags=["API"])
def api_vote(vote_id: str, conn: Connection = Depends(get_conn)):
    vote = conn.execute("SELECT * FROM votes WHERE id = %s", (vote_id,)).fetchone()
    if vote is None:
        raise HTTPException(404)
    vote.pop("search", None)
    vote["nominal"] = conn.execute(
        "SELECT member_id, group_code, choice FROM vote_records WHERE vote_id = %s", (vote_id,)
    ).fetchall()
    return vote


# --- RSS ----------------------------------------------------------------------------------------


def rss(xml: str) -> Response:
    return Response(xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/feed/proiecte.xml")
def feed_bills(request: Request, conn: Connection = Depends(get_conn)):
    return rss(feeds.bills_feed(conn, str(request.base_url)))


@app.get("/feed/voturi.xml")
def feed_votes(request: Request, conn: Connection = Depends(get_conn)):
    return rss(feeds.votes_feed(conn, str(request.base_url)))


@app.get("/feed/parlamentar/{member_id}.xml")
def feed_member(request: Request, member_id: str, conn: Connection = Depends(get_conn)):
    xml = feeds.member_feed(conn, str(request.base_url), member_id)
    if xml is None:
        raise HTTPException(404)
    return rss(xml)


@app.get("/feed/lege/{bill_id}.xml")
def feed_bill(request: Request, bill_id: str, conn: Connection = Depends(get_conn)):
    xml = feeds.bill_feed(conn, str(request.base_url), bill_id)
    if xml is None:
        raise HTTPException(404)
    return rss(xml)


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith(("/api/", "/feed/")):
        return Response('{"detail": "not found"}', status_code=404, media_type="application/json")
    detail = getattr(exc, "detail", None) or "Pagina nu există"
    return templates.TemplateResponse(
        request, "error.html", {"message": detail, "legislature": CONF.legislature}, status_code=404
    )
