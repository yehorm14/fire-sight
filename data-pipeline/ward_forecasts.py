"""Generate ward projections independently of the SIMD scoring inputs."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
WARDS_GEOJSON = HERE.parent / "backend" / "data" / "glasgow_wards.geojson"


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


def project_wards(fire_records, ward_codes):
    """Fit each ward's observed, consecutive financial-year dwelling-fire counts."""
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
    rows["Value"] = pd.to_numeric(rows["Value"], errors="raise")
    if not np.isfinite(rows["Value"]).all() or rows["Value"].lt(0).any():
        raise ValueError("Dwelling-fire counts must be finite and non-negative")

    projections = []
    for ward_code, annual in rows.groupby("FeatureCode"):
        annual = annual.sort_values("DateCode")
        dates = annual["DateCode"].str.extract(r"^(\d{4})/(\d{4})$")
        if dates.isna().any().any():
            raise ValueError(f"{ward_code}: expected financial years in YYYY/YYYY format")
        starts, ends = (dates[column].astype(int).to_numpy() for column in (0, 1))
        if not ((ends == starts + 1).all() and (np.diff(starts) == 1).all()):
            raise ValueError(f"{ward_code}: financial years must be consecutive and unique")

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


def load_ward_projections(fire_csv):
    with WARDS_GEOJSON.open() as source:
        ward_codes = {feature["properties"]["ward_id"] for feature in json.load(source)["features"]}
    return project_wards(pd.read_csv(fire_csv), ward_codes)


if __name__ == "__main__":
    output = HERE / "output"
    output.mkdir(exist_ok=True)
    forecasts = load_ward_projections(HERE / "raw" / "fire_statistics_scotland.csv")
    forecasts.to_csv(output / "glasgow_ward_forecasts.csv", index=False)
    print(f"Saved {len(forecasts)} annual ward projections to {output}")
