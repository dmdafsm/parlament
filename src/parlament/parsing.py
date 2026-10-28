"""Shared helpers for parsing Romanian parliamentary pages."""

import datetime as dt
import io
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

MONTHS = {
    "ian": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "iun": 6,
    "iul": 7, "aug": 8, "sep": 9, "oct": 10, "noi": 11, "nov": 11, "dec": 12,
}  # fmt: skip


class ParseError(ValueError):
    """The page does not have the expected structure (the source changed)."""


def clean(text: str | None) -> str:
    """Collapse whitespace and normalise the cedilla letters the sites mix with comma-below ones."""
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("ş", "ș").replace("Ş", "Ș").replace("ţ", "ț").replace("Ţ", "Ț")
    return re.sub(r"\s+", " ", text).strip()


def node_text(node: Node | None) -> str:
    return clean(node.text(separator=" ")) if node is not None else ""


def html(text: str) -> HTMLParser:
    return HTMLParser(text)


def query_param(url: str, name: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(name)
    return values[0] if values else None


def int_or_none(text: str | None) -> int | None:
    text = clean(text).rstrip(".")
    return int(text) if text.isdigit() else None


def parse_month_label(text: str) -> dt.date | None:
    """'sep. 2023' -> 2023-09-01 (cdep.ro publishes group/party changes with month precision)."""
    match = re.search(r"([a-zăâî]{3})[a-zăâî]*\.?\s+(\d{4})", clean(text).lower())
    if not match or match.group(1) not in MONTHS:
        return None
    return dt.date(int(match.group(2)), MONTHS[match.group(1)], 1)


def parse_long_date(text: str) -> dt.date | None:
    """'29 iul. 1952', '21 decembrie 2024' -> date."""
    match = re.search(r"(\d{1,2})\s+([a-zăâî]{3})[a-zăâî]*\.?\s+(\d{4})", clean(text).lower())
    if not match or match.group(2) not in MONTHS:
        return None
    return dt.date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))


def parse_dotted_date(text: str) -> dt.date | None:
    """'18.03.2024' or '18-03-2024' -> date."""
    match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text or "")
    if not match:
        return None
    return dt.date(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def fold(text: str) -> str:
    """Accent- and case-insensitive key for matching names across sources."""
    return slug(text).replace("-", " ")


def form_fields(page: str, leave_out: tuple[str, ...] = ()) -> dict[str, str]:
    """Hidden and text fields of an ASP.NET page's form, to submit it as the browser does on a postback link."""
    fields = {}
    for node in html(page).css("input"):
        name = node.attributes.get("name")
        if name and node.attributes.get("type") in ("hidden", "text") and name not in leave_out:
            fields[name] = node.attributes.get("value") or ""
    if "__VIEWSTATE" not in fields:
        raise ParseError("no ASP.NET form state on the page")
    return fields


def pdf_text(content: bytes) -> str:
    """Text layer of a PDF (empty for scanned documents)."""
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    except (PdfReadError, ValueError) as error:
        raise ParseError(f"unreadable PDF ({error})") from error
