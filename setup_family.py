"""Put this family's projects in the pool and register its health checks. Run by the Setup workflow (GitHub Actions: the hub
trusts this repo, s1d-labs/<family>, through its OIDC token). Safe to run again: queue items that exist are kept.

Both sites answer GitHub's runners directly (test 2026-11-12), so the projects run with no proxy (proxy=""; the India
pool servers are not used),
threads=1 and delay_ms=1000 (one request per second per worker)."""
from scrape_hub_client import register_project, seed_queue, set_pool, set_probes

from family import FAMILY, PROBES, PROJECTS

print("health checks:", set_probes(FAMILY, PROBES))
for p in PROJECTS:
    register_project(p["name"], title=p["title"], unit_label=p["unit_label"], record_label=p["record_label"],
                     expected_units=len(p["items"]), expected_records=sum(i["payload"].get("expected", 0) for i in p["items"]))
    set_pool(p["name"], FAMILY, p["task"], target=p["target"], env=p["env"], probe=p["probe"],
             max_workers=p.get("max_workers"), proxy="", threads=1, delay_ms=1000)
    print(p["name"], "queue:", seed_queue(p["name"], p["items"]))
