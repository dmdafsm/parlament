"""Text of each bill's explanatory memorandum (expunerea de motive), the input of the plain-language summaries.

Only bills that have a page on the site are covered: Chamber bills, and Senate bills that never reached the
Chamber. The memorandum is listed among the bill's documents on both chambers' pages; the senat.ro copy is
preferred (senat.ro answers more reliably). Scanned PDFs have no text layer and are stored with NULL text;
`ocr` reads them later with Tesseract (the cdep.ro copies are all scans without a text layer).
"""

import re
import subprocess
import tempfile
from pathlib import Path

import psycopg

from parlament import db
from parlament.fetch import Fetcher, FetchError
from parlament.parsing import ParseError, pdf_text

SOURCE = "bill-texts"
MAX_CHARS = 20000  # the summary reads the beginning of the memorandum; the rest stays on the official PDF
MIN_CHARS = 200  # less than this is a scanned page with a stray text line, not a text layer


def pending(conn: psycopg.Connection) -> list[dict]:
    """Bills with a page on the site and a memorandum, not fetched yet; most recently active first."""
    return conn.execute(
        """SELECT b.id,
               (SELECT d.url FROM bills t JOIN bill_documents d ON d.bill_id = t.id
                WHERE (t.id = b.id OR (b.senate_key IS NOT NULL AND t.senate_key = b.senate_key))
                    AND d.title ILIKE 'expunerea de motive%%' AND d.url ILIKE '%%.pdf'
                ORDER BY (d.url LIKE '%%senat.ro%%') DESC, d.seq LIMIT 1) AS url
           FROM bills b
           WHERE (b.chamber = 'cd' OR NOT EXISTS (
                     SELECT 1 FROM bills c WHERE c.chamber = 'cd' AND c.senate_key = b.senate_key))
               AND NOT EXISTS (SELECT 1 FROM bill_texts x WHERE x.bill_id = b.id)
           ORDER BY b.last_event_on DESC NULLS LAST, b.id"""
    ).fetchall()


def _site(url: str) -> str:
    return "senat" if "senat.ro" in url else "cdep"


def clean_text(text: str) -> str | None:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text[:MAX_CHARS] if len(text) >= MIN_CHARS else None


def ingest(conn: psycopg.Connection, fetcher: Fetcher, limit: int | None = None, site: str = "all") -> int:
    """Fetch pending memoranda; `site` ('senat' or 'cdep') limits them to one site, e.g. while the other is down."""
    bills = [bill for bill in pending(conn) if bill["url"] and site in ("all", _site(bill["url"]))]
    # log_start commits, so each bill below is its own transaction and survives an interrupted run.
    log = db.log_start(conn, SOURCE, f"memoranda ({len(bills)})")
    count, errors = 0, []
    for bill in bills[:limit] if limit else bills:
        try:
            text = clean_text(pdf_text(fetcher.get_bytes(_site(bill["url"]), bill["url"])))
        except (FetchError, ParseError) as error:
            errors.append(f"{bill['id']}: {error}")
            continue
        with conn.transaction():
            conn.execute(
                """INSERT INTO bill_texts (bill_id, url, text) VALUES (%s, %s, %s)
                   ON CONFLICT (bill_id) DO UPDATE SET url = EXCLUDED.url, text = EXCLUDED.text, fetched_at = now()""",
                (bill["id"], bill["url"], text),
            )
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count


OCR_PAGES = 8  # enough for MAX_CHARS; the rest of a long memorandum is not summarised anyway


def recognize(content: bytes, pages: int = OCR_PAGES) -> str:
    """Text of a scanned PDF, read by Tesseract (Romanian) from its first `pages` pages rendered at 300 dpi.

    Needs the `ocr` extra (pypdfium2) and the `tesseract` program with the Romanian data; it runs on the
    maintainer's machine, like the summaries, not in the containers."""
    import pypdfium2

    document = pypdfium2.PdfDocument(content)
    texts = []
    with tempfile.TemporaryDirectory() as folder:
        for number in range(min(pages, len(document))):
            image = Path(folder) / f"{number}.png"
            document[number].render(scale=300 / 72, grayscale=True).to_pil().save(image)
            result = subprocess.run(
                ["tesseract", str(image), "-", "-l", "ron"], capture_output=True, text=True, check=True, timeout=300
            )
            texts.append(result.stdout)
    return "\n".join(texts)


def scanned(conn: psycopg.Connection) -> list[dict]:
    """Memoranda stored without text (scans), most recently active bills first."""
    return conn.execute(
        """SELECT x.bill_id, x.url FROM bill_texts x JOIN bills b ON b.id = x.bill_id WHERE x.text IS NULL
           ORDER BY b.last_event_on DESC NULLS LAST, b.id"""
    ).fetchall()


def ocr(conn: psycopg.Connection, fetcher: Fetcher, limit: int | None = None, read=recognize) -> int:
    """Read the scanned memoranda with OCR. The PDF comes from the raw cache when it is there (use a caching
    fetcher); a scan that still yields no text stays NULL."""
    rows = scanned(conn)
    log = db.log_start(conn, SOURCE, f"memoranda ocr ({len(rows)})")
    count, errors = 0, []
    for row in rows[:limit] if limit else rows:
        try:
            text = clean_text(read(fetcher.get_bytes(_site(row["url"]), row["url"])))
        except (FetchError, OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"{row['bill_id']}: {error}")
            continue
        if text is None:
            continue
        with conn.transaction():
            conn.execute(
                "UPDATE bill_texts SET text = %s, fetched_at = now() WHERE bill_id = %s", (text, row["bill_id"])
            )
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
