"""Jinja filters: Romanian dates, percentages and labels."""

import datetime as dt
import hashlib
import re
from functools import cache
from pathlib import Path

STATIC = Path(__file__).parent / "static"

MONTHS = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sep.", "oct.", "nov.", "dec."]
CHOICES = {"yes": "Pentru", "no": "Contra", "abstain": "Abținere", "present_not_voting": "Prezent, nu a votat"}
CHOICE_CLASS = {"yes": "green", "no": "red", "abstain": "amber", "present_not_voting": "grey"}


def date_ro(value: dt.date | dt.datetime | None, time: bool = False) -> str:
    if value is None:
        return "–"
    text = f"{value.day} {MONTHS[value.month - 1]} {value.year}"
    # senat.ro publishes no time of day for votes (stored as midnight): show the date only.
    if time and isinstance(value, dt.datetime) and (value.hour, value.minute) != (0, 0):
        text += f", {value:%H:%M}"
    return text


def month_ro(value: dt.date | None) -> str:
    return f"{MONTHS[value.month - 1]} {value.year}" if value else ""


def pct(value, digits: int = 0) -> str:
    if value is None:
        return "–"
    return f"{float(value) * 100:.{digits}f}%".replace(".", ",")


def chamber_label(chamber: str, plural: bool = False) -> str:
    if chamber == "cd":
        return "Deputați" if plural else "Camera Deputaților"
    return "Senatori" if plural else "Senat"


def role_label(chamber: str) -> str:
    return "deputat" if chamber == "cd" else "senator"


def number(value) -> str:
    return "–" if value is None else f"{int(value):,}".replace(",", ".")


BILL_REF = re.compile(r"\b(?:P[LH][\s-]*x?|PH\s*CD|BP)\s*\d+\s*/\s*\d{4}", re.I)


def vote_title(vote) -> str:
    """What a vote was about. A Chamber vote's subject repeats its type and number ('Vot final Respingere
    PL 480/2026 pentru ...'); the title starts at the last bill number. Otherwise the description."""
    subject = vote.get("subject")
    if not subject:
        return vote["description"]
    refs = list(BILL_REF.finditer(subject))
    return subject[refs[-1].start() :] if refs else subject


@cache
def asset(path: str) -> str:
    """'/static/app.css?v=<content hash>': static files are cached long, the hash changes with the content."""
    digest = hashlib.sha256((STATIC / path).read_bytes()).hexdigest()[:10]
    return f"/static/{path}?v={digest}"


def register(env) -> None:
    env.filters.update(
        date_ro=date_ro,
        month_ro=month_ro,
        pct=pct,
        chamber=chamber_label,
        role=role_label,
        number=number,
        vote_title=vote_title,
        choice=lambda value: CHOICES.get(value, value),
        choice_class=lambda value: CHOICE_CLASS.get(value, ""),
    )
    env.globals.update(today=dt.date.today, asset=asset)
