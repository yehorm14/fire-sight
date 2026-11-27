"""Generate ward projections independently of the SIMD scoring inputs."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WARDS_GEOJSON = HERE.parent / "backend" / "data" / "glasgow_wards.geojson"
WARD_HISTORY_CSV = HERE / "reference" / "glasgow_ward_dwelling_fires.csv"
WARD_RELEASE_JSON = HERE / "reference" / "ward_forecast_release.json"


def forecast_ward(counts):
    """Project three individual financial-year counts from annual observations."""
    horizons = (1, 2, 3)
    counts = np.asarray(counts, dtype=float)
    n = len(counts)
    if n < 2:
        last = float(counts[-1]) if n else 0.0
        return {h: {"forecast": round(last), "lower": round(last), "upper": round(last)}
                for h in horizons} | {"trendpct": 0.0, "data_quality": "insufficient"}

    x = np.arange(n, dtype=float)
    weights = np.exp(np.linspace(0.0, 1.0, n))
    slope, intercept = np.polyfit(x, counts, 1, w=weights)

    fitted    = slope * x + intercept
    residuals = counts - fitted
    res_std   = float(np.std(residuals, ddof=1)) if n > 2 else float(np.abs(residuals).mean())

    results = {}
    for h in horizons:
        pt = max(0.0, slope * (n - 1 + h) + intercept)
        results[h] = {
            "forecast": round(pt),
            "lower":    round(max(0.0, pt - 1.96 * res_std)),
            "upper":    round(max(0.0, pt + 1.96 * res_std)),
        }

    latest   = float(counts[-1])
    trendpct = round((results[1]["forecast"] - latest) / latest * 100, 1) if latest else 0.0
    return results | {"trendpct": trendpct,
                      "slope": round(float(slope), 3),
                      "data_quality": "sufficient" if n >= 6 else "limited"}


def ward_observations(fire_records, ward_codes):
    """Select and validate the official annual dwelling-fire counts for the mapped wards."""
    fire_records = fire_records.rename(columns={
        "GeographyCode": "FeatureCode",
        "GeographyName": "FeatureName",
        "Type Of Fire": "Type of Fire",
    })
    rows = fire_records.loc[
        fire_records["FeatureCode"].isin(ward_codes)
        & fire_records["Type of Fire"].eq("Dwelling Fire")
        & fire_records["Accident Status"].eq("All")
        & fire_records["Measurement"].eq("Count")
    ].copy()

    if set(rows["FeatureCode"]) != set(ward_codes):
        raise ValueError("Missing dwelling-fire counts for one or more mapped wards")
    if "GeographyType" in rows and not rows["GeographyType"].eq("Electoral Wards").all():
        raise ValueError("Ward dwelling-fire counts must use Electoral Wards geography")
    if "Units" in rows and not rows["Units"].eq("Fires").all():
        raise ValueError("Ward dwelling-fire counts must use the Fires unit")
    rows["Value"] = pd.to_numeric(rows["Value"], errors="coerce")
    if rows["Value"].isna().any():
        raise ValueError("Missing dwelling-fire count; use a recorded zero only")
    if (not np.isfinite(rows["Value"]).all() or rows["Value"].lt(0).any()
            or rows["Value"].mod(1).ne(0).any()):
        raise ValueError("Dwelling-fire counts must be finite non-negative integers")
    rows["Value"] = rows["Value"].astype(int)

    keys = ["FeatureCode", "DateCode"]
    if rows.duplicated(keys).any():
        raise ValueError("Duplicate ward and financial-year observation")
    rows = rows.sort_values(keys)
    dates = rows["DateCode"].astype("string").str.extract(r"^(\d{4})/(\d{4})$")
    if dates.isna().any().any():
        raise ValueError("Expected financial years in YYYY/YYYY format")
    rows["start_year"] = dates[0].astype(int)
    rows["end_year"] = dates[1].astype(int)
    if not rows["end_year"].eq(rows["start_year"] + 1).all():
        raise ValueError("Each financial year must span consecutive calendar years")
    for ward_code, annual in rows.groupby("FeatureCode"):
        if not (np.diff(annual["start_year"]) == 1).all():
            raise ValueError(f"{ward_code}: financial years must be consecutive and unique")
    return rows


def project_wards(fire_records, ward_codes):
    """Fit each ward's observed, consecutive financial-year dwelling-fire counts."""
    projections = []
    for ward_code, annual in ward_observations(fire_records, ward_codes).groupby("FeatureCode"):
        starts = annual["start_year"].to_numpy()
        ends = annual["end_year"].to_numpy()
        counts = annual["Value"].to_numpy(dtype=float)
        result = forecast_ward(counts)
        row = {
            "ward_id": ward_code,
            "ward_name": annual["FeatureName"].iloc[-1],
            "history_annual": counts[-6:].tolist(),
            "trend_pct": result["trendpct"],
            "slope": result.get("slope", 0.0),
            "data_quality": result["data_quality"],
            "years_of_data": len(counts),
            "first_year": starts[0],
            "last_year": ends[-1],
            "first_financial_year": annual["DateCode"].iloc[0],
            "last_financial_year": annual["DateCode"].iloc[-1],
        }
        for lead in (1, 2, 3):
            start = ends[-1] + lead - 1
            row[f"financial_year_{lead}yr"] = f"{start}/{start + 1}"
            for metric in ("forecast", "lower", "upper"):
                column = "forecast" if metric == "forecast" else f"forecast_{metric}"
                row[f"{column}_{lead}yr"] = result[lead][metric]
        projections.append(row)
    return pd.DataFrame(projections)


def mapped_ward_codes():
    with WARDS_GEOJSON.open() as source:
        return {feature["properties"]["ward_id"] for feature in json.load(source)["features"]}


def load_ward_projections(fire_csv=None):
    """Regenerate the published point release from its named, digest-pinned inputs."""
    release = json.loads(WARD_RELEASE_JSON.read_text())
    source = release["observation_source"]
    if fire_csv is None:
        fire_csv = WARD_RELEASE_JSON.parent / source["file"]["name"]
    if hashlib.sha256(Path(fire_csv).read_bytes()).hexdigest() != source["file"]["sha256"]:
        raise ValueError("Observation CSV does not match the ward forecast release input")
    if hashlib.sha256(WARDS_GEOJSON.read_bytes()).hexdigest() != release["boundary"]["sha256"]:
        raise ValueError("Ward boundaries do not match the ward forecast release input")

    wards = project_wards(pd.read_csv(fire_csv), mapped_ward_codes())
    for column in ("first_financial_year", "last_financial_year"):
        if not wards[column].eq(source[column]).all():
            raise ValueError(f"Ward observation periods differ from the release: {column}")
    for lead, target in enumerate(release["target_financial_years"], start=1):
        if not wards[f"financial_year_{lead}yr"].eq(target).all():
            raise ValueError(f"Ward projections differ from the declared target: {target}")
        wards[f"forecast_lower_{lead}yr"] = None
        wards[f"forecast_upper_{lead}yr"] = None

    return wards.assign(
        forecast_release_id=release["release_id"],
        interval_status=release["interval_status"],
        interval_method=release["interval_method"],
        interval_nominal_level=release["interval_nominal_level"],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fire-csv", type=Path, help="Alternate path to the same pinned observation CSV")
    args = parser.parse_args()
    output = HERE / "output"
    output.mkdir(exist_ok=True)
    forecasts = load_ward_projections(args.fire_csv)
    forecasts.to_csv(output / "glasgow_ward_forecasts.csv", index=False)
    print(f"Saved {len(forecasts)} annual ward projections to {output}")
