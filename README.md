# nclt

This family downloads orders and judgements from India company-law tribunals:

- NCLT (National Company Law Tribunal), `nclt.gov.in`.
- NCLAT (National Company Law Appellate Tribunal), `nclat.nic.in`.

It stores one record for each order or judgement. It stores the PDF file in the family bucket.

## India only

Both sites answer only from India. They block foreign IP addresses. The TLS certificates are valid.

Every project runs with `geo="IN"`. The India pool servers do the work. GitHub runners never get this work.
Each worker uses one thread. Each worker waits at least one second between requests.

## Projects

| Project | Source | Listing | Records |
|---|---|---|---|
| `nclt-nclat-judgements` | NCLAT | `/judgement-data?page=N` (30 per page, ~156 pages) | ~4,680 judgements |
| `nclt-nclat-orders` | NCLAT | `/daily-order-data` (latest only, no pages) | ~10 daily orders |
| `nclt-nclt-judgements` | NCLT | `/archive/judgement-date-wise?page=N` (10 per page, ~3,227 pages) | ~32,270 judgements |
| `nclt-nclt-orders` | NCLT | `/archive/order-judgements?page=N` (10 cases per page, ~11,760 pages) | ~117,600 cases |

The page counts come from the pager on 2026-11-07. Check them again before you seed the full queues.

## Tasks

The `crawl` task does all four projects. The `KIND` environment variable selects the parser:

- `nclat_judgements`, `nclat_orders`, `nclt_judgements`: the listing row holds the PDF link. The task
  parses the row, downloads the PDF, and stores it.
- `nclt_orders`: a two-step flow. The listing links to a detail page (`interim-order/<id>`). The task
  fetches the detail page, finds the order PDFs, and stores them.

Each record has these fields: `tribunal`, `bench`, `case_number`, `parties`, `date`, `order_type`,
`pdf_url`, `title`. The task stores the PDF at `<project>/pdf/<record-id>.pdf`.

## Record id

The record id comes from the PDF path. The PDF path is unique for each file. This id is stable between runs.

## Run it

1. Change `family.py` for your projects and page counts.
2. Run the **setup** workflow (Actions -> setup). It registers the projects and the health checks.
3. The hub starts runs on the India pool servers when the pool is on and there is work.

## Run it without the hub (India machine)

Use `standalone.py` on an India pool server or the India VPS. It is resumable. It writes records to
`out/<project>.jsonl`. It downloads PDFs to `out/<project>/pdf/`.

```
python standalone.py nclt-nclat-judgements
python standalone.py nclt-nclt-orders --start 0 --end 50
python standalone.py nclt-nclt-judgements --no-pdf      # records and links only
python fetch_docs.py nclt-nclt-judgements               # download the PDFs later
```

## Test it

- `python -m pytest tests` tests the parsers on saved real pages. No network is needed.
- `python crawl.py --local <file> <kind>` parses one saved page and prints the records.
- The **check** workflow serves a saved page from localhost and runs `scrape-check` against it. A GitHub
  runner cannot reach the live sites, so the check uses the saved page.

## Limits

- NCLT `/order-date-wise` has a CAPTCHA. This family does not use it. It uses the `/archive/` views instead.
- NCLAT `/daily-order-data` shows only the latest daily orders. The deep archive of NCLAT orders after
  31.05.2021 is in the `/display-board/` DataTables. That interface needs a CSRF token and POST requests.
  It is not in this family yet.
- The NCLAT TLS certificate expires on 2026-11-24. The site must renew it.
