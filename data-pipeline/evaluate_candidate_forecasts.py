"""Evaluate the FY2025/26 candidate annual ward series without changing production."""

import argparse
import json
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd

from build_best_fit_ward_series import BASENAME, REFERENCE
from evaluate_ward_forecasts import HORIZONS, MIN_TRAIN_YEARS, rolling_predictions, sha256
from pooled_ward_forecast import forecast_pooled_wards
from ward_forecasts import mapped_ward_codes, ward_observations

CANDIDATE_CSV = REFERENCE / f"{BASENAME}.csv"
FIRST_SCORED_ORIGIN = "2018/2019"
HOLDOUT_ORIGIN = "2022/2023"
NOMINAL_COVERAGE = 0.8
MIN_CALIBRATION_YEARS = 4
MIN_COVERAGE_YEARS = 5
COVERAGE_TOLERANCE = 0.10
MIN_MAE_IMPROVEMENT = 0.05
MAX_LEAD_MAE_REGRESSION = 0.05
MAX_CITY_BIAS_FRACTION = 0.10
MODEL = "pooled_poisson"
INCUMBENT = "weighted_trend"
MODELS = (INCUMBENT, "last_value", "moving_average_3yr", MODEL)


def point_cases(fire_records, ward_codes):
    """Reuse incumbent predictions and append pooled forecasts on identical cases."""
    existing = rolling_predictions(fire_records, ward_codes)
    observed = ward_observations(fire_records, ward_codes)
    panel = observed.pivot(index="FeatureCode", columns="DateCode", values="Value").sort_index(axis=1)
    if panel.isna().any().any():
        raise ValueError("Pooled forecasting requires matching observed years for all wards")
    values, years = panel.to_numpy(), panel.columns.tolist()
    pooled = []
    for width in range(MIN_TRAIN_YEARS, len(years)):
        forecasts = np.rint(forecast_pooled_wards(values[:, :width], HORIZONS)).astype(int)
        for lead in HORIZONS:
            target = width - 1 + lead
            if target < len(years):
                pooled.extend(
                    (str(ward), years[width - 1], years[target], lead, forecast)
                    for ward, forecast in zip(panel.index, forecasts[:, lead - 1], strict=True)
                )

    keys = ["ward_id", "origin", "target", "lead"]
    candidate = pd.DataFrame(pooled, columns=[*keys, MODEL])
    paired = existing.merge(candidate, on=keys, how="outer", validate="one_to_one", indicator=True)
    if not paired["_merge"].eq("both").all():
        raise ValueError("Candidate and baseline forecast cases do not align")
    return paired.drop(columns="_merge")


def city_cases(wards):
    """Form city point cases before interval calibration."""
    fields = ["model", "origin", "target", "lead"]
    return wards.groupby(fields, as_index=False)[["observed", "forecast"]].sum()


def add_intervals(cases, *, scale_by_forecast):
    """Calibrate separately per model and lead on targets strictly before each origin."""
    result = cases.copy()
    result["calibration_years"] = 0
    result["calibration_cases"] = 0
    result["last_calibration_target"] = pd.Series(pd.NA, index=result.index, dtype="string")
    result["lower"] = np.nan
    result["upper"] = np.nan

    for _, sequence in result.groupby(["model", "lead"]):
        errors = (sequence["forecast"] - sequence["observed"]).abs()
        scales = np.sqrt(sequence["forecast"].clip(lower=1)) if scale_by_forecast else 1
        scores = errors / scales
        for origin, current in sequence.groupby("origin"):
            prior = sequence.loc[sequence["target"].lt(origin)]
            years = prior["target"].nunique()
            if years < MIN_CALIBRATION_YEARS:
                continue
            rank = ceil((len(prior) + 1) * NOMINAL_COVERAGE)
            if rank > len(prior):
                continue
            cutoff = float(np.partition(scores.loc[prior.index].to_numpy(), rank - 1)[rank - 1])
            radius = cutoff * (np.sqrt(current["forecast"].clip(lower=1)) if scale_by_forecast else 1)
            result.loc[current.index, "calibration_years"] = years
            result.loc[current.index, "calibration_cases"] = len(prior)
            result.loc[current.index, "last_calibration_target"] = prior["target"].max()
            result.loc[current.index, "lower"] = np.floor((current["forecast"] - radius).clip(lower=0))
            result.loc[current.index, "upper"] = np.ceil(current["forecast"] + radius)
    return result


def predictions_summary(cases):
    """Report point and interval errors before rounding for display."""
    error = cases["forecast"] - cases["observed"]
    available = cases.loc[cases["lower"].notna()]
    covered = available["observed"].between(available["lower"], available["upper"])
    years = available["target"].nunique()
    return {
        "cases": len(cases),
        "target_years": int(cases["target"].nunique()),
        "mae": float(error.abs().mean()),
        "bias": float(error.mean()),
        "mean_observed": float(cases["observed"].mean()),
        "intervals": {
            "available_cases": len(available),
            "target_years": int(years),
            "covered_cases": int(covered.sum()),
            "coverage": float(covered.mean()) if len(available) else None,
            "mean_width": float((available["upper"] - available["lower"]).mean()) if len(available) else None,
        },
    }


def summarize(wards, cities):
    summaries = {}
    for lead, cases in wards.groupby("lead"):
        city = cities.loc[cities["lead"].eq(lead)]
        summaries[str(lead)] = {
            "target_period": [cases["target"].min(), cases["target"].max()],
            "origin_period": [cases["origin"].min(), cases["origin"].max()],
            "models": {
                model: {
                    "ward": predictions_summary(cases.loc[cases["model"].eq(model)]),
                    "city": predictions_summary(city.loc[city["model"].eq(model)]),
                }
                for model in MODELS
            },
        }
    return summaries


def accuracy_gate(summary):
    current = [data["models"][INCUMBENT]["ward"]["mae"] for data in summary.values()]
    candidate = [data["models"][MODEL]["ward"]["mae"] for data in summary.values()]
    improvement = 1 - sum(candidate) / sum(current)
    no_large_regression = all(new <= old * (1 + MAX_LEAD_MAE_REGRESSION)
                              for new, old in zip(candidate, current, strict=True))
    return {
        "mean_mae_improvement_fraction": improvement,
        "no_lead_regression_over_limit": no_large_regression,
        "passed": improvement >= MIN_MAE_IMPROVEMENT and no_large_regression,
    }


def promotion_decision(full, development, holdout):
    accuracy = {"development": accuracy_gate(development), "fixed_holdout": accuracy_gate(holdout)}
    bias = {
        lead: abs(data["models"][MODEL]["city"]["bias"]) / data["models"][MODEL]["city"]["mean_observed"]
        for lead, data in holdout.items()
    }
    interval = {}
    for lead, data in full.items():
        interval[lead] = {}
        for unit in ("ward", "city"):
            metrics = data["models"][MODEL][unit]["intervals"]
            if metrics["target_years"] < MIN_COVERAGE_YEARS:
                status = "insufficient_target_years"
            elif abs(metrics["coverage"] - NOMINAL_COVERAGE) > COVERAGE_TOLERANCE:
                status = "outside_coverage_tolerance"
            else:
                status = "passed"
            interval[lead][unit] = status
    bias_passed = all(value <= MAX_CITY_BIAS_FRACTION for value in bias.values())
    limits_met = all(result["passed"] for result in accuracy.values()) and bias_passed
    intervals_passed = all(status == "passed" for lead in interval.values() for status in lead.values())
    return {
        "accuracy": accuracy,
        "fixed_holdout_city_absolute_bias_fraction": bias,
        "city_bias_passed": bias_passed,
        "interval_coverage": interval,
        "intervals_passed": intervals_passed,
        "candidate_eligible_for_promotion": limits_met and intervals_passed,
        "fallback": INCUMBENT,
    }


def evaluate():
    manifest = json.loads(CANDIDATE_CSV.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if sha256(CANDIDATE_CSV) != manifest["artifact"]["sha256"]:
        raise ValueError("Candidate CSV differs from the versioned release")
    paired = point_cases(pd.read_csv(CANDIDATE_CSV), mapped_ward_codes())
    points = paired.melt(
        id_vars=["ward_id", "origin", "target", "lead", "observed"],
        value_vars=list(MODELS),
        var_name="model",
        value_name="forecast",
    )
    incumbent_ranges = paired.loc[paired["origin"].ge(FIRST_SCORED_ORIGIN)].rename(columns={
        INCUMBENT: "forecast", "weighted_trend_lower": "lower", "weighted_trend_upper": "upper",
    })
    wards = add_intervals(points, scale_by_forecast=True)
    cities = add_intervals(city_cases(points), scale_by_forecast=False)
    wards = wards.loc[wards["origin"].ge(FIRST_SCORED_ORIGIN)]
    cities = cities.loc[cities["origin"].ge(FIRST_SCORED_ORIGIN)]
    full = summarize(wards, cities)
    development = summarize(wards.loc[wards["target"].le(HOLDOUT_ORIGIN)],
                            cities.loc[cities["target"].le(HOLDOUT_ORIGIN)])
    holdout_wards = wards.loc[wards["origin"].eq(HOLDOUT_ORIGIN)]
    holdout_cities = cities.loc[cities["origin"].eq(HOLDOUT_ORIGIN)]
    holdout = summarize(holdout_wards, holdout_cities)
    return {
        "source_id": manifest["source_id"],
        "observation_sha256": manifest["artifact"]["sha256"],
        "first_scored_origin": FIRST_SCORED_ORIGIN,
        "fixed_holdout_origin": HOLDOUT_ORIGIN,
        "nominal_interval_coverage": NOMINAL_COVERAGE,
        "minimum_prior_target_years_for_calibration": MIN_CALIBRATION_YEARS,
        "promotion_thresholds": {
            "minimum_equal_lead_mae_improvement_fraction": MIN_MAE_IMPROVEMENT,
            "maximum_lead_mae_regression_fraction": MAX_LEAD_MAE_REGRESSION,
            "maximum_fixed_holdout_city_absolute_bias_fraction": MAX_CITY_BIAS_FRACTION,
            "minimum_covered_target_years": MIN_COVERAGE_YEARS,
            "maximum_coverage_error": COVERAGE_TOLERANCE,
        },
        "full": full,
        "pre_holdout": development,
        "fixed_holdout": holdout,
        "incumbent_residual_range_diagnostics": {
            str(lead): predictions_summary(cases)["intervals"]
            for lead, cases in incumbent_ranges.groupby("lead")
        },
        "fixed_holdout_city_intervals": [
            {
                **row,
                "lower": int(row["lower"]) if row["calibration_years"] else None,
                "upper": int(row["upper"]) if row["calibration_years"] else None,
                "last_calibration_target": row["last_calibration_target"] if row["calibration_years"] else None,
            }
            for row in holdout_cities.loc[holdout_cities["model"].eq(MODEL), [
                "target", "observed", "forecast", "lower", "upper", "calibration_years", "last_calibration_target",
            ]].to_dict("records")
        ],
        "promotion_decision": promotion_decision(full, development, holdout),
    }


def precision(value):
    """Round displayed metrics without changing comparisons or counts."""
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: precision(item) for key, item in value.items()}
    if isinstance(value, list):
        return [precision(item) for item in value]
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(precision(evaluate()), indent=2, allow_nan=False))
