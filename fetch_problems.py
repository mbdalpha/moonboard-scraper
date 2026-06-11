#!/usr/bin/env python3
"""Pull the full MoonBoard 2024 problem catalog from the Moon app backend.

Uses the real app API discovered by decompiling com.trainingboard.moon and
capturing its TLS traffic via mitmproxy/WireGuard:

  GET https://grn-climbing.ems-x.com/_bs_api/v1/problems/get/{board}/0/{di}/{du}/{dd}?api-version=3.0

It's a 3-watermark delta sync (max dateInserted / dateUpdated / dateDeleted),
server-capped at 25000 rows per call. We start from epoch and advance all three
watermarks until a call returns fewer than the cap and adds no new problem ids.

Auth headers (bearer + Firebase App Check 'transfer-purpose' token, build ids)
are read from data/auth_headers.json, captured live from the iPhone. Those
tokens expire (~1h for App Check), so re-capture if you get 401/403.
"""
import gzip
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
HOST = "https://grn-climbing.ems-x.com"
BOARD_2024 = 21
CAP = 25000
EPOCH = "2000-01-01 00:00:00.000"


def _fmt(iso):
    return iso.replace("T", " ") if iso else None


def fetch(headers, board, w1, w2, w3):
    q = urllib.parse.quote
    url = (f"{HOST}/_bs_api/v1/problems/get/{board}/0/"
           f"{q(w1)}/{q(w2)}/{q(w3)}?api-version=3.0")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    body = json.loads(raw.decode())
    upd = body.get("updates")
    return json.loads(upd) if isinstance(upd, str) else (upd or [])


def batch_watermarks(batch):
    di = max((p["dateInserted"] for p in batch if p.get("dateInserted")), default=None)
    du = max((c["dateUpdated"] for p in batch for c in p.get("configurations", [])
              if c.get("dateUpdated")), default=None)
    dd = max((d for p in batch for d in
              ([p.get("dateDeleted")] + [c.get("dateDeleted") for c in p.get("configurations", [])])
              if d), default=None)
    return _fmt(di), _fmt(du), _fmt(dd)


def fetch_all(headers, board=BOARD_2024):
    problems = {}
    w1 = w2 = w3 = EPOCH
    page = 0
    while True:
        page += 1
        batch = fetch(headers, board, w1, w2, w3)
        new = sum(1 for p in batch if p["id"] not in problems)
        for p in batch:
            problems[p["id"]] = p
        print(f"  page {page}: {len(batch)} rows ({new} new), total unique {len(problems)}")
        if not batch or new == 0:
            break
        n1, n2, n3 = batch_watermarks(batch)
        n1, n2, n3 = n1 or w1, n2 or w2, n3 or w3
        if (n1, n2, n3) == (w1, w2, w3):
            break  # watermarks not advancing -> done
        w1, w2, w3 = n1, n2, n3
        if len(batch) < CAP and new == 0:
            break
        time.sleep(1.0)
    return list(problems.values())


def has_angle(problem, angle):
    return any(c.get("configuration") == angle for c in problem.get("configurations", []))


def main():
    headers = json.load(open(DATA / "auth_headers.json"))
    print("Fetching full MoonBoard 2024 catalog...")
    allp = fetch_all(headers)
    (DATA / "moon2024_all.json").write_text(json.dumps(allp, indent=2))

    deg40 = [p for p in allp if has_angle(p, "40°")]
    deg25 = [p for p in allp if has_angle(p, "25°")]
    bench40 = [p for p in deg40
               if any(c.get("configuration") == "40°" and c.get("isBenchmark")
                      for c in p["configurations"])]
    (DATA / "moonboard2024_40.json").write_text(json.dumps(deg40, indent=2))
    (DATA / "moonboard2024_40_benchmarks.json").write_text(json.dumps(bench40, indent=2))

    print(f"\nTotal 2024 problems:        {len(allp)}")
    print(f"  at 40°:                   {len(deg40)}  -> data/moonboard2024_40.json")
    print(f"  at 40° benchmarks:        {len(bench40)}  -> data/moonboard2024_40_benchmarks.json")
    print(f"  at 25°:                   {len(deg25)}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} — tokens likely expired; re-capture auth_headers.json. {e.read()[:200]}")
