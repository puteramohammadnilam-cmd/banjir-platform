"""Build app/data/areas/<area>/tide.json: predicted high and low tides at a tide gauge, for the page's tide card.

    python3 tools/build_tide.py [--area shah-alam] [--gauge 140] [--station "Port Klang"] [--from 2026] [--to 2027]

Run from 11_Platform_Draft with a Python that has utide (pip install utide; not an app dependency: the app reads the
built file only). Input: the UHSLC research quality hourly record of the gauge in $BANJIR_RAW_DIR/tide_uhslc (see its
README; free to use and redistribute, not for legal use). Method, as 06_Report_Source_Code/src/tide_predict.py, which
also holds the check against later readings: utide harmonic fit (ordinary least squares, nodal corrections) on the last
five years of readings; the tide predicted every 6 minutes; each high and low is a turn of that curve. Heights are in
metres from the record's mean level. Times are Malaysian time (UTC+8). Weather (surge, river flow) is not in them.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import utide

ROOT = Path(__file__).resolve().parents[1]
FIT_YEARS = 5
STEP_MIN = 6
MYT = timedelta(hours=8)
MIN_SWING_M = 0.1         # a low and high closer than this are a wobble of a flat (neap) tide, not a tide: dropped
BIG_SHARE = 0.75          # a day whose tide range is bigger than 75% of days' is a big (spring) tide
CHECK_RMS_M = {140: 0.18}   # typical error of the heights, from tide_predict.py's check on 2020-2023 readings


def raw_dir() -> Path:
    return Path(os.environ.get("BANJIR_RAW_DIR") or ROOT.parent / "05_Raw_Data_Sources") / "tide_uhslc"


def readings(gauge: int) -> tuple[np.ndarray, np.ndarray, str]:
    times, levels, name = [], [], ""
    with open(raw_dir() / f"rqds_{gauge}_hourly.csv") as fh:
        rows = csv.reader(fh)
        next(rows), next(rows)
        for name, t, v in rows:
            if v and v != "NaN" and abs(float(v)) < 30000:
                times.append(np.datetime64(t[:13]))
                levels.append(float(v) / 1000)
    return np.array(times), np.array(levels), name


def turns(gauge: int, first_year: int, last_year: int) -> tuple[list, str, str]:
    """[(Malaysian time, "high" | "low", metres from the mean)] and the fit window."""
    t, h, _ = readings(gauge)
    keep = t >= t[-1] - np.timedelta64(FIT_YEARS * 365, "D")
    as_dt = lambda a: a.astype("datetime64[m]").astype(datetime)   # noqa: E731
    coef = utide.solve(as_dt(t[keep]), h[keep], lat=3.05, method="ols", conf_int="none", verbose=False, nodal=True)
    start = np.datetime64(f"{first_year}-01-01T00") - np.timedelta64(8, "h")   # Malaysian midnight, in UTC
    end = np.datetime64(f"{last_year + 1}-01-01T00") - np.timedelta64(8, "h")
    grid = np.arange(start, end, np.timedelta64(STEP_MIN, "m"))
    level = utide.reconstruct(as_dt(grid), coef, verbose=False).h - float(np.mean(h[keep]))
    rise = np.sign(np.diff(level))
    found = []
    for i in np.nonzero(rise[1:] != rise[:-1])[0] + 1:
        turn = ((grid[i].astype(datetime) + MYT).strftime("%Y-%m-%dT%H:%M"), "high" if rise[i - 1] > 0 else "low",
                round(float(level[i]), 2))
        if found and abs(turn[2] - found[-1][2]) < MIN_SWING_M:
            found.pop()   # this turn and the last are a wobble: drop both, so highs and lows still alternate
        else:
            found.append(turn)
    return found, str(t[keep][0])[:10], str(t[-1])[:10]


def big_range(found: list) -> float:
    """The daily tide range (highest high minus lowest low, by Malaysian date) bigger than BIG_SHARE of days'."""
    days = {}
    for when, _, height in found:
        lo, hi = days.get(when[:10], (height, height))
        days[when[:10]] = (min(lo, height), max(hi, height))
    ranges = sorted(hi - lo for lo, hi in days.values())
    return round(ranges[int(len(ranges) * BIG_SHARE)], 2)


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--area", default="shah-alam")
    parser.add_argument("--gauge", type=int, default=140)
    parser.add_argument("--station", default="Port Klang")
    parser.add_argument("--from", dest="first", type=int, default=2026)
    parser.add_argument("--to", dest="last", type=int, default=2027)
    args = parser.parse_args(argv)
    found, fit_from, fit_to = turns(args.gauge, args.first, args.last)
    doc = {"version": 1, "station": args.station, "gauge": args.gauge,
           "source": "University of Hawaii Sea Level Center, research quality hourly tide-gauge record (gauge run by "
                     "JUPEM); free to use and redistribute, not for legal use",
           "fit": f"{fit_from} to {fit_to}", "typical_error_m": CHECK_RMS_M.get(args.gauge),
           "big_range_m": big_range(found), "turns": found}
    out = ROOT / "app" / "data" / "areas" / args.area / "tide.json"
    out.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {len(found)} highs and lows, {found[0][0]} to {found[-1][0]}; big tide from "
          f"{doc['big_range_m']} m; {out.stat().st_size // 1024} kB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
