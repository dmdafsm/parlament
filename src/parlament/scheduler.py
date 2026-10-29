"""Periodic collection in one process (no daemon framework): a loop that runs due jobs and sleeps.

Jobs and cadence (Bucharest time):
- every weekday at 21:00: recent votes and agendas of both chambers, and refresh of bills still in debate
- every Sunday at 03:00: all MP profiles (with CVs) and activity lists, new stenogram texts (both chambers),
  new explanatory memoranda, open-data CSV export and, with a GitHub token, the data release
"""

import datetime as dt
import logging
import time
import traceback

from parlament import analytics, db, exports, releases
from parlament.config import settings
from parlament.fetch import BlockedError, Fetcher
from parlament.ingest import (
    bill_texts,
    cdep_activity,
    cdep_agenda,
    cdep_bills,
    cdep_members,
    cdep_steno,
    cdep_votes,
    senat_activity,
    senat_agenda,
    senat_bills,
    senat_members,
    senat_steno,
    senat_votes,
)

log = logging.getLogger("parlament.scheduler")


def daily(conn, fetcher) -> None:
    today = dt.date.today()
    cdep_votes.ingest_days(conn, fetcher, cdep_votes.sitting_days(today - dt.timedelta(days=3), today))
    cdep_votes.fill_subjects(conn, fetcher)
    _, idps = cdep_agenda.ingest(conn, fetcher, [None])
    pending = [
        row["source_id"]
        for row in conn.execute(
            """SELECT source_id FROM bills WHERE law IS NULL AND last_event_on > current_date - 30
               ORDER BY last_event_on DESC"""
        )
    ]
    cdep_bills.ingest(conn, fetcher, sorted(set(idps) | set(pending)))
    cdep_bills.relink(conn)
    _, codes = senat_votes.ingest(conn, fetcher, today - dt.timedelta(days=7), today, settings().legislature)
    _, agenda_codes = senat_agenda.ingest(
        conn, fetcher, cdep_votes.sitting_days(today - dt.timedelta(days=3), today + dt.timedelta(days=7))
    )
    senat_bills.ingest(conn, fetcher, codes + agenda_codes, refresh_days=30)


def weekly(conn, fetcher) -> None:
    leg = settings().legislature
    cdep_members.ingest(conn, fetcher, leg)
    senat_members.ingest(conn, fetcher, leg)
    senat_activity.ingest(conn, fetcher, leg)
    _, idps = cdep_activity.ingest(conn, fetcher, leg)
    cdep_bills.ingest(conn, fetcher, sorted(set(idps)), refresh_days=30)
    cdep_bills.relink(conn)
    cdep_steno.ingest(conn, fetcher)
    senat_steno.ingest(conn, fetcher, leg)
    bill_texts.ingest(conn, fetcher)
    analytics.refresh(conn)  # the exports read the indicators
    exports.write_all(conn)
    if settings().github_token:  # the weekly data release on GitHub (ADR 0008)
        log.info("data release %s", releases.release(conn, dt.date.today()) or "already published")


def due(now: dt.datetime, last: dict[str, dt.date]) -> list[str]:
    jobs = []
    if now.weekday() < 5 and now.hour >= 21 and last.get("daily") != now.date():
        jobs.append("daily")
    if now.weekday() == 6 and now.hour >= 3 and last.get("weekly") != now.date():
        jobs.append("weekly")
    return jobs


def run(once: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with db.connect() as conn:
        db.migrate(conn)
        analytics.ensure_overview(conn)
    last: dict[str, dt.date] = {}
    while True:
        now = dt.datetime.now()
        jobs = ["daily", "weekly"] if once else due(now, last)
        for job in jobs:
            log.info("start %s", job)
            try:
                with db.connect() as conn, Fetcher() as fetcher:
                    {"daily": daily, "weekly": weekly}[job](conn, fetcher)
                log.info("done %s", job)
            except BlockedError as error:  # a bot check: stop this job, try again at the next scheduled run
                log.error("job %s stopped: %s", job, error)
                with db.connect() as conn:
                    db.close_running(conn, "blocked", str(error))
            except Exception:  # keep the loop alive; the failure is logged and in ingest_log
                log.error("job %s failed:\n%s", job, traceback.format_exc())
            try:  # pages show the indicators of whatever was stored, also after a stopped job
                with db.connect() as conn:
                    analytics.refresh(conn)
            except Exception:
                log.error("indicators not refreshed:\n%s", traceback.format_exc())
            last[job] = now.date()
        if once:
            return
        time.sleep(600)
