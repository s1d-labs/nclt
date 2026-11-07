"""Download the PDFs listed in a standalone run's JSONL. Resumable; India only.

Use this after `standalone.py <project> --no-pdf`, which collects the records and their `pdf_url` links but
skips the files. fetch_docs.py reads out/<project>.jsonl and downloads each `pdf_url` that is not already in
out/<project>/pdf/. Re-run it to pick up what failed; files that exist are skipped.

    python standalone.py nclt-nclt-judgements --no-pdf
    python fetch_docs.py nclt-nclt-judgements
"""
import argparse
import json
import os
import sys
import time

import requests

import crawl

UA = "s1d-labs scraper (https://github.com/s1d-labs)"


class FileHub:
    settings = {"threads": 1, "delay_ms": 1000, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("http_error", n)

    def block(self, n=1):
        self.metric("blocked", n)


def main():
    ap = argparse.ArgumentParser(description="Download the PDFs in a standalone JSONL (India only).")
    ap.add_argument("project")
    ap.add_argument("--out", default="out")
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()

    jsonl_path = os.path.join(a.out, f"{a.project}.jsonl")
    pdf_dir = os.path.join(a.out, a.project, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    if not os.path.exists(jsonl_path):
        sys.exit(f"no records file: {jsonl_path} (run standalone.py first)")

    hub, session = FileHub(), requests.Session()
    session.headers["User-Agent"] = UA
    ok = miss = skip = 0
    for line in open(jsonl_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        url = rec.get("pdf_url")
        rid = rec.get("record_id") or crawl._rid(url, line)
        if not url:
            continue
        dest = os.path.join(pdf_dir, rid + ".pdf")
        if os.path.exists(dest):
            skip += 1
            continue
        data = crawl.fetch(hub, session, url, binary=True)
        time.sleep(a.delay)
        if not data:
            miss += 1
            print(f"miss: {url}", file=sys.stderr)
            continue
        with open(dest, "wb") as f:
            f.write(data)
        ok += 1
    print(f"downloaded {ok}, already had {skip}, missing {miss}")


if __name__ == "__main__":
    main()
