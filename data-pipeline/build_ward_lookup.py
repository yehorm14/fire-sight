"""Build the Glasgow 2011 DataZone to May 2024 electoral ward lookup."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
WARDS_PATH = HERE.parent / "backend" / "data" / "glasgow_wards.geojson"
ZONES_PATH = HERE / "output" / "glasgowzones.csv"
OUTPUT_PATH = HERE / "reference" / "datazone_ward_lookup.csv"
SOURCE_SHA256 = "0a64937af60fb339a1be85cd2f65b6a3d410a38dc5b6c7f25a72ba2d7060a03e"
SHEET_NAME = "SIMD 2020v2 DZ lookup data"
GLASGOW_LA = "S12000049"


def read_glasgow_mapping(workbook_path, ward_names):
    if hashlib.sha256(workbook_path.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Workbook differs from the pinned SIMD lookup release documented in docs/PIPELINE.md")

    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    mapping = {}
    try:
        rows = iter(workbook[SHEET_NAME].values)
        columns = next(rows)
        zone_col, zone_name_col, council_col, ward_col, ward_name_col = (
            columns.index(name) for name in ("DZ", "DZname", "LAcode", "MMWcode", "MMWname")
        )
        for row in rows:
            if row[council_col] != GLASGOW_LA:
                continue
            zone_id, zone_name = row[zone_col], row[zone_name_col]
            ward_id, ward_name = row[ward_col], row[ward_name_col]
            if zone_id in mapping:
                raise ValueError(f"Duplicate Glasgow DataZone in workbook: {zone_id}")
            if ward_id not in ward_names or ward_names[ward_id] != ward_name:
                raise ValueError(f"Workbook ward {ward_id} ({ward_name}) does not match May 2024 ward data")
            if not isinstance(zone_name, str) or not zone_name.strip():
                raise ValueError(f"Missing official name for Glasgow DataZone {zone_id}")
            mapping[zone_id] = (ward_id, zone_name.strip())
    finally:
        workbook.close()
    return mapping


def build_lookup(workbook_path):
    with WARDS_PATH.open(encoding="utf-8") as handle:
        props = [feature["properties"] for feature in json.load(handle)["features"]]
    ward_names = {ward["WD24CD"]: ward["WD24NM"] for ward in props}
    if set(ward_names) != {ward["ward_id"] for ward in props}:
        raise ValueError("App ward IDs differ from the May 2024 boundary codes")

    with ZONES_PATH.open(encoding="utf-8", newline="") as handle:
        zones = {row["zoneid"] for row in csv.DictReader(handle)}

    mapping = read_glasgow_mapping(workbook_path, ward_names)
    missing_zones = zones - mapping.keys()
    extra_zones = mapping.keys() - zones
    missing_wards = ward_names.keys() - {ward for ward, _ in mapping.values()}
    if missing_zones or extra_zones or missing_wards:
        raise ValueError(
            f"Lookup coverage differs from app data. Missing zones: {sorted(missing_zones)}. "
            f"Extra zones: {sorted(extra_zones)}. Wards without zones: {sorted(missing_wards)}."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("datazone_id", "ward_id", "datazone_vintage", "ward_vintage", "datazone_name"))
        writer.writerows(
            (zone, ward, "DZ2011", "WD24", zone_name)
            for zone, (ward, zone_name) in sorted(mapping.items())
        )
    print(f"Wrote {len(mapping)} DataZones across {len(ward_names)} wards to {OUTPUT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="The pinned Scottish Government SIMD lookup workbook")
    args = parser.parse_args()
    try:
        build_lookup(args.workbook)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
