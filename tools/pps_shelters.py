"""Relief centres (PPS) used in past Shah Alam floods: pps.csv -> the shelters file tools/build_area.py reads.

    .venv/bin/python tools/pps_shelters.py [--csv ../05_Raw_Data_Sources/shah_alam/pps/pps.csv] [--out FILE]

Run from 11_Platform_Draft. A row is shown on the map (in "located") only when it has coordinates and its place was
verified "yes" (an OSM feature of the same name in the section the news names) or "probable" (nearly the same name).
Every other row ("area only", "no", or no coordinates) goes into "not_located" and is named in the note instead, so
nothing is drawn where the point is a guess. The list is not official: the note says "used in past floods, not an
official list", and the area's notes.shelters should carry that text.

Writes FILE (default ../05_Raw_Data_Sources/shah_alam/city_osm/shelters.json):
  {"located": [{name, lat, lon, section, verified, date_used, source_url}], "not_located": [...], "note": text}
Names lose the bracketed remark the research added ("SK Kemuning 2 (listed as ... on OSM)" -> "SK Kemuning 2").
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sections_io  # noqa: E402
from rawpaths import SHAH_ALAM_RAW  # noqa: E402

DEFAULT_CSV = SHAH_ALAM_RAW / "pps" / "pps.csv"
DEFAULT_OUT = SHAH_ALAM_RAW / "city_osm" / "shelters.json"
SHOWN = {"yes", "probable"}
LABEL = "used in past floods, not an official list"
REMARK = re.compile(r"\s*\([^()]*\)\s*$")
WHY_NOT = {"area only": "only the village is on the map"}


def clean_name(name: str) -> str:
    """The name without a trailing bracketed remark."""
    return REMARK.sub("", name).strip()


def _first_date(text: str) -> str:
    return text.split(";")[0].strip()


def _row(raw: dict) -> dict:
    section = raw["section"].strip()
    return {"name": clean_name(raw["name"]), "section": sections_io.slug(section) if section else None,
            "section_label": section, "verified": raw["verified"].strip(), "date_used": raw["date_used"].strip(),
            "source_url": raw["source_url"].split(";")[0].strip(),
            "lat": float(raw["lat"]) if raw["lat"].strip() else None,
            "lon": float(raw["lon"]) if raw["lon"].strip() else None}


def read_rows(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return [_row(raw) for raw in csv.DictReader(handle)]


def is_shown(row: dict) -> bool:
    return row["lat"] is not None and row["lon"] is not None and row["verified"] in SHOWN


def _named(row: dict) -> str:
    """The name, with its section when the name does not say it, and why it is not drawn when there is a reason."""
    text = row["name"] if not row["section_label"] or "seksyen" in row["name"].lower() \
        else f"{row['name']} (Seksyen {row['section_label']})"
    return f"{text}, {WHY_NOT[row['verified']]}" if row["verified"] in WHY_NOT else text


def _months(rows: list[dict]) -> str:
    found = sorted({d.strip()[:7] for row in rows for d in row["date_used"].split(";") if d.strip()})
    words = [date.fromisoformat(f"{month}-01").strftime("%B %Y") for month in found]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def note(located: list[dict], not_located: list[dict]) -> str:
    """The text for the area's notes.shelters."""
    probable = sum(1 for row in located if row["verified"] == "probable")
    text = (f"Relief centres (PPS) {LABEL}: {len(located)} centres named in news reports of the floods of "
            f"{_months(located + not_located)}, placed with OpenStreetMap"
            + (f" ({probable} of them by a nearly matching name)" if probable else "")
            + ". A centre open in one flood may not open in the next, so check with the council or the state disaster "
              "office before going.")
    if not_located:
        text += (" Also named in the news but not shown, because they could not be placed on the map: "
                 + "; ".join(_named(row) for row in not_located) + ".")
    return text


def shelters(rows: list[dict]) -> dict:
    """{"located", "not_located", "note"} from the rows, in the CSV's order."""
    located = [{k: row[k] for k in ("name", "lat", "lon", "section", "verified", "date_used", "source_url")}
               for row in rows if is_shown(row)]
    not_located = [row for row in rows if not is_shown(row)]
    kept = [{k: row[k] for k in ("name", "section", "verified", "date_used", "source_url")} for row in not_located]
    return {"located": located, "not_located": kept, "note": note(located, not_located)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = shelters(read_rows(args.csv))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(result['located'])} located, {len(result['not_located'])} named only -> {args.out}\n{result['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
