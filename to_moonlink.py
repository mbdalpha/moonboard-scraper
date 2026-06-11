#!/usr/bin/env python3
"""Convert our Moon-app dataset into the JSON schema moonlink-pwa expects.

moonlink-pwa (normalizeProblems) wants each problem's moves as an array of
{Description:"G5", IsStart:bool, IsEnd:bool}. Our `moves` is a packed string
like "s~D5~|l~G11~|r~I12~|e~J18~" (s=start, l/r=hand, e=end). This rewrites it.
"""
import json
import pathlib
import re
import sys

DATA = pathlib.Path(__file__).resolve().parent / "data"
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
    for c in problem.get("configurations", []):
        if c.get("configuration") == angle:
            return c
    return None


def convert(problems, angle="40°", setup_label="MoonBoard 2024"):
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
    src = json.load(open(DATA / "moonboard2024_40.json"))
    full = convert(src)
    bench = [p for p in full if p["IsBenchmark"]]
    (DATA / "moonboard2024_40_moonlink.json").write_text(json.dumps(full))
    (DATA / "moonboard2024_40_benchmarks_moonlink.json").write_text(json.dumps(bench))
    print(f"converted {len(full)} problems ({len(bench)} benchmarks)")
    print("  -> data/moonboard2024_40_moonlink.json")
    print("  -> data/moonboard2024_40_benchmarks_moonlink.json")
    # sample
    print("\nsample:", json.dumps(full[0], ensure_ascii=False)[:300])


if __name__ == "__main__":
    main()
