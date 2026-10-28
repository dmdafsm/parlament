"""A small synthetic parliament stored through the real collectors' store functions."""

import datetime as dt

from parlament.ingest import (
    cdep_agenda,
    cdep_bills,
    cdep_members,
    cdep_votes,
    senat_agenda,
    senat_bills,
    senat_members,
    senat_votes,
)
from parlament.ingest.cdep_members import ListedDeputy, Profile
from tests.conftest import fixture


def deputy(conn, idm, name, group, idg, start_group=None, validated=dt.date(2024, 12, 21)):
    listed = ListedDeputy(idm, name, 1, "Alba", idg, group)
    profile = Profile(name=name, validated_on=validated)
    profile.groups = [{"group_source_id": idg, "group_name": group, "start": start_group, "end": None}]
    profile.stats = {"speeches": (int(idm) * 2, None), "bills": (int(idm), None)}
    with conn.transaction():
        cdep_members.store_deputy(conn, 2024, listed, profile, f"https://example.invalid/{idm}")


def seed(conn) -> None:
    # Deputy 1 comes from a fixture with group/party history; 2-5 are simple.
    listed = cdep_members.parse_deputy_list(fixture("cdep_list.html"))[0]
    profile = cdep_members.parse_profile(fixture("cdep_profile.html"))
    profile.mandate_end = profile.mandate_end_note = None  # keep in office for the tests
    with conn.transaction():
        cdep_members.store_deputy(conn, 2024, listed, profile, "https://example.invalid/1")
        cdep_members.store_cv(
            conn, "cd-2024-1", cdep_members.parse_cv(fixture("cdep_cv_text.html")), "https://example.invalid/1&pag=0"
        )
    deputy(conn, "3", "Cernat Vlad", "USR", "4")
    deputy(conn, "4", "Dima Petre", "PSD", "1")
    deputy(conn, "5", "Enescu Maria", "PSD", "1")
    deputy(conn, "6", "Florea Ion", "PSD", "1", validated=dt.date(2025, 7, 1))  # validated after the vote
    with conn.transaction():
        senat_members.store_senator(
            conn,
            2024,
            senat_members.parse_senator_list(fixture("senat_list.html"))[0],
            senat_members.parse_senator_profile(fixture("senat_profile.html")),
        )
    day = dt.date(2025, 6, 23)
    records = cdep_votes.parse_nominal(fixture("cdep_vote_nominal.html"))
    with conn.transaction():
        for vote in cdep_votes.parse_day(fixture("cdep_vote_day.html"), day):
            cdep_votes.store_vote(conn, vote, None if vote["is_test"] else records)
        cdep_agenda.store_agenda(
            conn, cdep_agenda.parse_agenda(fixture("cdep_agenda.html")), "https://example.invalid/oz"
        )
        cdep_bills.store_bill(conn, "22001", cdep_bills.parse_bill(fixture("cdep_bill.html")))
    seed_senate(conn)
    conn.commit()


SENATOR = "senat-2024-aaaaaaaa-1111-2222-3333-444444444444"


def seed_senate(conn) -> None:
    """Senate votes (the first with its nominal list), a Senate-only bill, an agenda and a biography."""
    day = dt.date(2025, 6, 24)
    records = senat_votes.parse_nominal(fixture("senat_vote_nominal.html"), 2024)
    with conn.transaction():
        for vote in senat_votes.parse_day(fixture("senat_vote_day.html"), day):
            senat_votes.store_vote(conn, vote, records if vote["seq"] == 0 else None)
        cdep_bills.store_bill(
            conn,
            "901",
            senat_bills.parse_bill(fixture("senat_bill.html")),
            chamber="senat",
            url=senat_bills.bill_url("901"),
        )
        senat_agenda.store_agenda(
            conn, senat_agenda.parse_agenda(fixture("senat_agenda.html"), day), senat_agenda.agenda_url(day)
        )
        cdep_members.store_cv(
            conn, SENATOR, senat_members.parse_biography(fixture("senat_biography.html")), "https://example.invalid/s"
        )
    senat_bills.link(conn)
