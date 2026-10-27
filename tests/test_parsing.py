import datetime as dt

from parlament.fetch import decode
from parlament.ingest.cdep_bills import bill_key, find_bill_ref, ordinance_of
from parlament.ingest.cdep_members import member_ref_from_url, parse_period
from parlament.parsing import clean, parse_dotted_date, parse_long_date, parse_month_label


def test_dates():
    assert parse_month_label("sep. 2023") == dt.date(2023, 9, 1)
    assert parse_month_label("noi. 2021") == dt.date(2021, 11, 1)
    assert parse_month_label("nimic") is None
    assert parse_long_date("n. 29 iul. 1952") == dt.date(1952, 7, 29)
    assert parse_long_date("21 decembrie 2024") == dt.date(2024, 12, 21)
    assert parse_dotted_date("164/18.03.2024") == dt.date(2024, 3, 18)
    assert parse_dotted_date("03-06-2021") == dt.date(2021, 6, 3)


def test_periods():
    assert parse_period("- membru până în  sep. 2023") == parse_period("până în sep. 2023")
    period = parse_period("&nbsp;- din  sep. 2023 - până în  feb. 2024")
    assert (period.start, period.end) == (dt.date(2023, 9, 1), dt.date(2024, 2, 1))
    assert parse_period("").start is None


def test_clean_normalises_cedilla_letters():
    assert clean("  Naţional\xa0 Liberal ") == "Național Liberal"


def test_decode_cdep_iso_8859_2():
    assert decode("Camera Deputaţilor".encode("iso-8859-2")) == "Camera Deputaţilor"
    assert decode('<meta charset="utf-8">ș'.encode()) == '<meta charset="utf-8">ș'


def test_bill_references():
    assert bill_key("PL-x nr. 164/2024") == bill_key("PL 164/2024") == bill_key("Pl-x164 /2024") == "pl:164/2024"
    assert bill_key("PH CD 53/2017") != bill_key("PL-x 53/2017")
    assert bill_key("vot test") is None
    assert find_bill_ref("PL-x 356/2016 - Vot final adoptare") == "PL-x 356/2016"
    assert find_bill_ref("vacantarea locului de deputat (PH CD 55/2017)") == "PH CD 55/2017"


def test_ordinance_detection():
    title = "Proiectul de Lege pentru aprobarea Ordonanţei de urgenţă a Guvernului nr.224/2020 privind sprijinul"
    assert ordinance_of(title) == "OUG 224/2020"
    assert ordinance_of("Lege pentru respingerea Ordonanței Guvernului nr. 7/2019") == "OG 7/2019"
    nested = (
        "Proiect de Lege privind aprobarea Ordonanței de urgențã a Guvernului nr.10/2021 pentru modificarea "
        "Ordonanței de urgență a Guvernului nr.224/2020 privind sprijinul"
    )
    assert ordinance_of(nested) == "OUG 10/2021"
    # Mentioning an ordinance is not approving one.
    assert ordinance_of("Lege pentru modificarea art. 2 din Ordonanța de urgență a Guvernului nr. 1/2020") is None


def test_member_refs():
    assert member_ref_from_url("/pls/parlam/structura2015.mp?idm=273&leg=2020&cam=2") == "cd-2020-273"
    assert member_ref_from_url("/pls/parlam/structura2015.mp?idm=57&leg=2020&cam=1") == "senat-2020-57"
    assert member_ref_from_url("/pls/parlam/structura2015.gp?idg=1") is None
