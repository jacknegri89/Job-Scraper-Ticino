"""Build data/places.json from the GeoNames postal-code files for Italy and Switzerland.

Usage:
    python tools/build_places.py IT.txt CH.txt

Download IT.zip and CH.zip from https://download.geonames.org/export/zip/ and unzip them.
Only Lombardy (Italy) and Ticino (Switzerland) are kept. Coordinates of places that appear
with several postal codes are averaged. GeoNames data is licensed CC BY 4.0.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "places.json"
ITALY_REGION_NAME = "Lombardia"
TICINO_REGION_CODE = "TI"
TRAILING_POSTAL_OFFICE = re.compile(r"\s+\d+$")
COLUMN_COUNT = 11


def read_rows(file_path: Path) -> list[list[str]]:
    rows = []
    with file_path.open(encoding="utf-8") as source:
        for line in source:
            columns = line.rstrip("\n").split("\t")
            if len(columns) >= COLUMN_COUNT:
                rows.append(columns)
    return rows


def collect_italy(rows: list[list[str]], collected: dict) -> None:
    for columns in rows:
        if columns[3] != ITALY_REGION_NAME:
            continue
        name = columns[2].strip()
        key = ("IT", "LOM", columns[6], name)
        collected[key].append((float(columns[9]), float(columns[10])))


def collect_ticino(rows: list[list[str]], collected: dict) -> None:
    for columns in rows:
        if columns[4] != TICINO_REGION_CODE:
            continue
        municipality = columns[7].strip() or columns[2].strip()
        name = TRAILING_POSTAL_OFFICE.sub("", municipality)
        key = ("CH", "TI", "TI", name)
        collected[key].append((float(columns[9]), float(columns[10])))


def build(italy_file: Path, switzerland_file: Path) -> list[list]:
    collected: dict = defaultdict(list)
    collect_italy(read_rows(italy_file), collected)
    collect_ticino(read_rows(switzerland_file), collected)
    places = []
    for (country, region, province, name), coordinates in sorted(collected.items()):
        latitude = sum(point[0] for point in coordinates) / len(coordinates)
        longitude = sum(point[1] for point in coordinates) / len(coordinates)
        places.append([name, country, region, province, round(latitude, 4), round(longitude, 4)])
    return places


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    places = build(Path(sys.argv[1]), Path(sys.argv[2]))
    document = {
        "license": "Contains GeoNames data, CC BY 4.0, https://www.geonames.org",
        "columns": ["name", "country", "region", "province", "lat", "lng"],
        "places": places,
    }
    OUTPUT_FILE.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(places)} places to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
