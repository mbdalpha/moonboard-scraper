#!/usr/bin/env python3
"""Pull per-hold photos + board layouts from moonboard.com into the dataset.

The (retired) moonboard.com hold-setup viewer composes each board out of
individual hold photos: /content/images/holds/h{number}.png, positioned and
rotated per POST /HoldSetups/GetHoldsetupHolds (Kendo filter
`setupid~eq~{id}`; website setup ids match the app board ids in config.json).
This replays that for every board in config.json and writes, under data/holds/:

  index.json        slug -> board label
  {slug}.json       manifest {label, cells:{CELL:[image, rotation]}}
  img/*.png         the hold photos (shared across boards)

and bundles all of that into a single importable archive:

  data/moonlink_holds.zip

Import that zip into moonlink-pwa (drop it on the library zone, same as a
problems file) and it renders the real holds under the LED grid. The holds live
in this repo, independent of any moonlink-pwa checkout. Needs the same
headed-Chrome login as pull_moonboard.py (Cloudflare): run via
  nix-shell -p "python3.withPackages (p: [p.playwright])" --run "python3 fetch_hold_layouts.py"
"""
import base64
import json
import sys
import zipfile

from playwright.sync_api import sync_playwright

from config import load_config, board_slug, output_dir
from pull_moonboard import MoonBoardClient

HOLDS_URL = "https://www.moonboard.com/HoldSetups/GetHoldsetupHolds"
IMG_BASE = "https://www.moonboard.com/content/images/holds/"

FETCH_IMG_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'same-origin'});
  if (r.status !== 200) return {status: r.status};
  const buf = new Uint8Array(await r.arrayBuffer());
  let s = '';
  for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
  return {status: 200, b64: btoa(s)};
}"""


def fetch_layout(client, setup_id):
    return client.api_post(HOLDS_URL, {
        "sort": "", "page": 1, "pageSize": 200, "group": "",
        "filter": f"setupid~eq~{setup_id}",
    })


def manifest_from(layout, label):
    cells = {}
    for holdset in layout.get("Data") or []:
        for hold in holdset.get("Holds") or []:
            loc = hold.get("Location") or {}
            cell = (loc.get("Description") or "").upper()
            num = hold.get("Number")
            if not cell or not num:
                continue
            cells[cell] = [f"h{num}.png", loc.get("Rotation") or 0]
    return {"label": label, "cells": cells}


def build_zip(holds_dir, zip_path):
    """Bundle data/holds/ into one archive. PNGs are stored (already
    compressed); the small JSON manifests are deflated. moonlink-pwa's importer
    reads both methods."""
    with zipfile.ZipFile(zip_path, "w") as z:
        for j in sorted(holds_dir.glob("*.json")):
            z.write(j, j.name, compress_type=zipfile.ZIP_DEFLATED)
        for img in sorted((holds_dir / "img").glob("*.png")):
            z.write(img, f"img/{img.name}", compress_type=zipfile.ZIP_STORED)


def main():
    cfg = load_config()
    out = output_dir(cfg)
    holds_dir = out / "holds"
    (holds_dir / "img").mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        client = MoonBoardClient(pw)
        try:
            client.login()
            index = {}
            for board in cfg["boards"]:
                slug = board_slug(board)
                layout = fetch_layout(client, board["id"])
                if not (layout.get("Data") or []):
                    print(f"no hold data for {board['name']} (setup {board['id']}) — skipped")
                    continue
                manifest = manifest_from(layout, board["name"])
                n = len(manifest["cells"])
                print(f"{board['name']}: {n} holds in "
                      f"{len(layout['Data'])} holdsets")
                (holds_dir / f"{slug}.json").write_text(json.dumps(manifest))
                index[slug] = board["name"]
                fetched = skipped = 0
                for img, _rot in manifest["cells"].values():
                    dst = holds_dir / "img" / img
                    if dst.exists():
                        skipped += 1
                        continue
                    res = client.page.evaluate(FETCH_IMG_JS, IMG_BASE + img)
                    if res.get("status") != 200:
                        print(f"  {img}: HTTP {res.get('status')}")
                        continue
                    dst.write_bytes(base64.b64decode(res["b64"]))
                    fetched += 1
                print(f"  images: {fetched} fetched, {skipped} already present")
            if not index:
                sys.exit("nothing fetched")
            (holds_dir / "index.json").write_text(json.dumps(index))
            zip_path = out / "moonlink_holds.zip"
            build_zip(holds_dir, zip_path)
            mb = zip_path.stat().st_size / 1e6
            print(f"\nbundled {len(index)} board(s) -> {zip_path} ({mb:.1f} MB)")
            print("import that zip into moonlink-pwa (drop it on the library zone)")
        finally:
            client.close()


if __name__ == "__main__":
    main()
