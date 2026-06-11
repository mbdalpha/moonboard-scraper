#!/usr/bin/env python3
"""Shared loader for config.json — selects what part of the catalog to pull.

config.json keys (all optional; defaults reproduce the original behaviour):

  boards               list of {"id": int, "name": str, "angles": [...] | "all"}
                       Board id is the {board} segment of the app's sync URL
                       (/problems/get/{board}/...). Confirmed ids:
                         15 = MoonBoard 2017 (25°/40°)
                         17 = MoonBoard 2019 (25°/40°)
                         19 = MoonBoard Mini 2020 (40°)
                         21 = MoonBoard 2024 (25°/40°)
                         22 = MoonBoard Mini 2024 (40°)
                       (16/18/20/23-25 are empty; the 2016 board isn't in the
                       app backend.) "angles" filters which wall angles get
                       their own output files ("all" = every angle found in
                       the data).
  benchmarks_only      true -> only benchmark problems are written
  min_grade/max_grade  inclusive Font-grade range, e.g. "6A+".."7C"
  setter               only problems whose setter name contains this string
                       (case-insensitive)
  output_dir           where dataset files go (relative to this directory)
  write_benchmark_files  also write a *_benchmarks subset next to each full
                       per-angle file (ignored when benchmarks_only is true)

The sync API always returns a board's complete catalog, so `boards` controls
what is actually downloaded; the other keys filter what is written to disk.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"

FONT_GRADES = ["4", "4+", "5", "5+",
               "6A", "6A+", "6B", "6B+", "6C", "6C+",
               "7A", "7A+", "7B", "7B+", "7C", "7C+",
               "8A", "8A+", "8B", "8B+", "8C", "8C+", "9A"]

DEFAULTS = {
    "boards": [{"id": 21, "name": "MoonBoard 2024", "angles": ["40°"]}],
    "benchmarks_only": False,
    "min_grade": None,
    "max_grade": None,
    "setter": None,
    "output_dir": "data",
    "write_benchmark_files": True,
}


def _norm_angle(a):
    """'40', '40°', '40 degrees' -> '40°' (matches the API's configuration strings)."""
    m = re.match(r"^\s*(\d+)\s*(°|deg(rees?)?)?\s*$", str(a))
    if not m:
        sys.exit(f"config.json: bad angle {a!r} — use e.g. \"40°\" or \"40\"")
    return m.group(1) + "°"


def _check_grade(g, key):
    if g is None:
        return None
    g = str(g).upper()
    if g not in FONT_GRADES:
        sys.exit(f"config.json: {key} {g!r} is not a Font grade ({', '.join(FONT_GRADES)})")
    return g


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"config.json is not valid JSON: {e}")
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            sys.exit(f"config.json: unknown key(s): {', '.join(sorted(unknown))}")
        cfg.update(user)
    else:
        print("(no config.json — using defaults: MoonBoard 2024 at 40°)")

    if not cfg["boards"]:
        sys.exit("config.json: 'boards' is empty — nothing to download")
    for b in cfg["boards"]:
        if "id" not in b:
            sys.exit(f"config.json: board entry missing 'id': {b}")
        b.setdefault("name", f"board {b['id']}")
        angles = b.setdefault("angles", "all")
        if angles != "all":
            b["angles"] = [_norm_angle(a) for a in angles]

    cfg["min_grade"] = _check_grade(cfg["min_grade"], "min_grade")
    cfg["max_grade"] = _check_grade(cfg["max_grade"], "max_grade")
    return cfg


def board_slug(board):
    return re.sub(r"[^a-z0-9]+", "", board["name"].lower()) or f"board{board['id']}"


def angle_token(angle):
    return angle.rstrip("°")


def board_angles(board, problems):
    """The board's configured angles, or every angle present in `problems`."""
    if board["angles"] != "all":
        return board["angles"]
    found = {c.get("configuration") for p in problems
             for c in (p.get("configurations") or []) if c.get("configuration")}
    return sorted(found)


def passes_filters(problem, angle_cfg, cfg):
    """Apply benchmarks_only / grade range / setter to one problem's
    configuration at a given angle."""
    if cfg["benchmarks_only"] and not angle_cfg.get("isBenchmark"):
        return False
    if cfg["setter"]:
        if cfg["setter"].lower() not in (problem.get("setter") or "").lower():
            return False
    if cfg["min_grade"] or cfg["max_grade"]:
        grade = (angle_cfg.get("grade") or "").upper()
        if grade not in FONT_GRADES:
            return False
        i = FONT_GRADES.index(grade)
        if cfg["min_grade"] and i < FONT_GRADES.index(cfg["min_grade"]):
            return False
        if cfg["max_grade"] and i > FONT_GRADES.index(cfg["max_grade"]):
            return False
    return True


def output_dir(cfg):
    d = pathlib.Path(cfg["output_dir"])
    if not d.is_absolute():
        d = HERE / d
    d.mkdir(parents=True, exist_ok=True)
    return d
