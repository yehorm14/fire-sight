"""Build the FY2025/26 release of annual best-fit Scottish ward dwelling-fire counts."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "reference"
WARDS_GEOJSON = HERE.parent / "backend" / "data" / "glasgow_wards.geojson"
DIRECT_SNAPSHOT = REFERENCE / "glasgow_ward_dwelling_fires.csv"
BASENAME = "sfrs_best_fit_ward_dwelling_fires_fy2025_26"
GLASGOW = "S12000049"
YEARS = range(2009, 2026)
DWELLING = "Dwelling Fire"
RETRIEVED_ON = "2026-11-26"
SOURCES = {
    "incidents": {
        "url": "https://www.firescotland.gov.uk/publications/document/?id=9990",
        "published": "2026-10-30",
        "sha256": "a9fa5a8e017ad4dce29dd57d2abbce520ca4af31aa415036487991bcfe88ba5d",
    },
    "tables": {
        "url": "https://www.firescotland.gov.uk/publications/document/?id=9989",
        "published": "2026-10-30",
        "sha256": "5c3bbd46c941a4095275cd887d05874bbb9ac9834dab39c82eb3c53e0a64c0b4",
    },
    "lookup": {
        "url": "https://data.gov.scot/dataset/2022_data_zone_lookup/resource/81b010f5-0207-4ee5-bd2d-e7821aa6a3dc",
        "published": "2026-08-19",
        "sha256": "41f51a4c0e6edbd30f81c3d8d79c37f3f557a3c1d887a10b75c07f0bc01e0891",
    },
    "glasgow_map": {
        "url": "https://www.data.gov.uk/dataset/faf874fd-aee8-4ca0-a4a9-4c8885ba3e82/wards-may-2024-boundaries-uk-bgc",
        "edition": "WD24",
        "sha256": "86fa0fc0112b1335cff186e06fc006249438ea37a31618894e9ac9f2b06c01cd",
    },
    "direct_benchmark": {
        "url": "https://data.gov.scot/dataset/fire___type_of_incident",
        "sha256": "7bf600b93ff765de52f141e376e65f95af7f830c2ba97b389847e55104eb211c",
    },
}


@dataclass(frozen=True)
class Ward:
    code: str
    name: str
    council: str


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def add_unique(mapping, key, value, context):
    if key in mapping:
        raise ValueError(f"Duplicate {context}: {key}")
    mapping[key] = value


def year_label(year):
    return f"{year}/{year + 1}"


def source_year(label):
    if not isinstance(label, str) or len(label) != 7 or not label[:4].isdigit():
        raise ValueError(f"Unexpected fiscal year: {label}")
    year = int(label[:4])
    if year not in YEARS or label != f"{year}-{(year + 1) % 100:02d}":
        raise ValueError(f"Unexpected fiscal year: {label}")
    return year


def checked_incident_year(label, incident_date):
    year = source_year(label)
    if not isinstance(incident_date, date):
        raise ValueError(f"Missing or invalid incident date for {label}: {incident_date}")
    if incident_date.year - (incident_date.month < 4) != year:
        raise ValueError(f"Incident date {incident_date} disagrees with fiscal year {label}")
    return year


@contextmanager
def workbook_rows(path, sheet):
    with path.open("rb") as stream:
        workbook = load_workbook(stream, read_only=True, data_only=True)
        try:
            rows = iter(workbook[sheet].values)
            headers = next(rows)
            yield headers, rows
        finally:
            workbook.close()


def read_lookup(path):
    zones, wards, councils = {}, {}, {}
    with path.open(encoding="cp1252", newline="") as file:
        for row in csv.DictReader(file):
            zone, ward_id, ward_name, council, council_name = (
                (row.get(field) or "").strip()
                for field in ("DZ22_Code", "MMWard_Code", "MMWard_Name", "LA_Code", "LA_Name")
            )
            if not all((zone, ward_id, ward_name, council, council_name)):
                raise ValueError("Missing code or name in the DataZone lookup")
            ward = Ward(ward_id, ward_name, council)
            if wards.setdefault(ward_id, ward) != ward:
                raise ValueError(f"Conflicting geography for ward {ward_id}")
            if councils.setdefault(council, council_name) != council_name:
                raise ValueError(f"Conflicting name for council {council}")
            add_unique(zones, zone, ward, "DataZone")
    if (len(zones), len(wards), len(councils)) != (7392, 355, 32):
        raise ValueError("Expected 7,392 DataZones, 355 wards and 32 councils")
    return zones, wards, councils


def verify_glasgow_wards(wards):
    map_wards = {}
    for feature in json.loads(WARDS_GEOJSON.read_text(encoding="utf-8"))["features"]:
        properties = feature["properties"]
        code = properties["WD24CD"]
        if code != properties["ward_id"]:
            raise ValueError(f"App ward ID disagrees with WD24 for {code}")
        add_unique(map_wards, code, properties["WD24NM"], "WD24 map ward")
    lookup_wards = {ward.code: ward.name for ward in wards.values() if ward.council == GLASGOW}
    if len(map_wards) != 23 or lookup_wards != map_wards:
        raise ValueError("Glasgow lookup must match the names and codes of the 23 WD24 map wards")


def tally_incidents(rows, zones, councils):
    ward_counts, council_counts, issues = Counter(), Counter(), Counter()
    locations = Counter()
    for fire_type, fiscal_year, incident_date, council, council_name, zone in rows:
        if fire_type != DWELLING:
            continue
        year = checked_incident_year(fiscal_year, incident_date)
        if council not in councils:
            reason = "unknown_council" if council else "missing_council"
        elif council_name != councils[council]:
            reason = "council_name_disagreement"
        elif zone not in zones:
            reason = "unmatched_datazone" if zone else "missing_datazone"
        elif zones[zone].council != council:
            reason = "council_code_disagreement"
        else:
            ward_counts[zones[zone].code, year] += 1
            council_counts[council, year] += 1
            continue
        issues[reason] += 1
        lookup_council = zones[zone].council if zone in zones else None
        locations[reason, fiscal_year, str(council), str(lookup_council)] += 1

    if issues:
        detail = "; ".join(
            f"{reason} FY{year} reported={reported} lookup={lookup}: {count}"
            for (reason, year, reported, lookup), count in sorted(locations.items())
        )
        raise ValueError(f"Unavailable ward observations ({dict(issues)}): {detail}")
    return ward_counts, council_counts


def read_incidents(path, zones, councils):
    fields = ("IncidentType", "FiscalYear", "IncidentDate", "LACode", "LocalAuthority", "DataZone")
    with workbook_rows(path, "Sheet1") as (headers, rows):
        indices = tuple(headers.index(field) for field in fields)
        return tally_incidents((tuple(row[i] for i in indices) for row in rows), zones, councils)


def tally_published(rows, councils_by_name):
    counts = {}
    excluded_unnamed = {}
    for fiscal_year, name, dwelling_values in rows:
        year = source_year(fiscal_year)
        if len(dwelling_values) != 8 or any(type(value) is not int or value < 0 for value in dwelling_values):
            raise ValueError(f"Invalid published dwelling counts for {name} FY{fiscal_year}")
        total = sum(dwelling_values)
        if not name and total == 0:
            add_unique(excluded_unnamed, year, 0, "unnamed council/year")
            continue
        if name not in councils_by_name:
            raise ValueError(f"Unrecognised council {name!r} with {total} published dwelling fires")
        add_unique(counts, (councils_by_name[name], year), total, "published council/year")
    return counts, excluded_unnamed


def read_published(path, councils):
    councils_by_name = {name: code for code, name in councils.items()}
    if len(councils_by_name) != len(councils):
        raise ValueError("Council names are not unique")
    with workbook_rows(path, "BuildingFiresLAData") as (headers, rows):
        year_idx, name_idx = headers.index("Year"), headers.index("LA_Name")
        dwelling = tuple(i for i, header in enumerate(headers)
                         if isinstance(header, str) and header.startswith("Dwelling:"))
        return tally_published(
            ((row[year_idx], row[name_idx], tuple(row[i] for i in dwelling)) for row in rows),
            councils_by_name,
        )


def reconcile_councils(incidents, published, councils):
    expected = {(council, year) for council in councils for year in YEARS}
    if published.keys() != expected:
        raise ValueError("Published table must contain one row for every council and financial year")
    different = {key: (incidents.get(key, 0), total) for key, total in published.items()
                 if incidents.get(key, 0) != total}
    if different:
        raise ValueError(f"Incident and published council counts differ: {different}")


def compare_direct(ward_counts, glasgow_wards):
    values = {}
    with DIRECT_SNAPSHOT.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            year = int(row["DateCode"][:4])
            key = (row["GeographyCode"], year)
            add_unique(values, key, int(row["Value"]), "direct ward/year")
    if values.keys() != {(ward, year) for ward in glasgow_wards for year in range(2009, 2023)}:
        raise ValueError("Direct benchmark must cover all Glasgow wards from FY2009/10 to FY2022/23")
    deltas = [ward_counts[key] - value for key, value in values.items()]
    return {
        "source_id": "sfrs_direct_ward_fy2009_10_to_fy2022_23",
        "matched_ward_years": len(deltas),
        "exact_matches": deltas.count(0),
        "mean_absolute_difference": round(sum(abs(delta) for delta in deltas) / len(deltas), 3),
        "smallest_delta": min(deltas),
        "largest_delta": max(deltas),
        "direct_total": sum(values.values()),
        "best_fit_total": sum(values.values()) + sum(deltas),
    }


def build(incidents, lookup, tables, output):
    for key, path in {
        "incidents": incidents,
        "lookup": lookup,
        "tables": tables,
        "glasgow_map": WARDS_GEOJSON,
        "direct_benchmark": DIRECT_SNAPSHOT,
    }.items():
        if sha256(path) != SOURCES[key]["sha256"]:
            raise ValueError(f"{path} does not match the pinned {key} SHA-256")

    zones, wards, councils = read_lookup(lookup)
    verify_glasgow_wards(wards)
    ward_counts, council_counts = read_incidents(incidents, zones, councils)
    published, unnamed = read_published(tables, councils)
    reconcile_councils(council_counts, published, councils)
    glasgow_wards = {ward.code for ward in wards.values() if ward.council == GLASGOW}
    overlap = compare_direct(ward_counts, glasgow_wards)

    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output) as temporary:
        staging = Path(temporary)
        csv_path = staging / f"{BASENAME}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(("GeographyCode", "GeographyName", "GeographyType", "DateCode", "Measurement",
                             "Units", "Value", "Accident Status", "Type Of Fire", "CouncilCode"))
            writer.writerows(
                (ward.code, ward.name, "Electoral Wards", year_label(year), "Count", "Fires",
                 ward_counts[ward.code, year], "All", DWELLING, ward.council)
                for ward in sorted(wards.values(), key=lambda ward: ward.code)
                for year in YEARS
            )
        rows = len(wards) * len(YEARS)
        manifest = {
            "source_id": BASENAME,
            "retrieved_on": RETRIEVED_ON,
            "outcome": "SFRS-attended incidents classified Dwelling Fire, all accident statuses",
            "unit": "dwelling fires per ward per financial year",
            "financial_year": {"first": year_label(YEARS.start), "last": year_label(YEARS.stop - 1),
                               "starts": "1 April", "ends": "31 March"},
            "geography": {"region": "Scotland", "assignment": "whole 2022 DataZone to published electoral ward",
                          "glasgow_map_edition": "WD24", "councils": len(councils), "wards": len(wards),
                          "datazones": len(zones), "glasgow_council_code": GLASGOW,
                          "glasgow_wards": len(glasgow_wards)},
            "sources": SOURCES,
            "coverage": {
                "ward_years": rows,
                "glasgow_ward_years": len(glasgow_wards) * len(YEARS),
                "mapped_incidents": sum(ward_counts.values()),
                "glasgow_mapped_incidents": sum(council_counts[GLASGOW, year] for year in YEARS),
                "verified_zero_ward_years": rows - len(ward_counts),
                "unavailable_ward_years": 0,
                "missing_council": 0,
                "unknown_council": 0,
                "missing_datazone": 0,
                "unmatched_datazone": 0,
                "council_name_disagreement": 0,
                "council_code_disagreement": 0,
                "published_council_years_reconciled": len(published),
                "unnamed_published_rows_excluded": [
                    {"financial_year": year_label(year), "dwelling_fires": total}
                    for year, total in sorted(unnamed.items())
                ],
            },
            "glasgow_annual_totals": {year_label(year): council_counts[GLASGOW, year] for year in YEARS},
            "glasgow_direct_overlap": overlap,
            "artifact": {"name": csv_path.name, "rows": rows, "sha256": sha256(csv_path)},
        }
        manifest_path = staging / f"{BASENAME}.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n",
        )
        csv_path.replace(output / csv_path.name)
        manifest_path.replace(output / manifest_path.name)
    print(f"Wrote {rows} ward/year counts and provenance to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for source in ("incidents", "lookup", "tables"):
        parser.add_argument(f"--{source}", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REFERENCE)
    args = parser.parse_args()
    try:
        build(args.incidents, args.lookup, args.tables, args.output_dir)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
