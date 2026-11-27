"""Contract checks for the committed model-data artefacts.

The API serves two CSVs produced by data-pipeline/run_model.py. This module
validates them (schema, ward coverage, financial-year units, provenance
manifest) without any download, and is used both by the API readiness
endpoint and by CI tests.

CLI:
    python backend/data_contract.py            # validate, exit 1 on problems
    python backend/data_contract.py --write-manifest   # refresh the manifest
"""
import ast
import csv
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR.parent / "data-pipeline" / "output"
ZONES_CSV = OUTPUT_DIR / "glasgowzones.csv"
WARD_FORECASTS_CSV = OUTPUT_DIR / "glasgow_ward_forecasts.csv"
MANIFEST_JSON = OUTPUT_DIR / "manifest.json"
WARDS_FILE = BASE_DIR / "data" / "glasgow_wards.geojson"
REFERENCE_DIR = OUTPUT_DIR.parent / "reference"
WARD_RELEASE_JSON = REFERENCE_DIR / "ward_forecast_release.json"
INTERVAL_WITHHELD = "withheld_after_evaluation"
WARD_RELEASE_COLUMNS = {"forecast_release_id", "interval_status", "interval_method", "interval_nominal_level"}

FY_RE = re.compile(r"^(\d{4})/(\d{4})$")
HORIZON_LEADS = (1, 2, 3)

ZONE_COLUMNS = {
    "zoneid", "zonename", "simddecile", "riskscore", "drivers", "riskrank",
    "n_score_components", "cif_ratio",
}
WARD_COLUMNS = {
    "ward_id", "ward_name", "history_annual", "years_of_data", "first_year", "last_year",
    "first_financial_year", "last_financial_year",
} | {
    f"{prefix}_{lead}yr"
    for lead in HORIZON_LEADS
    for prefix in ("financial_year", "forecast", "forecast_lower", "forecast_upper")
}

ZONE_MANIFEST_SOURCES = [
    {
        "name": "SIMD 2020v2 population-weighted deciles",
        "publisher": "Public Health Scotland",
        "url": "https://www.opendata.nhs.scot/dataset/scottish-index-of-multiple-deprivation/resource/acade396-8430-4b34-895a-b3e757fa346e",
    },
    {
        "name": "SIMD 2020v2 indicators",
        "publisher": "Scottish Government",
        "url": "https://www.gov.scot/publications/scottish-index-of-multiple-deprivation-2020v2-indicator-data/",
    },
]
BEST_FIT_MANIFEST_SOURCE = {
    "name": "SFRS best-fit ward dwelling-fire counts, through FY2025/26",
    "publisher": "Scottish Fire and Rescue Service and Scottish Government",
    "url": "https://www.firescotland.gov.uk/publications/document/?id=9990",
}
DIRECT_MANIFEST_SOURCE = {
    "name": "SFRS fire statistics (type of incident)",
    "publisher": "Scottish Fire and Rescue Service via data.gov.scot",
}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def financial_year_start(value: Any) -> Optional[int]:
    match = FY_RE.match(str(value))
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        return None
    return int(match.group(1))


def is_nonnegative_count(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value < float("inf")


def is_whole_count(value: Any) -> bool:
    return is_nonnegative_count(value) and value == int(value)


def read_ward_release() -> Optional[Dict[str, Any]]:
    try:
        release = json.loads(WARD_RELEASE_JSON.read_text())
    except (OSError, ValueError):
        return None
    return release if isinstance(release, dict) else None


def release_row_matches(row, release) -> bool:
    return (
        bool(release)
        and bool(release.get("release_id"))
        and row.get("forecast_release_id") == release["release_id"]
        and row.get("interval_status") == release.get("interval_status") == INTERVAL_WITHHELD
        and row.get("interval_method") is release.get("interval_method") is None
        and row.get("interval_nominal_level") is release.get("interval_nominal_level") is None
    )


def bounds_match_interval(status, lower, point, upper) -> bool:
    if status == INTERVAL_WITHHELD:
        return is_whole_count(point) and lower is None and upper is None
    return (
        status is None
        and all(is_nonnegative_count(value) for value in (lower, point, upper))
        and lower <= point <= upper
    )


def _check_pinned_file(directory, entry, label):
    name = entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str) or not name or Path(name).name != name:
        return f"{label}: missing or invalid pinned filename"
    path = directory / name
    try:
        actual = sha256_of(path)
    except OSError:
        return f"{label}: cannot read {name}"
    if actual != entry.get("sha256"):
        return f"{label}: {name} does not match its pinned SHA-256"
    return None


def check_ward_release_inputs(release, wards_file=WARDS_FILE) -> List[str]:
    if not release:
        return [f"missing or invalid ward forecast release: {WARD_RELEASE_JSON.name}"]
    try:
        source = release["observation_source"]
        boundary = release["boundary"]
        model = release["model"]
        first = financial_year_start(source["first_financial_year"])
        last = financial_year_start(source["last_financial_year"])
        published = date.fromisoformat(release["issue_date"])
        expected = [f"{last + lead}/{last + lead + 1}" for lead in HORIZON_LEADS] if last else []
        declared = (
            bool(release["release_id"]) and bool(release["outcome"]) and bool(release["unit"])
            and model["id"] == "recency_weighted_linear_trend"
            and type(model["version"]) is int and model["version"] > 0
            and model["inputs"] == "annual ward dwelling-fire counts"
            and first is not None and last is not None and first < last
            and published >= date(last + 1, 4, 1)
            and boundary["edition"] == "WD24"
            and all(source[key] for key in ("id", "label", "method"))
            and release["target_financial_years"] == expected
            and release["interval_status"] == INTERVAL_WITHHELD
            and release["interval_method"] is None and release["interval_nominal_level"] is None
        )
        if not declared:
            return ["ward forecast release provenance or interval metadata is invalid"]
        problems = [
            _check_pinned_file(REFERENCE_DIR, source["file"], "ward observation input"),
            _check_pinned_file(REFERENCE_DIR, source["manifest"], "ward observation manifest"),
            _check_pinned_file(REFERENCE_DIR, release["evaluation"], "ward model evaluation"),
            _check_pinned_file(wards_file.parent, {
                "name": wards_file.name, "sha256": boundary["sha256"],
            }, "ward boundaries"),
        ]
        if any(problems):
            return [problem for problem in problems if problem]
        source_manifest = json.loads((REFERENCE_DIR / source["manifest"]["name"]).read_text())
        if (
            source_manifest["source_id"] != source["id"]
            or source_manifest["outcome"] != release["outcome"]
            or source_manifest["unit"] != release["unit"]
            or source_manifest["financial_year"]["first"] != source["first_financial_year"]
            or source_manifest["financial_year"]["last"] != source["last_financial_year"]
            or source_manifest["geography"]["glasgow_map_edition"] != boundary["edition"]
            or any(source_manifest["artifact"][key] != source["file"][key] for key in ("name", "sha256"))
        ):
            return ["ward forecast release disagrees with the pinned observation manifest"]
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return ["ward forecast release provenance or interval metadata is invalid"]
    return []


def _read_csv(path: Path, problems: List[str]):
    import pandas as pd

    if not path.exists():
        problems.append(f"missing required file: {path.name}")
        return None
    try:
        df = pd.read_csv(path, keep_default_na=False, na_values=[""])
    except Exception as exc:  # malformed CSV
        problems.append(f"{path.name} is not readable as CSV: {exc}")
        return None
    if df.empty:
        problems.append(f"{path.name} has no rows")
        return None
    return df


def _ward_ids(wards_file: Path) -> List[str]:
    with wards_file.open() as handle:
        data = json.load(handle)
    return [f["properties"]["ward_id"] for f in data.get("features", [])]


def check_ward_forecasts(csv_path: Path = WARD_FORECASTS_CSV, wards_file: Path = WARDS_FILE) -> List[str]:
    problems: List[str] = []
    df = _read_csv(csv_path, problems)
    if df is None:
        return problems
    name = csv_path.name
    missing = sorted(WARD_COLUMNS - set(df.columns))
    if missing:
        problems.append(f"{name} is missing columns (legacy or malformed schema?): {', '.join(missing)}")
        return problems

    release_columns = set(df.columns) & WARD_RELEASE_COLUMNS
    release = read_ward_release() if release_columns else None
    if release_columns and (release_columns != WARD_RELEASE_COLUMNS or not release):
        return [f"{name} must declare all ward forecast release fields and reference a readable release"]
    observation_source = release.get("observation_source") if release else None
    if release and not isinstance(observation_source, dict):
        return [f"{name} references an invalid ward forecast observation source"]

    if df["ward_id"].duplicated().any():
        problems.append(f"{name} has duplicate ward_id values")
    expected = set(_ward_ids(wards_file)) if wards_file.exists() else set()
    if not expected:
        problems.append(f"ward boundaries missing or empty: {wards_file.name}")
    else:
        got = set(df["ward_id"])
        if expected - got:
            problems.append(f"{name} has no forecast for wards: {', '.join(sorted(expected - got))}")
        if got - expected:
            unknown = sorted(str(ward) for ward in got - expected)
            problems.append(f"{name} has unknown wards: {', '.join(unknown)}")

    records = df.astype(object).where(df.notna(), None)
    for row in records.to_dict(orient="records"):
        ward = row["ward_id"]
        interval_status = row.get("interval_status")
        if release_columns and not release_row_matches(row, release):
            problems.append(f"{ward}: forecast release or interval metadata is invalid")
            continue
        first, last = financial_year_start(row["first_financial_year"]), financial_year_start(row["last_financial_year"])
        if first is None or last is None:
            problems.append(f"{ward}: first/last financial year must look like 2022/2023")
            continue
        if row["years_of_data"] != last - first + 1:
            problems.append(f"{ward}: years_of_data does not match first/last financial year")
        if (row["first_year"], row["last_year"]) != (first, last + 1):
            problems.append(f"{ward}: first_year/last_year disagree with financial years")
        if release and any(
            row[column] != observation_source.get(column)
            for column in ("first_financial_year", "last_financial_year")
        ):
            problems.append(f"{ward}: observed periods do not match the ward forecast release")
        try:
            history = ast.literal_eval(str(row["history_annual"]))
            if not isinstance(history, list) or not history or not all(isinstance(v, (int, float)) and v >= 0 for v in history):
                raise ValueError
        except (ValueError, SyntaxError):
            problems.append(f"{ward}: history_annual must be a list of non-negative annual counts")
        for lead in HORIZON_LEADS:
            start = financial_year_start(row[f"financial_year_{lead}yr"])
            if start != last + lead:
                problems.append(
                    f"{ward}: financial_year_{lead}yr is {row[f'financial_year_{lead}yr']!r}; "
                    f"expected the {lead}-year-ahead financial year (period unit is annual, not months)"
                )
            lo, mid, hi = (
                row[f"forecast_lower_{lead}yr"], row[f"forecast_{lead}yr"], row[f"forecast_upper_{lead}yr"],
            )
            if not bounds_match_interval(interval_status, lo, mid, hi):
                requirement = (
                    "a non-negative whole forecast and both bounds blank"
                    if interval_status == INTERVAL_WITHHELD else "0 <= lower <= forecast <= upper"
                )
                problems.append(f"{ward}: forecast bounds for lead {lead} must satisfy {requirement}")
    return problems


def check_zones(csv_path: Path = ZONES_CSV) -> List[str]:
    problems: List[str] = []
    df = _read_csv(csv_path, problems)
    if df is None:
        return problems
    missing = sorted(ZONE_COLUMNS - set(df.columns))
    if missing:
        problems.append(f"{csv_path.name} is missing columns: {', '.join(missing)}")
        return problems
    if df["zoneid"].duplicated().any():
        problems.append(f"{csv_path.name} has duplicate zoneid values")
    if df["riskscore"].isna().any() or not df["riskscore"].between(0, 100).all():
        problems.append(f"{csv_path.name} riskscore must be present and within 0-100")
    return problems


def build_manifest() -> Dict[str, Any]:
    import pandas as pd

    wf = pd.read_csv(WARD_FORECASTS_CSV)
    zones = pd.read_csv(ZONES_CSV)
    versioned = "forecast_release_id" in wf
    ward_source = BEST_FIT_MANIFEST_SOURCE if versioned else DIRECT_MANIFEST_SOURCE
    manifest = {
        "generated_by": "data-pipeline/run_model.py",
        "period_unit": "financial_year",
        "history": {
            "first_financial_year": sorted(wf["first_financial_year"])[0],
            "last_financial_year": sorted(wf["last_financial_year"])[-1],
        },
        "projected_financial_years": sorted(
            {fy for lead in HORIZON_LEADS for fy in wf[f"financial_year_{lead}yr"]}
        ),
        "sources": [*ZONE_MANIFEST_SOURCES, ward_source],
        "zone_model": {
            "version": 2,
            "score_type": "heuristic vulnerability composite",
            "cif_column": "cif_ratio",
            "cif_unit": "indirectly standardised observed-to-expected ratio on the published scale",
        },
        "files": {
            p.name: {"sha256": sha256_of(p), "rows": int(len(df))}
            for p, df in ((WARD_FORECASTS_CSV, wf), (ZONES_CSV, zones))
        },
    }
    if versioned:
        manifest["ward_forecast_release"] = read_ward_release()
    return manifest


def check_manifest(
    manifest_path: Path = MANIFEST_JSON,
    files: Optional[List[Path]] = None,
    wards_file: Path = WARDS_FILE,
) -> List[str]:
    """Provenance: the manifest must exist, name its sources and match the committed files."""
    problems: List[str] = []
    if not manifest_path.exists():
        return [f"missing provenance manifest: {manifest_path.name}"]
    try:
        manifest = json.loads(manifest_path.read_text())
    except OSError as exc:
        return [f"cannot read provenance manifest {manifest_path.name}: {exc}"]
    except ValueError as exc:
        return [f"{manifest_path.name} is not valid JSON: {exc}"]
    if not isinstance(manifest, dict):
        return [f"{manifest_path.name} must contain a JSON object"]
    if manifest.get("period_unit") != "financial_year":
        problems.append("manifest period_unit must be 'financial_year'")
    if not manifest.get("sources"):
        problems.append("manifest lists no data sources")
    expected_files = files or [WARD_FORECASTS_CSV, ZONES_CSV]
    release = manifest.get("ward_forecast_release")
    entries = manifest.get("files")
    if not isinstance(entries, dict):
        return [*problems, "manifest files must contain a JSON object"]
    for path in expected_files:
        entry = entries.get(path.name)
        if not isinstance(entry, dict):
            problems.append(f"manifest has no entry for {path.name}")
            continue
        if not path.exists():
            continue
        try:
            if path.name == WARD_FORECASTS_CSV.name:
                with path.open(newline="", encoding="utf-8") as handle:
                    columns = set(csv.DictReader(handle).fieldnames or [])
                if bool(WARD_RELEASE_COLUMNS & columns) != (release is not None):
                    problems.append("manifest and forecast CSV disagree on ward forecast release metadata")
            digest = sha256_of(path)
        except (OSError, UnicodeError, csv.Error):
            problems.append(f"cannot read committed artifact: {path.name}")
            continue
        if entry.get("sha256") != digest:
            problems.append(
                f"{path.name} changed since the manifest was written; review the diff then run "
                "`python backend/data_contract.py --write-manifest`"
            )
    if release is not None:
        expected = read_ward_release()
        if release != expected:
            problems.append("manifest ward forecast release differs from the versioned release definition")
        release_problems = check_ward_release_inputs(expected, wards_file)
        problems.extend(release_problems)
        if not release_problems:
            source = expected["observation_source"]
            history = {key: source[key] for key in ("first_financial_year", "last_financial_year")}
            if manifest.get("history") != history:
                problems.append("manifest history disagrees with the ward forecast release")
            if manifest.get("projected_financial_years") != expected["target_financial_years"]:
                problems.append("manifest target years disagree with the ward forecast release")
    return problems


def check_all() -> List[str]:
    return check_ward_forecasts() + check_zones() + check_manifest()


if __name__ == "__main__":
    if "--write-manifest" in sys.argv:
        found = check_ward_forecasts() + check_zones()
        if not found:
            with WARD_FORECASTS_CSV.open(newline="") as handle:
                if WARD_RELEASE_COLUMNS & set(csv.DictReader(handle).fieldnames or []):
                    found += check_ward_release_inputs(read_ward_release())
        if found:
            print("\n".join(found))
            sys.exit(1)
        MANIFEST_JSON.write_text(json.dumps(build_manifest(), indent=2) + "\n")
        print(f"wrote {MANIFEST_JSON}")
    else:
        found = check_all()
        print("\n".join(found) if found else "model data contract OK")
        sys.exit(1 if found else 0)
