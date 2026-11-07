"""Parsing tests on saved real pages: fast, no network. One saved page for every layout the sites have.

The pages in tests/pages/ were fetched from India on 2026-11-07 (both sites geo-block foreign IPs).
"""
from pathlib import Path

import crawl

PAGES = Path(__file__).parent / "pages"


def _read(name):
    return (PAGES / name).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- NCLAT judgements (/judgement-data)

def test_nclat_judgements_rows_are_deduped_to_thirty():
    # the page renders the same 30 judgements in five identical tables; parse() must return 30, not 150
    rows = crawl.parse_nclat_judgements(_read("nclat-judgement-data-p0.html"))
    assert len(rows) == 30
    ids = [r for r, _ in rows]
    assert len(set(ids)) == 30                                   # no duplicate record ids


def test_nclat_judgement_first_record():
    rows = crawl.parse_nclat_judgements(_read("nclat-judgement-data-p0.html"))
    rid, rec = rows[0]
    assert rec["tribunal"] == "NCLAT" and rec["order_type"] == "judgement"
    assert rec["case_number"] == "590/2020"
    assert rec["date"] == "28/05/2021"
    assert rec["parties"].startswith("Bank of India")
    assert rec["category"] == "Insolvency"
    assert rec["bench"] == "Court - 3"
    assert rec["judges"].startswith("Justice Anant Bijay Singh")
    assert rec["pdf_url"] == "https://nclat.nic.in/sites/default/files/migration/upload/84351351160b0b77aa3d42.pdf"
    assert rid.endswith("84351351160b0b77aa3d42.pdf")           # stable id from the PDF path


def test_nclat_judgements_every_row_has_a_pdf():
    rows = crawl.parse_nclat_judgements(_read("nclat-judgement-data-p1.html"))
    assert len(rows) == 30
    assert all(rec["pdf_url"] and rec["pdf_url"].startswith("https://nclat.nic.in/") for _, rec in rows)


# ---------------------------------------------------------------- NCLAT daily orders (/daily-order-data)

def test_nclat_daily_orders():
    rows = crawl.parse_nclat_orders(_read("nclat-daily-order-data-p0.html"))
    assert len(rows) >= 1
    rid, rec = rows[0]
    assert rec["tribunal"] == "NCLAT" and rec["order_type"] == "daily_order"
    assert rec["date"] == "04/01/2023"
    assert "Cause List" in rec["parties"]
    assert rec["pdf_url"].endswith("Supp_Causelist_ch_04.01.2023.pdf")


# ---------------------------------------------------------------- NCLT judgements (/archive/judgement-date-wise)

def test_nclt_judgements_ten_rows():
    rows = crawl.parse_nclt_judgements(_read("nclt-judgement-date-wise-p0.html"))
    assert len(rows) == 10
    assert len({r for r, _ in rows}) == 10


def test_nclt_judgement_first_record():
    rows = crawl.parse_nclt_judgements(_read("nclt-judgement-date-wise-p0.html"))
    rid, rec = rows[0]
    assert rec["tribunal"] == "NCLT" and rec["order_type"] == "judgement"
    assert rec["case_number"].startswith("IA/967/IB/2020")
    assert rec["date"] == "12/08/2021"                           # from the machine date in the date span
    assert "DBS Bank" in rec["parties"]
    assert rec["pdf_url"] == "https://nclt.gov.in/archive/sites/default/files/January2021/final-orders-pdf/IA-967-20.pdf"
    assert all(rec["pdf_url"] for _, rec in rows)


# ---------------------------------------------------------------- NCLT orders (/archive/order-judgements -> detail)

def test_nclt_orders_listing():
    rows = crawl.parse_nclt_orders_listing(_read("nclt-order-judgements-p0.html"))
    assert len(rows) == 10
    row = rows[0]
    assert row["tribunal"] == "NCLT" and row["order_type"] == "order"
    assert row["case_number"].startswith("IA(IBC)/129/KOB/2021")
    assert row["status"] == "PENDING"
    assert "SREE BHADRA" in row["parties"]
    assert row["detail_url"] == "https://nclt.gov.in/archive/interim-order/1243437"
    assert all(r["detail_url"] for r in rows)                    # every case links to its detail page


def test_nclt_interim_order_detail_gives_pdf():
    pdfs = crawl.parse_nclt_interim_order(_read("nclt-interim-order.html"))
    assert len(pdfs) >= 1
    od = pdfs[0]
    assert od["date"] == "31/08/2021"
    assert od["pdf_url"].startswith("https://nclt.gov.in/archive/sites/default/files/")
    assert od["pdf_url"].endswith(".pdf")


# ---------------------------------------------------------------- empty / malformed input

def test_empty_pages_give_nothing():
    empty = "<html><body>No results found</body></html>"
    assert crawl.parse_nclat_judgements(empty) == []
    assert crawl.parse_nclat_orders(empty) == []
    assert crawl.parse_nclt_judgements(empty) == []
    assert crawl.parse_nclt_orders_listing(empty) == []
    assert crawl.parse_nclt_interim_order(empty) == []
