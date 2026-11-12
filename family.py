"""What this family scrapes. Change this file first.

Family `nclt`: company-law tribunal orders and judgements from:
  - NCLT  (nclt.gov.in)   orders and judgements archive (Drupal views, PDFs inline or on a detail page)
  - NCLAT (nclat.nic.in)  older judgements and daily orders (Drupal views, PDFs inline)

Both sites answer GitHub's runners directly (test 2026-11-12) and have valid TLS certificates, so every project runs with
no proxy, threads=1 and delay_ms>=1000 (one request per second per worker).

The page counts below are the pager "last" values seen on 2026-11-07. Re-check them before you seed the
full queues: fetch each listing from India and read the last page number in the pager.
"""
import json
from pathlib import Path

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]

NCLT = "https://nclt.gov.in"
NCLAT = "https://nclat.nic.in"

# pager last-page index (0-based) on 2026-11-07; page count = value + 1
NCLAT_JUDGEMENT_PAGES = 156          # /judgement-data?page=0..155, 30 judgements/page  -> ~4,680
NCLT_JUDGEMENT_PAGES = 3227          # /archive/judgement-date-wise?page=0..3226, 10/page -> ~32,270
NCLT_ORDER_PAGES = 11760             # /archive/order-judgements?page=0..11759, 10 cases/page -> ~117,600 cases

PROJECTS = [
    {
        "name": f"{FAMILY}-nclat-judgements",
        "title": "NCLAT judgements (older archive)",
        "task": "crawl", "target": "nclat.nic.in",
        "env": {"KIND": "nclat_judgements", "SITE": NCLAT},
        "probe": f"{FAMILY}:nclat.nic.in",
        "unit_label": "page", "record_label": "judgement", "max_workers": 6,
        "items": [{"key": f"page-{n}", "payload": {"url": f"{NCLAT}/judgement-data?page={n}", "expected": 30}}
                  for n in range(NCLAT_JUDGEMENT_PAGES)],
    },
    {
        "name": f"{FAMILY}-nclat-orders",
        "title": "NCLAT daily orders and cause lists",
        "task": "crawl", "target": "nclat.nic.in",
        "env": {"KIND": "nclat_orders", "SITE": NCLAT},
        "probe": f"{FAMILY}:nclat.nic.in",
        "unit_label": "page", "record_label": "daily order", "max_workers": 2,
        # /daily-order-data is not paged; it shows the latest daily orders only. Re-fetch it on a schedule.
        "items": [{"key": "latest", "payload": {"url": f"{NCLAT}/daily-order-data", "expected": 10}}],
    },
    {
        "name": f"{FAMILY}-nclt-judgements",
        "title": "NCLT judgements (date wise archive)",
        "task": "crawl", "target": "nclt.gov.in",
        "env": {"KIND": "nclt_judgements", "SITE": NCLT},
        "probe": f"{FAMILY}:nclt.gov.in",
        "unit_label": "page", "record_label": "judgement", "max_workers": 6,
        "items": [{"key": f"page-{n}", "payload": {"url": f"{NCLT}/archive/judgement-date-wise?page={n}", "expected": 10}}
                  for n in range(NCLT_JUDGEMENT_PAGES)],
    },
    {
        "name": f"{FAMILY}-nclt-orders",
        "title": "NCLT orders (case wise archive)",
        "task": "crawl", "target": "nclt.gov.in",
        "env": {"KIND": "nclt_orders", "SITE": NCLT},
        "probe": f"{FAMILY}:nclt.gov.in",
        "unit_label": "page", "record_label": "order", "max_workers": 4,
        # each listing page holds ~10 cases; each case has a detail page with one or more order PDFs
        "items": [{"key": f"page-{n}", "payload": {"url": f"{NCLT}/archive/order-judgements?page={n}", "expected": 15}}
                  for n in range(NCLT_ORDER_PAGES)],
    },
]

# health checks: one per host, every minute, direct from the hub (in Mumbai).
# Work on a project holds while its probe fails.
PROBES = [
    {"name": f"{FAMILY}:nclt.gov.in", "url": f"{NCLT}/archive/judgement-date-wise", "expect": "Name of Petitioner"},
    {"name": f"{FAMILY}:nclat.nic.in", "url": f"{NCLAT}/judgement-data", "expect": "Download"},
]
