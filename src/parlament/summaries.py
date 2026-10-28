"""Plain-language summaries of bills, written by a local open-weight language model (ADR 0006).

The model reads the bill's title, the opening of its explanatory memorandum (`bill_texts`) and the part stating
the proposed change, and writes two or three plain sentences. It runs on the maintainer's machine behind an
OpenAI-compatible endpoint (for example `mlx_lm.server`); nothing is sent to a third party. Summaries are labelled
as generated, name the model and link the memorandum they come from. Bills without a text memorandum get none.
"""

import re

import httpx
import psycopg

from parlament import db
from parlament.config import settings

SOURCE = "summaries"
CONTEXT_CHARS = 1500  # the memorandum opens with the problem the bill answers
PROPOSAL_CHARS = 4500  # ... and states the change in a section like 'Schimbări preconizate'
# Where the proposed change is described. Many memoranda are scans with an OCR text layer that misreads letters
# ('Schimbdri preconlzate', 'baz5'), so the words are matched loosely; the first match wins.
PROPOSAL = re.compile(
    r"schimb\S*\s+precon\S*|principiile\s+de\s+baz\S*|(?:act|proiect)\S*\s+(?:normativ\s+)?propune"
    r"|prezent(?:a|ul)\s+(?:propunere|proiect)",
    re.I,
)

SYSTEM = (
    "Ești un redactor care explică proiectele de lege pe înțelesul tuturor. Scrii în limba română, cu diacritice, "
    "propoziții scurte și cuvinte obișnuite. Folosești doar informațiile din textul primit: nu inventa cifre, "
    "nume, date sau efecte care nu apar acolo."
)
PROMPT = (
    "Titlul proiectului: {title}\n\nSituația de acum, după inițiator:\n{context}\n\n"
    "Ce propune proiectul:\n{proposal}\n\n"
    "Scrie 2–3 propoziții (cel mult 60 de cuvinte): ce propune proiectul și pe cine privește. "
    "Prima propoziție începe cu „Proiectul propune”. Descrie doar propunerea, nu situația de acum, "
    "și nu face presupuneri despre efecte („ar putea”). Fără introducere și fără titlu."
)


def excerpts(text: str) -> tuple[str, str]:
    """(context, proposal): the opening of the memorandum and the part that states the proposed change."""
    match = PROPOSAL.search(text, CONTEXT_CHARS // 2)
    start = match.start() if match else CONTEXT_CHARS
    return text[: min(start, CONTEXT_CHARS)], text[start : start + PROPOSAL_CHARS]


def pending(conn: psycopg.Connection, model: str) -> list[dict]:
    """Bills with a memorandum text and no summary from this model yet; most recently active first."""
    return conn.execute(
        """SELECT b.id, b.title, x.url, x.text FROM bill_texts x JOIN bills b ON b.id = x.bill_id
           WHERE x.text IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM bill_summaries s WHERE s.bill_id = b.id AND s.model = %s)
           ORDER BY b.last_event_on DESC NULLS LAST, b.id""",
        (model,),
    ).fetchall()


def tidy(answer: str) -> str | None:
    """The model's answer without markdown or a leading label; None when it is empty or obviously off."""
    text = re.sub(r"[*#_`]+", "", answer).strip()
    text = re.sub(r"^(?:rezumat|explicație|pe scurt)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text if 40 <= len(text) <= 900 else None


def summarize(conn: psycopg.Connection, client: httpx.Client | None = None, limit: int | None = None) -> int:
    conf = settings()
    client = client or httpx.Client(base_url=conf.llm_url, timeout=300)
    bills = pending(conn, conf.llm_label)
    log = db.log_start(conn, SOURCE, f"summaries {conf.llm_label} ({len(bills)})")
    count, errors = 0, []
    for bill in bills[:limit] if limit else bills:
        messages = [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": PROMPT.format(
                    title=bill["title"], **dict(zip(("context", "proposal"), excerpts(bill["text"]), strict=True))
                ),
            },
        ]
        try:
            response = client.post(
                "/chat/completions",
                json={"model": conf.llm_model, "messages": messages, "temperature": 0, "max_tokens": 220},
            )
            response.raise_for_status()
            summary = tidy(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
            errors.append(f"{bill['id']}: {error}")
            if isinstance(error, httpx.TransportError):
                break  # the model server is down: stop instead of failing every bill
            continue
        if summary is None:
            errors.append(f"{bill['id']}: unusable answer")
            continue
        with conn.transaction():
            conn.execute(
                """INSERT INTO bill_summaries (bill_id, summary, model, source_url) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (bill_id) DO UPDATE SET summary = EXCLUDED.summary, model = EXCLUDED.model,
                       source_url = EXCLUDED.source_url, generated_at = now()""",
                (bill["id"], summary, conf.llm_label, bill["url"]),
            )
        count += 1
    db.log_end(conn, log, "ok" if not errors else "partial", count, "\n".join(errors[:20]) or None)
    return count
