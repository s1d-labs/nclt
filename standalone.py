"""Run one project without the hub, from a machine in India. Resumable; downloads the PDFs too.

Both sites answer only from India, so run this on an India pool server or the India VPS, not from abroad.

    python standalone.py nclt-nclat-judgements                 # all pages
    python standalone.py nclt-nclt-judgements --start 0 --end 50   # pages 0..49
    python standalone.py nclt-nclt-orders --out out            # two-step: listing -> detail -> PDFs

For each listing page it writes one JSON line per record to out/<project>.jsonl and stores the PDF at
out/<project>/pdf/<record-id>.pdf. It records finished pages in out/<project>.done and skips them on the
next run, so you can stop it and start it again. Use --no-pdf to collect only the records and links, then
run fetch_docs.py later.
"""
import argparse
import json
import os
import sys
import time

import requests

import crawl
from family import PROJECTS

UA = "s1d-labs scraper (https://github.com/s1d-labs)"
BY_NAME = {p["name"]: p for p in PROJECTS}


class FileHub:
    """Minimal hub stand-in: counts only, so crawl.fetch works unchanged."""
    settings = {"threads": 1, "delay_ms": 1000, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("http_error", n)

    def block(self, n=1):
        self.metric("blocked", n)


def get_pdf(hub, session, url, dest, delay):
    if os.path.exists(dest):
        return True
    data = crawl.fetch(hub, session, url, binary=True)
    time.sleep(delay)
    if not data:
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return True


def main():
    ap = argparse.ArgumentParser(description="Run one nclt-family project without the hub (India only).")
    ap.add_argument("project", choices=sorted(BY_NAME))
    ap.add_argument("--out", default="out")
    ap.add_argument("--start", type=int, default=None, help="first page index")
    ap.add_argument("--end", type=int, default=None, help="stop before this page index")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (>=1 is polite)")
    ap.add_argument("--no-pdf", action="store_true", help="store records and links only; download PDFs later with fetch_docs.py")
    a = ap.parse_args()

    p = BY_NAME[a.project]
    crawl.KIND = p["env"]["KIND"]
    crawl.SITE = p["env"]["SITE"]
    items = p["items"][a.start:a.end] if (a.start is not None or a.end is not None) else p["items"]

    os.makedirs(a.out, exist_ok=True)
    done_path = os.path.join(a.out, f"{a.project}.done")
    jsonl_path = os.path.join(a.out, f"{a.project}.jsonl")
    pdf_dir = os.path.join(a.out, a.project, "pdf")
    done = set(open(done_path).read().split()) if os.path.exists(done_path) else set()

    hub, session = FileHub(), requests.Session()
    session.headers["User-Agent"] = UA
    records = pdfs = 0
    with open(jsonl_path, "a", encoding="utf-8") as jf, open(done_path, "a") as df:
        for item in items:
            key = item["key"]
            if key in done:
                continue
            page = crawl.fetch(hub, session, item["payload"]["url"])
            time.sleep(a.delay)
            if page is None:
                print(f"{key}: listing did not load", file=sys.stderr)
                continue
            rows = emit(hub, session, jf, pdf_dir, key, page, a)
            records += rows[0]
            pdfs += rows[1]
            df.write(key + "\n")
            df.flush()
            print(f"{key}: {rows[0]} records, {rows[1]} pdfs (total {records}/{pdfs})", file=sys.stderr)
    print(f"done: {records} records, {pdfs} pdfs -> {jsonl_path}")


def emit(hub, session, jf, pdf_dir, key, page, a):
    """Parse one listing page, write records, download PDFs. Returns (records, pdfs)."""
    n_rec = n_pdf = 0
    if crawl.KIND == "nclt_orders":
        for row in crawl.parse_nclt_orders_listing(page, crawl.SITE):
            if not row.get("detail_url"):
                continue
            detail = crawl.fetch(hub, session, row["detail_url"])
            time.sleep(a.delay)
            if detail is None:
                continue
            for i, od in enumerate(crawl.parse_nclt_interim_order(detail, crawl.SITE)):
                rid = crawl._rid(od["pdf_url"], row["case_number"] + od["date"] + str(i))
                rec = {**row, **od, "record_id": rid}
                stored = False
                if not a.no_pdf and od.get("pdf_url"):
                    stored = get_pdf(hub, session, od["pdf_url"], os.path.join(pdf_dir, rid + ".pdf"), a.delay)
                rec["pdf_stored"] = stored
                jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_rec += 1
                n_pdf += int(stored)
        jf.flush()
        return n_rec, n_pdf
    for rid, rec in crawl.parse(page):
        rec = {**rec, "record_id": rid, "page": key}
        stored = False
        if not a.no_pdf and rec.get("pdf_url"):
            stored = get_pdf(hub, session, rec["pdf_url"], os.path.join(pdf_dir, rid + ".pdf"), a.delay)
        rec["pdf_stored"] = stored
        jf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n_rec += 1
        n_pdf += int(stored)
    jf.flush()
    return n_rec, n_pdf


if __name__ == "__main__":
    main()
