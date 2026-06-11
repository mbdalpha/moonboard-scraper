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

Which boards/angles/subsets get downloaded and written is driven by
config.json — see config.py for the schema.
"""
import gzip
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from config import (load_config, board_slug, angle_token, board_angles,
                    passes_filters, output_dir)

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data"
HOST = "https://grn-climbing.ems-x.com"
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
    if isinstance(upd, str):  # server sends "" (not null) when there's nothing left
        upd = json.loads(upd) if upd.strip() else []
    return upd or []


def batch_watermarks(batch):
    # configurations can be null (not just missing) on some boards
    di = max((p["dateInserted"] for p in batch if p.get("dateInserted")), default=None)
    du = max((c["dateUpdated"] for p in batch for c in (p.get("configurations") or [])
              if c.get("dateUpdated")), default=None)
    dd = max((d for p in batch for d in
              ([p.get("dateDeleted")] + [c.get("dateDeleted") for c in (p.get("configurations") or [])])
              if d), default=None)
    return _fmt(di), _fmt(du), _fmt(dd)


def fetch_all(headers, board):
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


def config_at(problem, angle):
    for c in problem.get("configurations") or []:
        if c.get("configuration") == angle:
            return c
    return None


def main():
    cfg = load_config()
    headers = json.load(open(DATA / "auth_headers.json"))
    out = output_dir(cfg)

    for board in cfg["boards"]:
        slug = board_slug(board)
        print(f"Fetching full {board['name']} catalog (board id {board['id']})...")
        allp = fetch_all(headers, board["id"])
        raw_path = out / f"{slug}_all.json"
        raw_path.write_text(json.dumps(allp, indent=2))
        print(f"\nTotal {board['name']} problems: {len(allp)}  -> {raw_path}")

        for angle in board_angles(board, allp):
            tok = angle_token(angle)
            subset, bench = [], []
            for p in allp:
                c = config_at(p, angle)
                if not c or not passes_filters(p, c, cfg):
                    continue
                subset.append(p)
                if c.get("isBenchmark"):
                    bench.append(p)
            path = out / f"{slug}_{tok}.json"
            path.write_text(json.dumps(subset, indent=2))
            print(f"  at {angle}:                 {len(subset)}  -> {path}")
            if cfg["write_benchmark_files"] and not cfg["benchmarks_only"]:
                bpath = out / f"{slug}_{tok}_benchmarks.json"
                bpath.write_text(json.dumps(bench, indent=2))
                print(f"  at {angle} benchmarks:      {len(bench)}  -> {bpath}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} — tokens likely expired; re-capture auth_headers.json. {e.read()[:200]}")
