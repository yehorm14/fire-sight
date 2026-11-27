"""Generate DataZone vulnerability scores and ward-level fire forecasts."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ward_forecasts import load_ward_projections

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUTPUT = HERE / "output"
GLASGOW_CA = "S12000049"

RISK_WEIGHTS = {
    "simddecile_inv": 0.25,
    "overcrowded_rate": 0.20,
    "cif_ratio": 0.20,
    "nocentralheat_rate": 0.20,
    "crime_rate_norm": 0.15,
}

DRIVER_LABELS = {
    "simddecile_inv": "High area deprivation",
    "overcrowded_rate": "High housing overcrowding",
    "cif_ratio": "High comparative illness factor",
    "nocentralheat_rate": "Poor housing condition (no central heating)",
    "crime_rate_norm": "Elevated crime rate",
}

ZONE_OUTPUT_COLUMNS = [
    "zoneid", "zonename", "simddecile", "riskscore", "drivers",
    "population", "overcrowded_rate", "nocentralheat_rate",
    "cif_ratio", "crime_rate_norm", "n_score_components",
]

# Historical column names retained in the DataZone CSV. Forecasts exist at
# ward level, so these columns have no DataZone values.
LEGACY_FORECAST_COLUMNS = [
    "forecast6mo", "forecastlower", "forecastupper", "forecast12mo",
    "forecast18mo", "trendpct", "seasonalitywinterpct",
]


def normalise_component(series: pd.Series) -> pd.Series:
    """Clip to the 2nd and 98th percentiles, then scale to [0, 1]."""
    series = pd.to_numeric(series, errors="coerce")
    valid = series.dropna()
    if valid.empty:
        return series
    lo, hi = valid.quantile([0.02, 0.98])
    if hi == lo:
        return series.where(series.isna(), 0.5)
    return (series.clip(lo, hi) - lo) / (hi - lo)


def compute_riskscore(row: pd.Series) -> pd.Series:
    total_w = total_s = n = 0
    for col, weight in RISK_WEIGHTS.items():
        value = row[f"{col}_norm"]
        if pd.notna(value):
            total_w += weight
            total_s += weight * value
            n += 1
    if total_w == 0:
        return pd.Series({"riskscore": np.nan, "n_score_components": 0})
    return pd.Series({
        "riskscore": int(round(total_s / total_w * 100)),
        "n_score_components": n,
    })


def extract_drivers(row: pd.Series) -> list[str] | None:
    contributions = {
        col: row[f"{col}_norm"] * weight
        for col, weight in RISK_WEIGHTS.items()
        if pd.notna(row[f"{col}_norm"])
    }
    if not contributions:
        return None
    top_three = sorted(contributions, key=contributions.get, reverse=True)[:3]
    return [DRIVER_LABELS[col] for col in top_three]


def build_zones(simd: pd.DataFrame, indicators: pd.DataFrame) -> pd.DataFrame:
    features = simd.loc[simd["CA"].eq(GLASGOW_CA), [
        "DataZone", "IntZone", "SIMD2020V2CountryDecile",
    ]].rename(columns={
        "DataZone": "zoneid", "IntZone": "zonename",
        "SIMD2020V2CountryDecile": "simddecile",
    })
    glasgow_indicators = indicators.loc[indicators["Council_area"].eq("Glasgow City"), [
        "Data_Zone", "Total_population", "overcrowded_rate",
        "nocentralheat_rate", "crime_rate", "CIF",
    ]].rename(columns={
        "Data_Zone": "zoneid", "Total_population": "population",
        "crime_rate": "crime_rate_norm", "CIF": "cif_ratio",
    })
    # SIMD publishes an indirectly standardised observed-to-expected ratio
    # already. Keep its published scale and treat suppression markers as missing.
    glasgow_indicators["cif_ratio"] = pd.to_numeric(glasgow_indicators["cif_ratio"], errors="coerce")
    features = features.merge(glasgow_indicators, on="zoneid", how="left", validate="one_to_one")
    features["simddecile_inv"] = 11 - features["simddecile"]
    for col in RISK_WEIGHTS:
        features[f"{col}_norm"] = normalise_component(features[col])

    features[["riskscore", "n_score_components"]] = features.apply(compute_riskscore, axis=1)
    features["drivers"] = features.apply(extract_drivers, axis=1)
    zones = features[ZONE_OUTPUT_COLUMNS].copy()
    zones["riskrank"] = zones["riskscore"].rank(ascending=False, method="min").astype("Int64")
    zones["data_quality"] = zones["n_score_components"].apply(
        lambda count: "sufficient" if count == 5 else ("limited" if count >= 3 else "insufficient")
    )
    for col in LEGACY_FORECAST_COLUMNS:
        zones[col] = np.nan
    return zones


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones-only", action="store_true", help="keep the existing ward forecasts")
    args = parser.parse_args()

    simd = pd.read_csv(RAW / "simd2020.csv")
    try:
        indicators = pd.read_excel(RAW / "simd2020_indicators.xlsx", sheet_name="Data")
    except ImportError as exc:
        parser.exit(1, f"Unable to read SIMD indicators. Install data-pipeline/requirements.txt: {exc}\n")
    zones = build_zones(simd, indicators)
    ward_forecasts = None if args.zones_only else load_ward_projections()

    OUTPUT.mkdir(exist_ok=True)
    zones_path = OUTPUT / "glasgowzones.csv"
    zones.to_csv(zones_path, index=False)
    print(f"Saved {len(zones)} DataZones to {zones_path}")
    print(f"Missing CIF ratios: {zones['cif_ratio'].isna().sum()}")
    print(f"Data quality breakdown:\n{zones['data_quality'].value_counts().to_string()}")
    if ward_forecasts is not None:
        wards_path = OUTPUT / "glasgow_ward_forecasts.csv"
        ward_forecasts.to_csv(wards_path, index=False)
        print(f"Saved {len(ward_forecasts)} ward forecasts to {wards_path}")


if __name__ == "__main__":
    main()
