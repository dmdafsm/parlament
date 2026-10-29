import json

import httpx

from parlament import summaries
from parlament.ingest import bill_texts
from tests.seed import seed

MEMO = (
    "EXPUNERE DE MOTIVE\nSecțiunea 1. Cerințele care reclamă intervenția normativă\n"
    + "Situația de acum, descrisă pe larg de inițiator. " * 20
    + "\n2. Schimbdri preconlzate\nPrezentul act normativ propune scutirea de taxă pentru exemplu."
)


class Pdfs:
    def __init__(self):
        self.urls = []

    def get_bytes(self, source, url, fresh=False):
        self.urls.append((source, url))
        return url.encode()


def test_memoranda(conn, monkeypatch):
    seed(conn)
    # The Chamber bill and the Senate-only bill both have a page and a memorandum among their documents.
    pending = {row["id"]: row["url"] for row in bill_texts.pending(conn)}
    assert pending == {
        "cd-22001": "https://www.cdep.ro/proiecte/2025/500/00/1/em501.pdf",
        "senat-901": "https://www.senat.ro/legis/PDF/2025/25L007EM.pdf",
    }
    # A scanned PDF (no text layer) is stored with NULL text, so it is neither fetched again nor summarised.
    texts = {"cdep": "", "senat": MEMO}
    monkeypatch.setattr(bill_texts, "pdf_text", lambda content: texts["senat" if b"senat" in content else "cdep"])
    fetcher = Pdfs()
    assert bill_texts.ingest(conn, fetcher, site="senat") == 1
    assert fetcher.urls == [("senat", "https://www.senat.ro/legis/PDF/2025/25L007EM.pdf")]
    assert bill_texts.ingest(conn, fetcher) == 1
    stored = {row["bill_id"]: row["text"] for row in conn.execute("SELECT * FROM bill_texts")}
    assert stored["cd-22001"] is None and stored["senat-901"].startswith("EXPUNERE DE MOTIVE")
    assert bill_texts.pending(conn) == []


def test_ocr_of_scanned_memoranda(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO bill_texts (bill_id, url, text) VALUES ('cd-22001', 'https://www.cdep.ro/scan.pdf', NULL),"
        " ('senat-901', 'https://www.senat.ro/blank.pdf', NULL)"
    )
    conn.commit()
    # The blank scan yields no text and stays NULL; the other is read and becomes summarisable.
    read = {b"https://www.cdep.ro/scan.pdf": MEMO, b"https://www.senat.ro/blank.pdf": "  \n"}
    fetcher = Pdfs()
    assert bill_texts.ocr(conn, fetcher, read=read.__getitem__) == 1
    assert fetcher.urls == [("cdep", "https://www.cdep.ro/scan.pdf"), ("senat", "https://www.senat.ro/blank.pdf")]
    stored = {row["bill_id"]: row["text"] for row in conn.execute("SELECT * FROM bill_texts")}
    assert stored["cd-22001"].startswith("EXPUNERE DE MOTIVE") and stored["senat-901"] is None
    assert [row["bill_id"] for row in bill_texts.scanned(conn)] == ["senat-901"]


def test_excerpts_find_the_proposal_in_ocr_text():
    context, proposal = summaries.excerpts(MEMO)
    assert context.startswith("EXPUNERE DE MOTIVE") and "Schimbdri" not in context
    assert proposal.startswith("Schimbdri preconlzate")


def test_tidy():
    assert summaries.tidy("**Rezumat:** Proiectul propune   scutirea de taxă pentru exemplu.") == (
        "Proiectul propune scutirea de taxă pentru exemplu."
    )
    assert summaries.tidy("Nu știu.") is None
    assert (
        summaries.tidy(
            "Proiectul propune un reprezentant al pacienților în consiliul spitalului. Asta ar putea ajuta pacienții."
        )
        == "Proiectul propune un reprezentant al pacienților în consiliul spitalului."
    )


def test_summarize(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO bill_texts (bill_id, url, text) VALUES ('senat-901', 'https://example.invalid/em.pdf', %s),"
        " ('cd-22001', 'https://example.invalid/scan.pdf', NULL)",
        (MEMO,),
    )
    conn.commit()
    requests = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = "Proiectul propune scutirea de taxă pentru exemplu. Privește pe toată lumea."
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(base_url="http://model.invalid/v1", transport=httpx.MockTransport(answer))
    assert summaries.summarize(conn, client) == 1
    prompt = requests[0]["messages"][1]["content"]
    assert "Propunere legislativă privind exemplul doi" in prompt and "Prezentul act normativ propune" in prompt
    row = conn.execute("SELECT * FROM bill_summaries WHERE bill_id = 'senat-901'").fetchone()
    assert row["summary"].startswith("Proiectul propune") and row["source_url"] == "https://example.invalid/em.pdf"
    assert row["model"] == "RoGemma3-4B-Instruct (OpenLLM-Ro)"
    # Already summarised by this model: nothing to do.
    assert summaries.summarize(conn, client) == 0
