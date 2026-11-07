"""The family's `crawl` task (see scrape.json). Try one page without the hub: python crawl.py --local <url-or-file> [kind]

The pool worker runs this with the assignment's env:
  SCRAPE_POOL_PROJECT  which project to work on
  SCRAPE_JOB_INDEX / SCRAPE_TOTAL_JOBS  this worker's slice
  SCRAPE_MAX_HOURS  time budget
  KIND   which parser/flow to use (nclt_judgements, nclt_orders, nclat_judgements, nclat_orders)
  SITE   the site base URL (e.g. https://nclt.gov.in)

Each queue item is one listing page. The task fetches the page, parses one record per order or
judgement, downloads the linked PDF, and stores the PDF in the family's bucket at <project>/pdf/<key>.pdf
(the hub signs every upload; this code never holds a storage key). NCLT orders are a two-step flow: the
listing links to a detail page (interim-order/<id>) that holds the order PDFs.

Both target sites answer only from India and use valid TLS certificates. The projects run with geo="IN"
(India pool servers). The code reports the standard counters (n_http, t_http_s, http_error, http_<code>)
that the hub uses for politeness and tracking.
"""
import gzip
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse

import requests

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
KIND = os.environ.get("KIND", "")
SITE = os.environ.get("SITE", "").rstrip("/")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"

# ------------------------------------------------------------------ parsing helpers (pure)

_TD = re.compile(r'<td[^>]*class="views-field views-field-([a-z0-9_-]+)"[^>]*>(.*?)</td>', re.S)
_ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_PDF = re.compile(r'href="([^"]+?\.pdf[^"]*)"', re.I)
_DATE_SPAN = re.compile(r'content="([0-9]{4}-[0-9]{2}-[0-9]{2})', re.I)
_STATUS = re.compile(r'\[([A-Z]+)\]')
_INTERIM = re.compile(r'href="((?:\.?/)?(?:archive/)?interim-order/\d+)"', re.I)


def _text(frag):
    """Visible text of an HTML fragment: tags stripped, entities decoded, whitespace collapsed."""
    frag = re.sub(r'(?i)<br\s*/?>', " / ", frag)
    frag = re.sub(r'<[^>]+>', " ", frag)
    return re.sub(r'\s+', " ", html.unescape(frag)).strip(" /").strip()


def _cells(row_inner):
    """Map each views-field-<suffix> cell in a table row to its inner HTML."""
    return {m.group(1): m.group(2) for m in _TD.finditer(row_inner)}


def _data_rows(page):
    """Inner HTML of every table row that is a data row (has <td> plus the counter cell)."""
    return [m.group(1) for m in _ROW.finditer(page)
            if "<td" in m.group(1) and "views-field-counter" in m.group(1)]


def _abs_url(href, base):
    """Resolve a page href (relative, ./ or absolute) to an absolute URL on the base host."""
    href = html.unescape(href.strip())
    if href.startswith(("http://", "https://")):
        return href
    return urllib.parse.urljoin(base + "/", href.lstrip("/") if href.startswith("/") else href.lstrip("./"))


def _pdf_url(frag, base):
    m = _PDF.search(frag or "")
    return _abs_url(m.group(1), base) if m else None


def _date(frag):
    """dd-mm-yyyy or dd/mm/yyyy from a cell; prefers the machine date in a date-display span."""
    m = _DATE_SPAN.search(frag or "")
    if m:
        y, mo, d = m.group(1).split("-")
        return f"{d}/{mo}/{y}"
    t = _text(frag or "")
    m = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b', t)
    return m.group(1).replace("-", "/") if m else ""


def _rid(pdf_url, fallback):
    """Stable record id from the PDF path (unique per file), else a hash of the fallback text."""
    if pdf_url:
        path = urllib.parse.urlsplit(pdf_url).path
        slug = re.sub(r'[^A-Za-z0-9._-]+', "-", urllib.parse.unquote(path).strip("/"))
        return slug[-180:].strip("-")
    return "x-" + hashlib.sha1(fallback.encode("utf-8", "replace")).hexdigest()[:24]


def _uniq(items, keyfn):
    """Drop repeated entries, keeping the first. The NCLAT listing repeats each table five times."""
    seen, out = set(), []
    for it in items:
        k = keyfn(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


# ------------------------------------------------------------------ parsers, one per listing (pure)

def parse_nclat_judgements(page, base="https://nclat.nic.in"):
    """Older NCLAT judgements listing (/judgement-data?page=N). One row per judgement, PDF inline."""
    out = []
    for inner in _data_rows(page):
        c = _cells(inner)
        if "field-final-appealno" not in c:
            continue
        pdf = _pdf_url(c.get("nothing-1", ""), base)
        rec = {
            "tribunal": "NCLAT", "order_type": "judgement",
            "case_number": _text(c.get("field-final-appealno", "")),
            "date": _date(c.get("field-final-date", "")),
            "parties": _text(c.get("nothing", "")),
            "category": _text(c.get("field-final-section", "")),
            "bench": _text(c.get("field-final-court", "")),
            "judges": _text(c.get("field-final-judge", "")),
            "pdf_url": pdf,
        }
        rec["title"] = rec["parties"]
        out.append((_rid(pdf, rec["case_number"] + rec["date"]), rec))
    return _uniq(out, lambda p: p[0])


def parse_nclat_orders(page, base="https://nclat.nic.in"):
    """Older NCLAT daily orders / cause lists (/daily-order-data). One row per daily order, PDF inline."""
    out = []
    for inner in _data_rows(page):
        c = _cells(inner)
        pdf = _pdf_url(c.get("nothing-1", ""), base)
        rec = {
            "tribunal": "NCLAT", "order_type": "daily_order",
            "case_number": _text(c.get("field-final-appealnos", "")),
            "date": _date(c.get("field-final-date", "")),
            "parties": _text(c.get("nothing", "")),
            "category": _text(c.get("field-final-section", "")),
            "bench": _text(c.get("field-final-court", "")),
            "judges": _text(c.get("field-final-judge", "")),
            "pdf_url": pdf,
        }
        rec["title"] = rec["parties"]
        out.append((_rid(pdf, rec["parties"] + rec["date"]), rec))
    return _uniq(out, lambda p: p[0])


def parse_nclt_judgements(page, base="https://nclt.gov.in"):
    """NCLT judgements archive (/archive/judgement-date-wise?page=N). One row per judgement, PDF inline."""
    out = []
    for inner in _data_rows(page):
        c = _cells(inner)
        if "field-cp-no" not in c:
            continue
        pdf = _pdf_url(c.get("field-final-orders-pdf", ""), base)
        case = _text(c.get("field-cp-no", ""))
        rec = {
            "tribunal": "NCLT", "order_type": "judgement", "bench": "",
            "case_number": case,
            "date": _date(c.get("field-final-order-date", "")),
            "parties": _text(c.get("field-name-of-petitioner", "")),
            "pdf_url": pdf,
        }
        rec["title"] = rec["parties"]
        out.append((_rid(pdf, case + rec["date"]), rec))
    return _uniq(out, lambda p: p[0])


def parse_nclt_orders_listing(page, base="https://nclt.gov.in"):
    """NCLT orders archive listing (/archive/order-judgements?page=N). One row per case.

    The PDFs are on a detail page; each row carries `detail_url` (interim-order/<id>), not a PDF.
    """
    out = []
    for inner in _data_rows(page):
        c = _cells(inner)
        if "field-cp-no" not in c:
            continue
        cp = c.get("field-cp-no", "")
        det = _INTERIM.search(cp)
        detail_url = _abs_url(det.group(1), base + "/archive") if det else None
        status = ""
        ms = _STATUS.search(cp)
        if ms:
            status = ms.group(1)
        case = _text(re.split(r'<p\b', cp, 1)[0])            # the case number is before the status / button markup
        out.append({
            "tribunal": "NCLT", "order_type": "order",
            "case_number": case, "status": status,
            "parties": _text(c.get("field-name-of-petitioner", "")),
            "listing": _text(c.get("field-final-order-date", "")),
            "detail_url": detail_url,
        })
    return _uniq(out, lambda r: r["detail_url"] or r["case_number"])


def parse_nclt_interim_order(page, base="https://nclt.gov.in"):
    """NCLT order detail page (/archive/interim-order/<id>). One entry per order PDF on the case."""
    out = []
    for inner in _data_rows(page):
        c = _cells(inner)
        pdf = _pdf_url(c.get("field-interim-order-pdf", ""), base) or _pdf_url(c.get("field-orders-pdf", ""), base)
        if not pdf:
            continue
        out.append({
            "case_number": _text(c.get("field-cp-no", "")),
            "date": _date(c.get("field-interim-order-date", "")) or _date(c.get("field-date-of-orders", "")),
            "description": _text(c.get("field-orders-paased-description", "")),
            "pdf_url": pdf,
        })
    return _uniq(out, lambda r: r["pdf_url"])


PARSERS = {
    "nclat_judgements": parse_nclat_judgements,
    "nclat_orders": parse_nclat_orders,
    "nclt_judgements": parse_nclt_judgements,
    "nclt_orders": parse_nclt_orders_listing,
}


def parse(page):
    """Dispatch to the parser named by KIND. Pure: tested on saved pages in tests/."""
    fn = PARSERS.get(KIND)
    if fn is None:
        raise SystemExit(f"KIND not set or unknown: {KIND!r} (one of {sorted(PARSERS)})")
    return fn(page, SITE or None) if SITE else fn(page)


# ------------------------------------------------------------------ fetching

def fetch(hub, session, url, binary=False):
    t = time.time()
    try:
        r = session.get(url, timeout=60, headers={"User-Agent": UA})
    except requests.RequestException:
        hub.metric("http_error")
        hub.error()
        return None
    hub.metric("n_http")
    hub.metric("t_http_s", time.time() - t)
    if r.status_code != 200:
        hub.metric(f"http_{r.status_code}")
        if r.status_code in (403, 429, 503):
            hub.block()
        return None
    if binary:
        return r.content
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def store_pdf(hub, session, pdf_url, key):
    """Download one PDF and upload it to <project>/pdf/<key>.pdf. Returns True on success."""
    data = fetch(hub, session, pdf_url, binary=True)
    if not data:
        return False
    hub.upload_many([(f"pdf/{key}.pdf", data, "application/pdf")])
    hub.metric("pdf_stored")
    return True


def polite(hub):
    time.sleep(max(1.0, hub.settings.get("delay_ms", 0) / 1000))


# ------------------------------------------------------------------ the hub task

def handle_direct(hub, session, item):
    """Listings whose rows carry the PDF link (NCLAT judgements/orders, NCLT judgements)."""
    page = fetch(hub, session, item["payload"]["url"])
    if page is None:
        hub.complete([item["key"]], "failed", error="listing did not load")
        return
    hub.upload_many([(f"pages/{item['key']}.html.gz", gzip.compress(page.encode()), "application/gzip")])
    rows = parse(page)
    stored = 0
    for rid, rec in rows:
        if rec.get("pdf_url"):
            ok = store_pdf(hub, session, rec["pdf_url"], rid)
            rec = {**rec, "pdf_stored": ok}
            if ok:
                stored += 1
            else:
                hub.failure("pdf", rid, "pdf did not download", url=rec["pdf_url"])
            polite(hub)
        hub.record(rid, {**rec, "page": item["key"]})
    hub.complete([item["key"]], "done", fetched=len(rows))
    hub.metric("pdf_ok", stored)


def handle_nclt_orders(hub, session, item):
    """NCLT orders: listing -> each case's detail page (interim-order/<id>) -> its order PDFs."""
    page = fetch(hub, session, item["payload"]["url"])
    if page is None:
        hub.complete([item["key"]], "failed", error="listing did not load")
        return
    hub.upload_many([(f"pages/{item['key']}.html.gz", gzip.compress(page.encode()), "application/gzip")])
    rows = parse_nclt_orders_listing(page, SITE or "https://nclt.gov.in")
    fetched = 0
    for row in rows:
        if not row.get("detail_url"):
            continue
        polite(hub)
        detail = fetch(hub, session, row["detail_url"])
        if detail is None:
            hub.failure("detail", row["detail_url"], "detail page did not load")
            continue
        for i, od in enumerate(parse_nclt_interim_order(detail, SITE or "https://nclt.gov.in")):
            rid = _rid(od["pdf_url"], row["case_number"] + od["date"] + str(i))
            ok = store_pdf(hub, session, od["pdf_url"], rid)
            if not ok:
                hub.failure("pdf", rid, "pdf did not download", url=od["pdf_url"])
            hub.record(rid, {**row, **od, "pdf_stored": ok, "page": item["key"]})
            fetched += 1
            polite(hub)
    hub.complete([item["key"]], "done", fetched=fetched)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")),
                    total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = requests.Session()
    worker = handle_nclt_orders if KIND == "nclt_orders" else handle_direct
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break
            worker(hub, session, items[0])
            polite(hub)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


# ------------------------------------------------------------------ offline dry run

class LocalHub:
    """Stand-in for HubClient so `--local` parses one page without the hub."""
    settings = {"threads": 1, "delay_ms": 0, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)


def local(src):
    """Parse one listing page and print its records. `src` is a URL or a local file path."""
    if os.path.exists(src):
        page = open(src, encoding="utf-8", errors="replace").read()
        counts = {"file": 1}
    else:
        hub = LocalHub()
        page = fetch(hub, requests.Session(), src)
        counts = hub.counts
    rows = parse(page) if page else []
    pairs = rows if KIND != "nclt_orders" else [(r.get("detail_url"), r) for r in rows]
    for rid, data in pairs:
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))
    print(f"{len(rows)} rows, KIND={KIND}, counters {counts}", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        if len(sys.argv) > 3:
            KIND = sys.argv[3]
        local(sys.argv[2])
    else:
        main()
