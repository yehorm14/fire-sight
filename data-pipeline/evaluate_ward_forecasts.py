"""Backtest annual ward forecasts against persistence and a three-year mean."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ward_forecasts import WARD_HISTORY_CSV, WARDS_GEOJSON, forecast_ward, mapped_ward_codes, ward_observations

MIN_TRAIN_YEARS = 6
MEAN_WINDOW = 3
HORIZONS = (1, 2, 3)
MODELS = ("weighted_trend", "last_value", "moving_average_3yr")


def rolling_predictions(fire_records, ward_codes):
    """Build out-of-sample predictions, with an expanding window for each ward."""
    observations = ward_observations(fire_records, ward_codes)
    predictions = []
    for ward, annual in observations.groupby("FeatureCode"):
        values = annual["Value"].to_numpy(dtype=float)
        years = annual["DateCode"].tolist()
        if len(values) <= MIN_TRAIN_YEARS:
            raise ValueError(f"{ward}: at least {MIN_TRAIN_YEARS + 1} annual observations are needed")

        for train_size in range(MIN_TRAIN_YEARS, len(values)):
            history = values[:train_size]
            trend = forecast_ward(history)
            last_value = round(history[-1])
            moving_average = round(float(history[-MEAN_WINDOW:].mean()))
            for lead in HORIZONS:
                target = train_size - 1 + lead
                if target >= len(values):
                    continue
                result = trend[lead]
                predictions.append({
                    "ward_id": ward,
                    "origin": years[train_size - 1],
                    "target": years[target],
                    "lead": lead,
                    "observed": values[target],
                    "weighted_trend": result["forecast"],
                    "weighted_trend_lower": result["lower"],
                    "weighted_trend_upper": result["upper"],
                    "last_value": last_value,
                    "moving_average_3yr": moving_average,
                })
    return pd.DataFrame(predictions)


def summarize(predictions):
    """Compare all point models on identical target cases within each horizon."""
    results = []
    for lead, cases in predictions.groupby("lead"):
        for model in MODELS:
            error = cases[model] - cases["observed"]
            row = {
                "lead_years": int(lead),
                "model": model,
                "cases": len(cases),
                "mae": round(float(error.abs().mean()), 3),
                "rmse": round(float(np.sqrt(np.square(error).mean())), 3),
                "bias": round(float(error.mean()), 3),
            }
            if model == "weighted_trend":
                lower = cases["weighted_trend_lower"]
                upper = cases["weighted_trend_upper"]
                covered = cases["observed"].between(lower, upper)
                row["covered_cases"] = int(covered.sum())
                row["coverage"] = round(float(covered.mean()), 3)
                row["mean_range_width"] = round(float((upper - lower).mean()), 3)
            results.append(row)
    return results


def sha256(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fire-csv", type=Path, default=WARD_HISTORY_CSV)
    args = parser.parse_args()

    predictions = rolling_predictions(pd.read_csv(args.fire_csv), mapped_ward_codes())
    print(json.dumps({
        "observation_sha256": sha256(args.fire_csv),
        "boundary_sha256": sha256(WARDS_GEOJSON),
        "period_unit": "financial_year",
        "count_unit": "dwelling fires",
        "minimum_training_years": MIN_TRAIN_YEARS,
        "wards": int(predictions["ward_id"].nunique()),
        "origins": sorted(predictions["origin"].unique()),
        "metrics": summarize(predictions),
    }, indent=2))


if __name__ == "__main__":
    main()
