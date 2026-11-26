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
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR.parent / "data-pipeline" / "output"
ZONES_CSV = OUTPUT_DIR / "glasgowzones.csv"
WARD_FORECASTS_CSV = OUTPUT_DIR / "glasgow_ward_forecasts.csv"
MANIFEST_JSON = OUTPUT_DIR / "manifest.json"
WARDS_FILE = BASE_DIR / "data" / "glasgow_wards.geojson"

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

MANIFEST_SOURCES = [
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
    {"name": "SFRS fire statistics (type of incident)", "publisher": "Scottish Fire and Rescue Service via data.gov.scot"},
]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def financial_year_start(value: Any) -> Optional[int]:
    match = FY_RE.match(str(value))
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        return None
    return int(match.group(1))


def is_nonnegative_count(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value < float("inf")


def _read_csv(path: Path, problems: List[str]):
    import pandas as pd

    if not path.exists():
        problems.append(f"missing required file: {path.name}")
        return None
    try:
        df = pd.read_csv(path)
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
            problems.append(f"{name} has unknown wards: {', '.join(sorted(got - expected))}")

    for row in df.to_dict(orient="records"):
        ward = row["ward_id"]
        first, last = financial_year_start(row["first_financial_year"]), financial_year_start(row["last_financial_year"])
        if first is None or last is None:
            problems.append(f"{ward}: first/last financial year must look like 2022/2023")
            continue
        if int(row["years_of_data"]) != last - first + 1:
            problems.append(f"{ward}: years_of_data does not match first/last financial year")
        if (int(row["first_year"]), int(row["last_year"])) != (first, last + 1):
            problems.append(f"{ward}: first_year/last_year disagree with financial years")
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
            if not all(is_nonnegative_count(value) for value in (lo, mid, hi)) or not (lo <= mid <= hi):
                problems.append(f"{ward}: forecast bounds for lead {lead} must satisfy 0 <= lower <= forecast <= upper")
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
    return {
        "generated_by": "data-pipeline/run_model.py",
        "period_unit": "financial_year",
        "history": {
            "first_financial_year": sorted(wf["first_financial_year"])[0],
            "last_financial_year": sorted(wf["last_financial_year"])[-1],
        },
        "projected_financial_years": sorted(
            {fy for lead in HORIZON_LEADS for fy in wf[f"financial_year_{lead}yr"]}
        ),
        "sources": MANIFEST_SOURCES,
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


def check_manifest(
    manifest_path: Path = MANIFEST_JSON,
    files: Optional[List[Path]] = None,
) -> List[str]:
    """Provenance: the manifest must exist, name its sources and match the committed files."""
    problems: List[str] = []
    if not manifest_path.exists():
        return [f"missing provenance manifest: {manifest_path.name}"]
    try:
        manifest = json.loads(manifest_path.read_text())
    except ValueError as exc:
        return [f"{manifest_path.name} is not valid JSON: {exc}"]
    if manifest.get("period_unit") != "financial_year":
        problems.append("manifest period_unit must be 'financial_year'")
    if not manifest.get("sources"):
        problems.append("manifest lists no data sources")
    for path in files or [WARD_FORECASTS_CSV, ZONES_CSV]:
        entry = manifest.get("files", {}).get(path.name)
        if entry is None:
            problems.append(f"manifest has no entry for {path.name}")
        elif path.exists() and entry.get("sha256") != sha256_of(path):
            problems.append(
                f"{path.name} changed since the manifest was written; review the diff then run "
                "`python backend/data_contract.py --write-manifest`"
            )
    return problems


def check_all() -> List[str]:
    return check_ward_forecasts() + check_zones() + check_manifest()


if __name__ == "__main__":
    if "--write-manifest" in sys.argv:
        found = check_ward_forecasts() + check_zones()
        if found:
            print("\n".join(found))
            sys.exit(1)
        MANIFEST_JSON.write_text(json.dumps(build_manifest(), indent=2) + "\n")
        print(f"wrote {MANIFEST_JSON}")
    else:
        found = check_all()
        print("\n".join(found) if found else "model data contract OK")
        sys.exit(1 if found else 0)
