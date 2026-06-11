#!/usr/bin/env python3
"""Convert our Moon-app dataset into the JSON schema moonlink-pwa expects.

moonlink-pwa (normalizeProblems) wants each problem's moves as an array of
{Description:"G5", IsStart:bool, IsEnd:bool}. Our `moves` is a packed string
like "s~D5~|l~G11~|r~I12~|e~J18~" (s=start, l/r=hand, e=end). This rewrites it.

Converts whatever boards/angles config.json selected (the files written by
fetch_problems.py) — see config.py for the schema.
"""
import json
import re
import sys

from config import (load_config, board_slug, angle_token, board_angles,
                    output_dir)

TOKEN = re.compile(r"^([slre])~([A-Ka-k]\d{1,2})~$")


def parse_moves(moves_str):
    out = []
    for tok in (moves_str or "").split("|"):
        m = TOKEN.match(tok.strip())
        if not m:
            continue
        kind, cell = m.group(1), m.group(2).upper()
        out.append({
            "Description": cell,
            "IsStart": kind == "s",
            "IsEnd": kind == "e",
        })
    return out


def config_for(problem, angle):
    for c in problem.get("configurations") or []:
        if c.get("configuration") == angle:
            return c
    return None


def convert(problems, angle, setup_label):
    out = []
    for p in problems:
        cfg = config_for(p, angle)
        if not cfg:
            continue
        moves = parse_moves(p.get("moves"))
        if not moves:
            continue
        out.append({
            "Name": p.get("name") or "Untitled",
            "Grade": cfg.get("grade") or cfg.get("userGrade") or "?",
            "UserGrade": cfg.get("userGrade"),
            "IsBenchmark": bool(cfg.get("isBenchmark")),
            "Repeats": cfg.get("repeats"),
            "Setter": {"Nickname": p.get("setter") or ""},
            "Holdsetup": {"Description": setup_label},
            "MoonBoardConfiguration": {"Description": angle + " MoonBoard"},
            "Moves": moves,
        })
    return out


def main():
    cfg = load_config()
    out = output_dir(cfg)
    converted_any = False

    for board in cfg["boards"]:
        slug = board_slug(board)
        raw_path = out / f"{slug}_all.json"
        if not raw_path.exists():
            print(f"skipping {board['name']}: {raw_path} not found "
                  "(run fetch_problems.py / capture_and_fetch.sh first)")
            continue
        allp = json.load(open(raw_path))
        for angle in board_angles(board, allp):
            tok = angle_token(angle)
            src_path = out / f"{slug}_{tok}.json"
            if not src_path.exists():
                print(f"skipping {board['name']} {angle}: {src_path} not found")
                continue
            full = convert(json.load(open(src_path)), angle, board["name"])
            dst = out / f"{slug}_{tok}_moonlink.json"
            dst.write_text(json.dumps(full))
            print(f"converted {len(full)} {board['name']} {angle} problems -> {dst}")
            if cfg["write_benchmark_files"] and not cfg["benchmarks_only"]:
                bench = [p for p in full if p["IsBenchmark"]]
                bdst = out / f"{slug}_{tok}_benchmarks_moonlink.json"
                bdst.write_text(json.dumps(bench))
                print(f"  {len(bench)} benchmarks -> {bdst}")
            converted_any = True

    if not converted_any:
        sys.exit("nothing converted — no fetched dataset files matched config.json")


if __name__ == "__main__":
    main()
